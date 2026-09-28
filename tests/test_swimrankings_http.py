from __future__ import annotations

import base64
import io
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.swimrankings_http import (
    DownloadedFile,
    SwimRankingsAuthenticationError,
    SwimRankingsDownloadError,
    SwimRankingsHttpClient,
    SwimRankingsRateLimitError,
    validate_lenex_payload,
)


def lenex_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("LenexData.lef", '<?xml version="1.0"?><LENEX version="3.0"/>')
    return output.getvalue()


class DownloadHandler(BaseHTTPRequestHandler):
    expected_authorization = "Basic " + base64.b64encode(b"etl-user:etl-password").decode("ascii")
    payload = lenex_bytes()

    def do_GET(self) -> None:
        if self.path == "/protected.lxf" and self.headers.get("Authorization") != self.expected_authorization:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Rankings HTTP Service 5"')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class SwimRankingsHttpClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def test_downloads_public_lenex(self) -> None:
        download = SwimRankingsHttpClient().download(f"{self.base_url}/public.lxf")
        validate_lenex_payload(download)

    def test_protected_download_requires_credentials(self) -> None:
        with self.assertRaises(SwimRankingsAuthenticationError):
            SwimRankingsHttpClient().download(f"{self.base_url}/protected.lxf")

    def test_reuses_client_for_consecutive_authenticated_downloads(self) -> None:
        client = SwimRankingsHttpClient(
            username="etl-user",
            password="etl-password",
            auth_origins=(self.base_url,),
        )
        for _ in range(2):
            download = client.download(f"{self.base_url}/protected.lxf")
            validate_lenex_payload(download)

    def test_rejects_non_lenex_response(self) -> None:
        with self.assertRaises(SwimRankingsDownloadError):
            validate_lenex_payload(
                DownloadedFile(
                    data=b"<html>Cloudflare challenge</html>",
                    final_url="https://www.swimrankings.net/index.php",
                    content_type="text/html",
                )
            )

    def test_reports_daily_limit_response(self) -> None:
        with self.assertRaises(SwimRankingsRateLimitError):
            validate_lenex_payload(
                DownloadedFile(
                    data=b"This feature is not available for the selected meet or you reached your daily limit for meets.",
                    final_url="https://www.swimrankings.net/services/ResultLenex/results.lxf",
                    content_type="text/plain",
                )
            )


if __name__ == "__main__":
    unittest.main()
