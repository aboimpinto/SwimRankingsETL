#!/usr/bin/env python3
"""Authenticated, session-aware HTTP downloads for SwimRankings services."""

from __future__ import annotations

import base64
import io
import os
import time
import zipfile
from dataclasses import dataclass
from email.message import Message
from http.cookiejar import CookieJar
from typing import Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPCookieProcessor,
    HTTPPasswordMgrWithDefaultRealm,
    Request,
    build_opener,
)


DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRIES = 3
DEFAULT_USER_AGENT = "SwimRankingsETL/1.0 (+https://github.com/aboimpinto/SwimRankingsETL)"
SWIMRANKINGS_ORIGINS = (
    "https://www.swimrankings.net/",
    "https://live.swimrankings.net/",
)


class SwimRankingsDownloadError(RuntimeError):
    """A download completed unsuccessfully or did not contain LENEX data."""


class SwimRankingsAuthenticationError(SwimRankingsDownloadError):
    """A protected SwimRankings service rejected or lacked credentials."""


class SwimRankingsRateLimitError(SwimRankingsDownloadError):
    """The service reports that the current meet-download quota is exhausted."""


@dataclass(frozen=True)
class DownloadedFile:
    data: bytes
    final_url: str
    content_type: Optional[str]


def credentials_from_environment(
    environ: Mapping[str, str] = os.environ,
) -> tuple[Optional[str], Optional[str]]:
    username = environ.get("SWIMRANKINGS_HTTP_USERNAME")
    password = environ.get("SWIMRANKINGS_HTTP_PASSWORD")
    if bool(username) != bool(password):
        raise SwimRankingsAuthenticationError(
            "Set both SWIMRANKINGS_HTTP_USERNAME and SWIMRANKINGS_HTTP_PASSWORD, or neither."
        )
    return username, password


class SwimRankingsHttpClient:
    """Keep cookies and HTTP Basic authentication available across a batch."""

    def __init__(
        self,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        sleeper: Callable[[float], None] = time.sleep,
        auth_origins: Sequence[str] = SWIMRANKINGS_ORIGINS,
    ) -> None:
        if bool(username) != bool(password):
            raise SwimRankingsAuthenticationError("A username and password must be supplied together.")
        self.has_credentials = bool(username and password)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.sleeper = sleeper
        self.auth_origins = tuple(auth_origins)
        self.authorization_header = (
            "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            if username and password
            else None
        )

        password_manager = HTTPPasswordMgrWithDefaultRealm()
        if username and password:
            for origin in self.auth_origins:
                password_manager.add_password(None, origin, username, password)
                password_manager.add_password("Rankings HTTP Service 5", origin, username, password)

        self.opener = build_opener(
            HTTPCookieProcessor(CookieJar()),
            HTTPBasicAuthHandler(password_manager),
        )

    @classmethod
    def from_environment(cls, **kwargs: object) -> "SwimRankingsHttpClient":
        username, password = credentials_from_environment()
        return cls(username=username, password=password, **kwargs)

    def download(self, url: str) -> DownloadedFile:
        headers = {
            "Accept": "application/zip, application/octet-stream, application/xml, text/xml;q=0.9, */*;q=0.5",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        request = Request(
            url,
            headers=headers,
        )
        if self.authorization_header and self._uses_auth_origin(url):
            # Send credentials on the initial service request so a public-looking
            # HTTP 200 quota response cannot mask the authenticated route. Using
            # an unredirected header prevents forwarding the secret to another
            # host if the service ever redirects externally.
            request.add_unredirected_header("Authorization", self.authorization_header)

        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return DownloadedFile(
                        data=response.read(),
                        final_url=response.geturl(),
                        content_type=response.headers.get_content_type(),
                    )
            except HTTPError as exc:
                response_headers = exc.headers
                exc.close()
                if exc.code == 401:
                    if self.has_credentials:
                        raise SwimRankingsAuthenticationError(
                            f"SwimRankings rejected the HTTP credentials for {url}."
                        ) from exc
                    raise SwimRankingsAuthenticationError(
                        "This SwimRankings LENEX file is protected. Set "
                        "SWIMRANKINGS_HTTP_USERNAME and SWIMRANKINGS_HTTP_PASSWORD."
                    ) from exc
                if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise
                self.sleeper(_retry_delay(response_headers, attempt))
            except URLError:
                if attempt >= self.retries:
                    raise
                self.sleeper(2 ** attempt)

        raise AssertionError("unreachable")

    def _uses_auth_origin(self, url: str) -> bool:
        target = urlsplit(url)
        return any(
            target.scheme == origin_parts.scheme and target.netloc == origin_parts.netloc
            for origin_parts in (urlsplit(origin) for origin in self.auth_origins)
        )


def _retry_delay(headers: Message, attempt: int) -> float:
    retry_after = headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), 60.0)
    return min(float(2 ** attempt), 30.0)


def validate_lenex_payload(download: DownloadedFile) -> None:
    data = download.data
    if not data:
        raise SwimRankingsDownloadError(f"SwimRankings returned an empty response for {download.final_url}.")

    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            if any(name.lower().endswith((".lef", ".xml")) for name in archive.namelist()):
                return
    except zipfile.BadZipFile:
        pass

    start = data.lstrip()[:256].lower()
    if start.startswith(b"<?xml") or start.startswith(b"<lenex"):
        return

    response_text = data[:1024].decode("utf-8", "replace").lower()
    if "reached your daily limit for meets" in response_text:
        raise SwimRankingsRateLimitError(
            "SwimRankings reports that the meet-download daily limit has been reached. "
            "Use an authorized account if its entitlement permits more downloads, or wait for the quota to reset."
        )

    raise SwimRankingsDownloadError(
        f"Expected LENEX data from {download.final_url}, but received "
        f"{download.content_type or 'an unknown content type'}."
    )


_default_client: Optional[SwimRankingsHttpClient] = None


def get_default_client() -> SwimRankingsHttpClient:
    global _default_client
    if _default_client is None:
        _default_client = SwimRankingsHttpClient.from_environment()
    return _default_client


def download_bytes(url: str) -> bytes:
    download = get_default_client().download(url)
    validate_lenex_payload(download)
    return download.data
