#!/usr/bin/env python3
"""
Import a month of live SwimRankings LENEX results into the canonical schema.

This runner is intentionally compatible with the older database schema present
in this checkout: countries, meets, events, swimmers, results, processing_log.
It does not require raw_import_files, raw_results, or swimmer_aliases.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import psycopg2
from psycopg2.extras import execute_values

from import_live_swimrankings_meet import (
    build_age_group_rankings,
    build_event_age_groups,
    canonical_swimmer_id,
    extract_meet_metadata,
    load_root_from_lxf_bytes,
    normalize_gender,
    parse_int,
    sanitize_filename,
    time_to_seconds,
)
from import_Swiss_NationalRecords import (
    DEFAULT_COURSES as DEFAULT_RECORD_COURSES,
    DEFAULT_RECORD_LIST_IDS,
    print_summary as print_record_summary,
    sync_swimrankings_records,
)


LIVE_INDEX_URL = "https://live.swimrankings.net/"
DEFAULT_SAVE_DIR = Path("data/lenex")
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass(frozen=True)
class LiveMeet:
    live_id: str
    url: str
    date_text: str
    start_date: date
    end_date: date
    course: str
    city: str
    country: Optional[str]
    name: str


@dataclass(frozen=True)
class ImportSummary:
    live_id: str
    status: str
    meet_id: Optional[str]
    meet_name: str
    meet_date: Optional[str]
    country: Optional[str]
    file_name: Optional[str]
    swimmers: int = 0
    results: int = 0
    reason: Optional[str] = None


class LiveIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[Tuple[str, str, str, str, str]] = []
        self._in_row = False
        self._in_cell = False
        self._cell_text: List[str] = []
        self._cells: List[str] = []
        self._href: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._href = None
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_text = []
        elif tag == "a" and self._in_row:
            href = attrs_dict.get("href") or ""
            if self._href is None and re.fullmatch(r"/\d+/?", href):
                self._href = href

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_cell:
            text = " ".join("".join(self._cell_text).split())
            self._cells.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._href and len(self._cells) >= 4:
                self.rows.append((self._href, self._cells[0], self._cells[1], self._cells[2], self._cells[3]))
            self._in_row = False


def download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def load_live_source(live_meet: LiveMeet, existing_path: Optional[Path]) -> Tuple[bytes, str]:
    if existing_path:
        return existing_path.read_bytes(), existing_path.as_posix()

    candidates = [
        live_meet.url.rstrip("/") + "/results.lxf",
        f"https://www.swimrankings.net/services/CalendarFile/{live_meet.live_id}/live/Results.lxf",
    ]
    errors = []
    for url in candidates:
        try:
            return download_bytes(url), url
        except HTTPError as exc:
            errors.append(f"{url} -> HTTP {exc.code}")
        except URLError as exc:
            errors.append(f"{url} -> {exc.reason}")
    raise RuntimeError("; ".join(errors))


def parse_date_text(text: str) -> Tuple[date, date]:
    text = " ".join(text.strip().split())
    single = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})", text)
    if single:
        day, month, year = single.groups()
        value = date(int(year), MONTHS[month], int(day))
        return value, value

    same_month = re.fullmatch(r"(\d{1,2}) - (\d{1,2}) ([A-Z][a-z]{2}) (\d{4})", text)
    if same_month:
        start_day, end_day, month, year = same_month.groups()
        return (
            date(int(year), MONTHS[month], int(start_day)),
            date(int(year), MONTHS[month], int(end_day)),
        )

    cross_month = re.fullmatch(
        r"(\d{1,2}) ([A-Z][a-z]{2}) - (\d{1,2}) ([A-Z][a-z]{2}) (\d{4})",
        text,
    )
    if cross_month:
        start_day, start_month, end_day, end_month, year = cross_month.groups()
        return (
            date(int(year), MONTHS[start_month], int(start_day)),
            date(int(year), MONTHS[end_month], int(end_day)),
        )

    raise ValueError(f"Unsupported live index date format: {text!r}")


def parse_city_country(text: str) -> Tuple[str, Optional[str]]:
    match = re.fullmatch(r"(.*)\s+\(([A-Z]{3})\)", text)
    if not match:
        return text.strip(), None
    city, country = match.groups()
    return city.strip(), country


def fetch_live_meets(index_url: str) -> List[LiveMeet]:
    html = download_bytes(index_url).decode("utf-8", "replace")
    parser = LiveIndexParser()
    parser.feed(html)

    meets: List[LiveMeet] = []
    for href, date_text, course, city_country, name in parser.rows:
        try:
            start_date, end_date = parse_date_text(date_text)
        except ValueError:
            continue
        city, country = parse_city_country(city_country)
        live_id = href.strip("/").split("/")[-1]
        meets.append(
            LiveMeet(
                live_id=live_id,
                url=urljoin(index_url, href),
                date_text=date_text,
                start_date=start_date,
                end_date=end_date,
                course=course,
                city=city,
                country=country,
                name=name,
            )
        )
    return meets


def overlaps_month(meet: LiveMeet, year: int, month: int) -> bool:
    month_start = date(year, month, 1)
    month_end = date(year + (month // 12), (month % 12) + 1, 1)
    return meet.start_date < month_end and meet.end_date >= month_start


def get_db_url(args: argparse.Namespace) -> str:
    if args.db_url:
        return args.db_url
    env_url = os.getenv("SWIMRANKINGS_DATABASE_URL")
    if env_url:
        return env_url
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5433")
    user = os.getenv("PGUSER", "hushuser")
    password = os.getenv("PGPASSWORD")
    database = os.getenv("PGDATABASE", "swimrankings")
    if not password:
        raise RuntimeError(
            "Set SWIMRANKINGS_DATABASE_URL, pass --db-url, or provide PGPASSWORD before running an import."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def ensure_country(cur, code: Optional[str]) -> None:
    if not code:
        return
    cur.execute("SELECT 1 FROM countries WHERE code=%s LIMIT 1", (code,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO countries (code, name, excluded) VALUES (%s, %s, false) "
            "ON CONFLICT (code) DO NOTHING",
            (code, code),
        )


def ensure_meet(
    cur,
    meet_id: str,
    name: str,
    city: Optional[str],
    nation: Optional[str],
    meet_date: Optional[str],
    pool_length: int,
) -> int:
    cur.execute("SELECT id FROM meets WHERE meet_id=%s LIMIT 1", (meet_id,))
    row = cur.fetchone()
    if row:
        meet_db_id = row[0]
    else:
        cur.execute(
            "INSERT INTO meets (meet_id, name, city, country_code, start_date, pool_length) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (meet_id, name, city, nation, meet_date, pool_length),
        )
        meet_db_id = cur.fetchone()[0]
    cur.execute(
        "UPDATE meets SET city = COALESCE(city, %s), pool_length = COALESCE(pool_length, %s) "
        "WHERE id=%s",
        (city, pool_length, meet_db_id),
    )
    return meet_db_id


def existing_result_count(cur, meet_id: str) -> int:
    cur.execute(
        """
        SELECT count(r.id)
          FROM meets m
          JOIN results r ON r.meet_id = m.id
         WHERE m.meet_id = %s
        """,
        (meet_id,),
    )
    return int(cur.fetchone()[0])


def already_processed_same_file(cur, file_name: str, file_hash: str) -> Optional[int]:
    cur.execute(
        """
        SELECT result_count
          FROM processing_log
         WHERE file_name=%s
           AND file_fingerprint=%s
           AND status='success'
         LIMIT 1
        """,
        (file_name, file_hash),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def ensure_event(cur, distance: int, stroke: str, gender: str, pool_length: int) -> int:
    cur.execute(
        "SELECT id FROM events WHERE distance=%s AND stroke=%s AND gender=%s AND pool_length=%s LIMIT 1",
        (distance, stroke, gender, pool_length),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO events (distance, stroke, gender, pool_length) VALUES (%s,%s,%s,%s) RETURNING id",
        (distance, stroke, gender, pool_length),
    )
    return cur.fetchone()[0]


def resolve_swimmer(
    cur,
    athlete_id: Optional[str],
    first_name: str,
    last_name: str,
    birth_year: int,
    nation: str,
    gender: str,
) -> int:
    if athlete_id:
        cur.execute(
            """
            SELECT id, first_name, last_name, birth_year, country_code, gender
              FROM swimmers
             WHERE swimmer_id=%s
             LIMIT 1
            """,
            (athlete_id,),
        )
        row = cur.fetchone()
        if row and (
            row[1] == first_name
            and row[2] == last_name
            and row[3] == birth_year
            and row[4] == nation
            and row[5] == gender
        ):
            return row[0]

    cur.execute(
        """
        SELECT id
          FROM swimmers
         WHERE first_name=%s
           AND last_name=%s
           AND birth_year=%s
           AND country_code=%s
           AND gender=%s
         ORDER BY id
         LIMIT 1
        """,
        (first_name, last_name, birth_year, nation, gender),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    swimmer_canon = canonical_swimmer_id(nation, gender, birth_year, first_name, last_name)
    cur.execute(
        """
        INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (swimmer_id) DO UPDATE SET
            first_name=EXCLUDED.first_name
        RETURNING id
        """,
        (swimmer_canon, first_name, last_name, birth_year, nation, gender),
    )
    return cur.fetchone()[0]


def iter_athletes(root) -> Iterable:
    clubs = root.find(".//CLUBS")
    if clubs is None:
        yield from root.findall(".//ATHLETE")
        return
    for club in clubs.findall("CLUB"):
        athletes = club.find("ATHLETES")
        if athletes is None:
            continue
        yield from athletes.findall("ATHLETE")


def find_existing_lxf(save_dir: Path, live_id: str) -> Optional[Path]:
    matches = sorted(save_dir.glob(f"*_{live_id}_*.lxf"))
    return matches[0] if matches else None


def save_lxf(save_dir: Path, live_id: str, meet_name: str, meet_date: Optional[str], nation: str, data: bytes) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_filename(f"{nation}_{meet_date}_{live_id}_{meet_name}")
    path = save_dir / f"{stem}.lxf"
    if not path.exists():
        path.write_bytes(data)
    return path


def parse_result_splits(result) -> List[Tuple[int, object, int]]:
    split_rows: List[Tuple[int, object, int]] = []
    splits = result.find("SPLITS")
    if splits is None:
        return split_rows

    for split_order, split in enumerate(splits.findall("SPLIT"), 1):
        distance = parse_int(split.get("distance"))
        split_seconds = time_to_seconds(split.get("swimtime"))
        if distance is None or split_seconds is None:
            continue
        split_rows.append((distance, split_seconds, split_order))
    return split_rows


def build_meet_id(meet_name: str, meet_date: Optional[str]) -> str:
    if meet_date:
        return f"{meet_name}_{meet_date}".replace(" ", "_")[:100]
    return meet_name.replace(" ", "_")[:100]


def fetch_result_ids(cur, rows: Sequence[Tuple[object, ...]]) -> Dict[int, int]:
    if not rows:
        return {}

    lookup_rows = [
        (index, row[0], row[1], row[2], row[5], row[3], row[7])
        for index, row in enumerate(rows)
    ]
    found_rows = execute_values(
        cur,
        """
        WITH input_rows(row_index, swimmer_id, meet_id, event_id, heat, time_seconds, result_date) AS (
            VALUES %s
        )
        SELECT input_rows.row_index, r.id
          FROM input_rows
          JOIN results r
            ON r.swimmer_id = input_rows.swimmer_id
           AND r.meet_id = input_rows.meet_id
           AND r.event_id = input_rows.event_id
           AND (
                (input_rows.heat IS NOT NULL AND r.heat = input_rows.heat)
                OR (
                    input_rows.heat IS NULL
                    AND r.heat IS NULL
                    AND r.result_date IS NOT DISTINCT FROM input_rows.result_date::date
                    AND ABS(r.time_seconds - input_rows.time_seconds) < 0.0001
                )
           )
         ORDER BY input_rows.row_index, r.id
        """,
        lookup_rows,
        page_size=1000,
        fetch=True,
    )

    result_ids: Dict[int, int] = {}
    ambiguous_indexes = set()
    for row_index, result_id in found_rows:
        if row_index in result_ids:
            ambiguous_indexes.add(row_index)
            continue
        result_ids[row_index] = result_id

    for row_index in ambiguous_indexes:
        result_ids.pop(row_index, None)
    return result_ids


def replace_result_splits(cur, rows: Sequence[Tuple[object, ...]]) -> None:
    result_ids = fetch_result_ids(cur, rows)
    split_values = []
    result_ids_with_splits = set()

    for index, row in enumerate(rows):
        splits = row[9]
        if not splits:
            continue
        result_id = result_ids.get(index)
        if result_id is None:
            continue
        result_ids_with_splits.add(result_id)
        for distance, split_seconds, split_order in splits:
            split_values.append((result_id, distance, split_seconds, split_order))

    if not split_values:
        return

    cur.execute("DELETE FROM splits WHERE result_id = ANY(%s)", (list(result_ids_with_splits),))
    execute_values(
        cur,
        """
        INSERT INTO splits (result_id, distance, time_seconds, split_order)
        VALUES %s
        """,
        split_values,
        page_size=1000,
    )


def import_meet(conn, live_meet: LiveMeet, save_dir: Path, dry_run: bool = False) -> ImportSummary:
    existing_path = find_existing_lxf(save_dir, live_meet.live_id)
    try:
        raw_bytes, source_ref = load_live_source(live_meet, existing_path)
        root = load_root_from_lxf_bytes(raw_bytes)
    except (RuntimeError, StopIteration, ValueError) as exc:
        return ImportSummary(
            live_id=live_meet.live_id,
            status="failed",
            meet_id=None,
            meet_name=live_meet.name,
            meet_date=live_meet.start_date.isoformat(),
            country=live_meet.country,
            file_name=None,
            reason=f"download_or_parse_failed: {exc}",
        )

    meta = extract_meet_metadata(root)
    meet_name = str(meta["name"])
    meet_date = str(meta["date"]) if meta["date"] else None
    meet_nation = str(meta["nation"] or live_meet.country or "UNK")
    meet_city = meta["city"] or live_meet.city
    pool_length = int(meta["pool_length"])
    meet_id = build_meet_id(meet_name, meet_date)
    file_hash = hashlib.sha1(raw_bytes).hexdigest()
    club_source = hashlib.sha256(raw_bytes).hexdigest()
    if existing_path:
        saved_path = existing_path
    elif dry_run:
        stem = sanitize_filename(f"{meet_nation}_{meet_date}_{live_meet.live_id}_{meet_name}")
        saved_path = save_dir / f"{stem}.lxf"
    else:
        saved_path = save_lxf(save_dir, live_meet.live_id, meet_name, meet_date, meet_nation, raw_bytes)

    cur = conn.cursor()
    try:
        already_loaded = existing_result_count(cur, meet_id)
        if already_loaded > 0:
            conn.rollback()
            return ImportSummary(
                live_id=live_meet.live_id,
                status="skipped_existing",
                meet_id=meet_id,
                meet_name=meet_name,
                meet_date=meet_date,
                country=meet_nation,
                file_name=saved_path.name,
                results=already_loaded,
                reason="meet already has result rows",
            )

        processed_result_count = already_processed_same_file(cur, saved_path.name, file_hash)
        if processed_result_count is not None:
            conn.rollback()
            return ImportSummary(
                live_id=live_meet.live_id,
                status="skipped_processed",
                meet_id=meet_id,
                meet_name=meet_name,
                meet_date=meet_date,
                country=meet_nation,
                file_name=saved_path.name,
                results=processed_result_count,
                reason="same source file already processed",
            )

        if dry_run:
            conn.rollback()
            return ImportSummary(
                live_id=live_meet.live_id,
                status="would_import",
                meet_id=meet_id,
                meet_name=meet_name,
                meet_date=meet_date,
                country=meet_nation,
                file_name=saved_path.name,
                reason=source_ref,
            )

        cur.execute("ALTER TABLE results ADD COLUMN IF NOT EXISTS club_name text, ADD COLUMN IF NOT EXISTS club_source text, ADD COLUMN IF NOT EXISTS status text")
        ensure_country(cur, meet_nation)
        meet_db_id = ensure_meet(cur, meet_id, meet_name, meet_city, meet_nation, meet_date, pool_length)

        event_cache: Dict[str, int] = {}
        event_meta: Dict[str, Tuple[int, str, str, int, bool, Optional[int]]] = {}
        event_rounds: Dict[str, Optional[str]] = {}
        for event in root.findall(".//EVENT"):
            source_event_id = (event.get("eventid") or "").strip()
            swimstyle = event.find("SWIMSTYLE")
            if not source_event_id or swimstyle is None:
                continue
            distance = parse_int(swimstyle.get("distance")) or 0
            stroke = (swimstyle.get("stroke") or "FREE").strip().upper()
            gender = normalize_gender(event.get("gender"), "U")
            relay_count = parse_int(swimstyle.get("relaycount")) or 1
            event_meta[source_event_id] = (
                distance,
                stroke,
                gender,
                pool_length,
                relay_count > 1,
                relay_count if relay_count > 1 else None,
            )
            event_rounds[source_event_id] = (event.get("round") or "").strip().upper() or None

        # Some LENEX files, including Swiss national championships, store
        # placements in EVENT/AGEGROUPS/RANKINGS rather than on RESULT itself.
        ranking_map = build_age_group_rankings(root)
        event_age_groups = build_event_age_groups(root)

        club_names = {id(athlete): (club.get("name") or "").strip() or None
                      for club in root.findall(".//CLUB") for athlete in club.findall("./ATHLETES/ATHLETE")}
        event_dates = {(event.get("eventid") or "").strip(): session.get("date") or meet_date
                       for session in root.findall(".//SESSION") for event in session.findall(".//EVENT")}
        result_rows: List[Tuple[object, ...]] = []
        unique_swimmers = set()
        selected_athletes: Dict[str, int] = {}
        for athlete in iter_athletes(root):
            first_name = (athlete.get("firstname") or "").strip()
            last_name = (athlete.get("lastname") or "").strip()
            if not first_name or not last_name:
                continue
            birthdate = (athlete.get("birthdate") or "").strip()
            birth_year = parse_int(birthdate[:4])
            if birth_year is None:
                continue
            athlete_id = (athlete.get("athleteid") or "").strip() or None
            gender = normalize_gender(athlete.get("gender"), "U")
            nation = (athlete.get("nation") or meet_nation or "UNK").strip() or "UNK"
            ensure_country(cur, nation)
            swimmer_pk = resolve_swimmer(cur, athlete_id, first_name, last_name, birth_year, nation, gender)
            unique_swimmers.add(swimmer_pk)
            if athlete_id:
                selected_athletes[athlete_id] = swimmer_pk

            results_elem = athlete.find("RESULTS")
            if results_elem is None:
                continue
            for result in results_elem.findall("RESULT"):
                source_event_id = (result.get("eventid") or "").strip()
                if source_event_id not in event_meta:
                    continue
                if source_event_id not in event_cache:
                    distance, stroke, event_gender, event_pool_length, _, _ = event_meta[source_event_id]
                    event_cache[source_event_id] = ensure_event(cur, distance, stroke, event_gender, event_pool_length)
                swimtime_text = (result.get("swimtime") or "").strip()
                time_seconds = time_to_seconds(swimtime_text)
                if time_seconds is None:
                    continue
                rank = parse_int(result.get("rank")) or parse_int(result.get("place"))
                heat = parse_int(result.get("heatid"))
                lane = parse_int(result.get("lane"))
                reaction_time = (result.get("reactiontime") or "").strip() or None
                split_rows = parse_result_splits(result)
                age_group_info = ranking_map.get(
                    (source_event_id, (result.get("resultid") or "").strip())
                ) or event_age_groups.get(source_event_id)
                result_rows.append(
                    (
                        swimmer_pk,
                        meet_db_id,
                        event_cache[source_event_id],
                        time_seconds,
                        rank,
                        heat,
                        lane,
                        event_dates.get(source_event_id, meet_date),
                        reaction_time,
                        split_rows,
                        age_group_info.source_age_group_id if age_group_info else None,
                        age_group_info.age_group_min if age_group_info else None,
                        age_group_info.age_group_max if age_group_info else None,
                        age_group_info.age_group_label if age_group_info else None,
                        age_group_info.age_group_rank if age_group_info else None,
                        age_group_info.age_group_order if age_group_info else None,
                        event_rounds.get(source_event_id),
                        False,
                        None,
                        club_names.get(id(athlete)),
                        club_source if club_names.get(id(athlete)) else None,
                        (result.get("status") or "").strip() or None,
                    )
                )

        # Relay teams are separate LENEX records. Associate each team result
        # with every selected member referenced by RELAYPOSITION.
        for relay in root.findall(".//RELAY"):
            for result in relay.findall("./RESULTS/RESULT"):
                source_event_id = (result.get("eventid") or "").strip()
                if source_event_id not in event_meta:
                    continue
                distance, stroke, event_gender, event_pool_length, is_relay, relay_count = event_meta[source_event_id]
                if not is_relay:
                    continue
                if source_event_id not in event_cache:
                    event_cache[source_event_id] = ensure_event(
                        cur, distance, stroke, event_gender, event_pool_length
                    )
                time_seconds = time_to_seconds((result.get("swimtime") or "").strip())
                if time_seconds is None or time_seconds <= 0:
                    continue
                age_group_info = ranking_map.get(
                    (source_event_id, (result.get("resultid") or "").strip())
                ) or event_age_groups.get(source_event_id)
                rank = parse_int(result.get("rank")) or parse_int(result.get("place"))
                heat = parse_int(result.get("heatid"))
                lane = parse_int(result.get("lane"))
                reaction_time = (result.get("reactiontime") or "").strip() or None
                split_rows = parse_result_splits(result)

                for position in result.findall("./RELAYPOSITIONS/RELAYPOSITION"):
                    swimmer_pk = selected_athletes.get((position.get("athleteid") or "").strip())
                    if swimmer_pk is None:
                        continue
                    result_rows.append(
                        (
                            swimmer_pk,
                            meet_db_id,
                            event_cache[source_event_id],
                            time_seconds,
                            rank,
                            heat,
                            lane,
                            meet_date,
                            reaction_time,
                            split_rows,
                            age_group_info.source_age_group_id if age_group_info else None,
                            age_group_info.age_group_min if age_group_info else None,
                            age_group_info.age_group_max if age_group_info else None,
                            age_group_info.age_group_label if age_group_info else None,
                            age_group_info.age_group_rank if age_group_info else None,
                            age_group_info.age_group_order if age_group_info else None,
                            event_rounds.get(source_event_id),
                            True,
                            relay_count,
                            None,
                            None,
                            (result.get("status") or "").strip() or None,
                        )
                    )

        deduped_rows = []
        seen = set()
        for row in result_rows:
            key = (row[0], row[1], row[2], row[5])
            if key in seen:
                continue
            seen.add(key)
            deduped_rows.append(row)

        if deduped_rows:
            execute_values(
                cur,
                """
                INSERT INTO results (
                    swimmer_id,
                    meet_id,
                    event_id,
                    time_seconds,
                    rank,
                    heat,
                    lane,
                    result_date,
                    reaction_time,
                    age_group_id,
                    age_group_min,
                    age_group_max,
                    age_group_label,
                    age_group_rank,
                    age_group_order,
                    event_round,
                    is_relay,
                    relay_count,
                    club_name,
                    club_source,
                    status
                )
                VALUES %s
                ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO UPDATE SET
                    time_seconds=EXCLUDED.time_seconds,
                    rank=EXCLUDED.rank,
                    lane=EXCLUDED.lane,
                    result_date=EXCLUDED.result_date,
                    reaction_time=COALESCE(EXCLUDED.reaction_time, results.reaction_time),
                    age_group_id=EXCLUDED.age_group_id,
                    age_group_min=EXCLUDED.age_group_min,
                    age_group_max=EXCLUDED.age_group_max,
                    age_group_label=EXCLUDED.age_group_label,
                    age_group_rank=EXCLUDED.age_group_rank,
                    age_group_order=EXCLUDED.age_group_order,
                    event_round=EXCLUDED.event_round,
                    is_relay=EXCLUDED.is_relay,
                    relay_count=EXCLUDED.relay_count,
                    club_name=EXCLUDED.club_name,
                    club_source=EXCLUDED.club_source,
                    status=EXCLUDED.status
                """,
                [row[:9] + row[10:] for row in deduped_rows],
                page_size=1000,
            )
            replace_result_splits(cur, deduped_rows)

        cur.execute(
            """
            INSERT INTO processing_log (file_name, status, processed_date, swimmer_count, result_count, error_msg, file_fingerprint)
            VALUES (%s, 'success', now(), %s, %s, NULL, %s)
            ON CONFLICT (file_name) DO UPDATE SET
                status='success',
                processed_date=now(),
                swimmer_count=EXCLUDED.swimmer_count,
                result_count=EXCLUDED.result_count,
                error_msg=NULL,
                file_fingerprint=EXCLUDED.file_fingerprint
            """,
            (saved_path.name, len(unique_swimmers), len(deduped_rows), file_hash),
        )

        conn.commit()
        return ImportSummary(
            live_id=live_meet.live_id,
            status="imported",
            meet_id=meet_id,
            meet_name=meet_name,
            meet_date=meet_date,
            country=meet_nation,
            file_name=saved_path.name,
            swimmers=len(unique_swimmers),
            results=len(deduped_rows),
        )
    except Exception as exc:
        conn.rollback()
        return ImportSummary(
            live_id=live_meet.live_id,
            status="failed",
            meet_id=meet_id,
            meet_name=meet_name,
            meet_date=meet_date,
            country=meet_nation,
            file_name=saved_path.name,
            reason=f"{type(exc).__name__}: {exc}",
        )
    finally:
        cur.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a month from live.swimrankings.net.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--through-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--index-url", default=LIVE_INDEX_URL)
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    parser.add_argument("--db-url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-future",
        action="store_true",
        help="Include meets whose start date is after --through-date.",
    )
    parser.add_argument(
        "--skip-records",
        dest="skip_records",
        action="store_true",
        help="Emergency flag: skip the official records sync before live meet import.",
    )
    parser.add_argument(
        "--skip-swiss-records",
        dest="skip_records",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--record-list-ids",
        nargs="+",
        default=list(DEFAULT_RECORD_LIST_IDS),
        help="SwimRankings record list ids to sync before importing live meets.",
    )
    parser.add_argument(
        "--swiss-record-list-id",
        dest="legacy_swiss_record_list_id",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--record-courses",
        nargs="+",
        default=list(DEFAULT_RECORD_COURSES),
        help="Official record courses to sync before importing live meets. Default: LCM SCM.",
    )
    parser.add_argument(
        "--swiss-record-courses",
        dest="record_courses",
        nargs="+",
        help=argparse.SUPPRESS,
    )
    return parser


def print_summary(summary: ImportSummary) -> None:
    fields = [
        summary.status,
        f"id={summary.live_id}",
        f"date={summary.meet_date}",
        f"country={summary.country}",
        f"results={summary.results}",
        f"name={summary.meet_name}",
    ]
    if summary.reason:
        fields.append(f"reason={summary.reason}")
    print(" | ".join(fields), flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args()
    db_url: Optional[str] = None

    record_list_ids = (
        [args.legacy_swiss_record_list_id]
        if args.legacy_swiss_record_list_id
        else args.record_list_ids
    )

    if not args.skip_records:
        if not args.dry_run:
            db_url = get_db_url(args)
        record_results = sync_swimrankings_records(
            db_url=db_url,
            record_list_ids=record_list_ids,
            courses=args.record_courses,
            dry_run=args.dry_run,
        )
        for record_result in record_results:
            print_record_summary(record_result)

    meets = [
        meet
        for meet in fetch_live_meets(args.index_url)
        if overlaps_month(meet, args.year, args.month)
        and (args.include_future or meet.start_date <= args.through_date)
    ]
    meets.sort(key=lambda meet: (meet.start_date, meet.live_id))

    print(
        f"LIVE_IMPORT_PLAN year={args.year} month={args.month} through={args.through_date} meets={len(meets)} dry_run={args.dry_run}",
        flush=True,
    )
    if not meets:
        return 0

    if db_url is None:
        db_url = get_db_url(args)
    conn = psycopg2.connect(db_url)
    try:
        summaries = [import_meet(conn, meet, args.save_dir, args.dry_run) for meet in meets]
    finally:
        conn.close()

    counts: Dict[str, int] = {}
    total_results = 0
    for summary in summaries:
        counts[summary.status] = counts.get(summary.status, 0) + 1
        if summary.status == "imported":
            total_results += summary.results
        print_summary(summary)

    print(
        "DONE "
        + " ".join(f"{status}={count}" for status, count in sorted(counts.items()))
        + f" total_imported_results={total_results}",
        flush=True,
    )
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
