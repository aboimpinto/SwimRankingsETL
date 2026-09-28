#!/usr/bin/env python3
"""
Download and import official records from SwimRankings LENEX.

The SwimRankings RecordLenex endpoint returns one LENEX file per record list
and course. The importer stores current official records in dedicated tables so
website code can read records without scraping SwimRankings pages.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from swimrankings_http import download_bytes


DEFAULT_RECORD_LIST_IDS = ("50017", "50018", "50001", "50008", "50009", "50010")
RECORD_LIST_LABELS = {
    "50017": "Swiss Records",
    "50018": "Swiss Agegroup Records",
    "50001": "World Records",
    "50008": "World Junior Records",
    "50009": "European Records",
    "50010": "European Junior Records",
}
DEFAULT_COURSES = ("LCM", "SCM")
DEFAULT_POINTS = "fina_2025"
DEFAULT_LANGUAGE = "us"
DEFAULT_SAVE_DIR = Path("data/records")
RECORD_LENEX_BASE_URL = "https://www.swimrankings.net/services/RecordLenex/records.lxf"


@dataclass(frozen=True)
class SwimRankingsRecord:
    source_order: int
    record_list_id: str
    record_list_name: Optional[str]
    record_type: Optional[str]
    nation: Optional[str]
    course: str
    gender: str
    age_min: Optional[int]
    age_max: Optional[int]
    age_group_key: str
    age_group_label: str
    distance: int
    stroke: str
    relay_count: int
    swimtime_text: str
    time_seconds: Decimal
    points: Optional[int]
    record_date: Optional[date]
    record_updated: Optional[date]
    meetinfo_id: Optional[str]
    meet_name: Optional[str]
    meet_city: Optional[str]
    meet_nation: Optional[str]
    timing: Optional[str]
    athlete_id: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    birthdate: Optional[date]
    birth_year: Optional[int]
    athlete_gender: Optional[str]
    athlete_nation: Optional[str]
    club_id: Optional[str]
    club_code: Optional[str]
    club_name: Optional[str]
    club_nation: Optional[str]
    club_region: Optional[str]
    source_url: str
    source_hash: str
    splits: Tuple[Tuple[int, str, Decimal], ...]
    region: Optional[str] = None
    handicap: Optional[str] = None
    record_status: Optional[str] = None


@dataclass(frozen=True)
class SyncResult:
    record_list_id: str
    record_list_label: str
    course: str
    url: str
    file_name: str
    parsed: int
    deleted: int
    inserted: int
    dry_run: bool


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = " ".join(value.strip().split())
    return value or None


def parse_int(value: Optional[str]) -> Optional[int]:
    text = clean_text(value)
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def parse_date(value: Optional[str]) -> Optional[date]:
    text = clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def time_to_seconds(value: Optional[str]) -> Optional[Decimal]:
    text = clean_text(value)
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return Decimal(parts[0]) * Decimal("3600") + Decimal(parts[1]) * Decimal("60") + Decimal(parts[2])
        if len(parts) == 2:
            return Decimal(parts[0]) * Decimal("60") + Decimal(parts[1])
        return Decimal(text)
    except InvalidOperation:
        return None


def sanitize_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip("._-")
    return ascii_text or "swimrankings_records"


def age_group_key(age_min: Optional[int], age_max: Optional[int]) -> str:
    if age_min is not None and age_max is not None and age_min == age_max:
        return str(age_min)
    if age_max is not None and (age_min is None or age_min <= 0):
        return f"{age_max}u"
    if age_min is not None and age_max is not None:
        return f"{age_min}-{age_max}"
    return "open"


def age_group_label(age_min: Optional[int], age_max: Optional[int]) -> str:
    if age_min is not None and age_max is not None and age_min == age_max:
        return f"{age_min} years"
    if age_max is not None and (age_min is None or age_min <= 0):
        return f"{age_max} years and younger"
    if age_min is not None and age_max is not None:
        return f"{age_min}-{age_max} years"
    return "Open"


def build_record_lenex_url(
    record_list_id: str,
    course: str,
    points: str,
    language: str,
    base_url: str = RECORD_LENEX_BASE_URL,
) -> str:
    query = urlencode(
        {
            "RecordListId": record_list_id,
            "Course": course,
            "Points": points,
            "Language": language,
        }
    )
    return f"{base_url}?{query}"


def load_root_from_lxf_bytes(data: bytes) -> ET.Element:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            inner_name = next(
                name for name in archive.namelist() if name.lower().endswith((".lef", ".xml"))
            )
            return ET.fromstring(archive.read(inner_name))
    except zipfile.BadZipFile:
        return ET.fromstring(data)


def save_record_file(save_dir: Path, record_list_id: str, course: str, data: bytes) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{sanitize_filename(f'swimrankings_records_{record_list_id}_{course}')}.lxf"
    path.write_bytes(data)
    return path


def get_db_url(explicit_db_url: Optional[str]) -> str:
    if explicit_db_url:
        return explicit_db_url
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


def iter_recordlists(root: ET.Element) -> Iterable[ET.Element]:
    recordlists = root.find(".//RECORDLISTS")
    if recordlists is None:
        return []
    return recordlists.findall("RECORDLIST")


def parse_records(
    root: ET.Element,
    source_url: str,
    source_hash: str,
    fallback_record_list_id: str,
) -> List[SwimRankingsRecord]:
    records: List[SwimRankingsRecord] = []
    source_order = 0
    for recordlist in iter_recordlists(root):
        age_group = recordlist.find("AGEGROUP")
        age_min = parse_int(age_group.get("agemin")) if age_group is not None else None
        age_max = parse_int(age_group.get("agemax")) if age_group is not None else None
        record_list_id = clean_text(recordlist.get("recordlistid")) or fallback_record_list_id
        course = clean_text(recordlist.get("course")) or "LCM"
        gender = clean_text(recordlist.get("gender")) or "U"
        updated = parse_date(recordlist.get("updated"))

        for record in recordlist.findall("./RECORDS/RECORD"):
            swimstyle = record.find("SWIMSTYLE")
            if swimstyle is None:
                continue
            distance = parse_int(swimstyle.get("distance"))
            stroke = clean_text(swimstyle.get("stroke"))
            relay_count = parse_int(swimstyle.get("relaycount")) or 1
            swimtime_text = clean_text(record.get("swimtime"))
            time_seconds = time_to_seconds(swimtime_text)
            if distance is None or not stroke or not swimtime_text or time_seconds is None:
                continue

            meetinfo = record.find("MEETINFO")
            athlete = record.find("ATHLETE")
            club = athlete.find("CLUB") if athlete is not None else None

            split_rows: List[Tuple[int, str, Decimal]] = []
            for split in record.findall("./SPLITS/SPLIT"):
                split_distance = parse_int(split.get("distance"))
                split_time_text = clean_text(split.get("swimtime"))
                split_seconds = time_to_seconds(split_time_text)
                if split_distance is not None and split_time_text and split_seconds is not None:
                    split_rows.append((split_distance, split_time_text, split_seconds))

            birthdate = parse_date(athlete.get("birthdate")) if athlete is not None else None
            source_order += 1
            records.append(
                SwimRankingsRecord(
                    source_order=source_order,
                    record_list_id=record_list_id,
                    record_list_name=clean_text(recordlist.get("name")),
                    record_type=clean_text(recordlist.get("type")),
                    nation=clean_text(recordlist.get("nation")),
                    course=course,
                    gender=gender,
                    age_min=age_min,
                    age_max=age_max,
                    age_group_key=age_group_key(age_min, age_max),
                    age_group_label=age_group_label(age_min, age_max),
                    distance=distance,
                    stroke=stroke.upper(),
                    relay_count=relay_count,
                    swimtime_text=swimtime_text,
                    time_seconds=time_seconds,
                    points=parse_int(record.get("points")),
                    record_date=parse_date(meetinfo.get("date")) if meetinfo is not None else None,
                    record_updated=updated,
                    meetinfo_id=clean_text(meetinfo.get("meetinfoid")) if meetinfo is not None else None,
                    meet_name=clean_text(meetinfo.get("name")) if meetinfo is not None else None,
                    meet_city=clean_text(meetinfo.get("city")) if meetinfo is not None else None,
                    meet_nation=clean_text(meetinfo.get("nation")) if meetinfo is not None else None,
                    timing=clean_text(meetinfo.get("timing")) if meetinfo is not None else None,
                    athlete_id=clean_text(athlete.get("athleteid")) if athlete is not None else None,
                    first_name=clean_text(athlete.get("firstname")) if athlete is not None else None,
                    last_name=clean_text(athlete.get("lastname")) if athlete is not None else None,
                    birthdate=birthdate,
                    birth_year=birthdate.year if birthdate else None,
                    athlete_gender=clean_text(athlete.get("gender")) if athlete is not None else None,
                    athlete_nation=clean_text(athlete.get("nation")) if athlete is not None else None,
                    club_id=clean_text(club.get("clubid")) if club is not None else None,
                    club_code=clean_text(club.get("code")) if club is not None else None,
                    club_name=clean_text(club.get("name")) if club is not None else None,
                    club_nation=clean_text(club.get("nation")) if club is not None else None,
                    club_region=clean_text(club.get("region")) if club is not None else None,
                    source_url=source_url,
                    source_hash=source_hash,
                    splits=tuple(split_rows),
                    region=clean_text(recordlist.get("region")),
                    handicap=clean_text(recordlist.get("handicap")),
                    record_status=clean_text(record.get("status")),
                )
            )
    return records


def ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS swimrankings_records (
            id SERIAL PRIMARY KEY,
            source_order INTEGER NOT NULL DEFAULT 0,
            record_list_id TEXT NOT NULL,
            record_list_name TEXT,
            record_type TEXT,
            nation TEXT,
            course TEXT NOT NULL,
            gender TEXT NOT NULL,
            age_min INTEGER,
            age_max INTEGER,
            age_group_key TEXT NOT NULL,
            age_group_label TEXT NOT NULL,
            distance INTEGER NOT NULL,
            stroke TEXT NOT NULL,
            relay_count INTEGER NOT NULL DEFAULT 1,
            swimtime_text TEXT NOT NULL,
            time_seconds NUMERIC(10,2) NOT NULL,
            points INTEGER,
            record_date DATE,
            record_updated DATE,
            meetinfo_id TEXT,
            meet_name TEXT,
            meet_city TEXT,
            meet_nation TEXT,
            timing TEXT,
            athlete_id TEXT,
            first_name TEXT,
            last_name TEXT,
            birthdate DATE,
            birth_year INTEGER,
            athlete_gender TEXT,
            athlete_nation TEXT,
            club_id TEXT,
            club_code TEXT,
            club_name TEXT,
            club_nation TEXT,
            club_region TEXT,
            source_url TEXT,
            source_hash TEXT,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        ALTER TABLE swimrankings_records
        ADD COLUMN IF NOT EXISTS source_order INTEGER NOT NULL DEFAULT 0
        """
    )
    cur.execute("ALTER TABLE swimrankings_records ADD COLUMN IF NOT EXISTS region text, ADD COLUMN IF NOT EXISTS handicap text, ADD COLUMN IF NOT EXISTS record_status text")
    cur.execute("DROP INDEX IF EXISTS swimrankings_records_key")
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS swimrankings_records_key_idx
        ON swimrankings_records (
            record_list_id,
            course,
            gender,
            age_group_key,
            distance,
            stroke,
            relay_count,
            source_order
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS swimrankings_records_lookup_idx
        ON swimrankings_records (
            course,
            gender,
            age_min,
            age_max,
            distance,
            stroke
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS swimrankings_record_splits (
            id SERIAL PRIMARY KEY,
            record_id INTEGER NOT NULL REFERENCES swimrankings_records(id) ON DELETE CASCADE,
            distance INTEGER NOT NULL,
            swimtime_text TEXT NOT NULL,
            time_seconds NUMERIC(10,2) NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS swimrankings_record_splits_key
        ON swimrankings_record_splits (record_id, distance)
        """
    )


def insert_record(cur, record: SwimRankingsRecord) -> int:
    cur.execute(
        """
        INSERT INTO swimrankings_records (
            source_order,
            record_list_id,
            record_list_name,
            record_type,
            nation,
            course,
            gender,
            age_min,
            age_max,
            age_group_key,
            age_group_label,
            distance,
            stroke,
            relay_count,
            swimtime_text,
            time_seconds,
            points,
            record_date,
            record_updated,
            meetinfo_id,
            meet_name,
            meet_city,
            meet_nation,
            timing,
            athlete_id,
            first_name,
            last_name,
            birthdate,
            birth_year,
            athlete_gender,
            athlete_nation,
            club_id,
            club_code,
            club_name,
            club_nation,
            club_region,
            source_url,
            source_hash,
            imported_at
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,now()
        )
        RETURNING id
        """,
        (
            record.source_order,
            record.record_list_id,
            record.record_list_name,
            record.record_type,
            record.nation,
            record.course,
            record.gender,
            record.age_min,
            record.age_max,
            record.age_group_key,
            record.age_group_label,
            record.distance,
            record.stroke,
            record.relay_count,
            record.swimtime_text,
            record.time_seconds,
            record.points,
            record.record_date,
            record.record_updated,
            record.meetinfo_id,
            record.meet_name,
            record.meet_city,
            record.meet_nation,
            record.timing,
            record.athlete_id,
            record.first_name,
            record.last_name,
            record.birthdate,
            record.birth_year,
            record.athlete_gender,
            record.athlete_nation,
            record.club_id,
            record.club_code,
            record.club_name,
            record.club_nation,
            record.club_region,
            record.source_url,
            record.source_hash,
        ),
    )
    record_id = int(cur.fetchone()[0])
    cur.execute("UPDATE swimrankings_records SET region=%s,handicap=%s,record_status=%s WHERE id=%s",(record.region,record.handicap,record.record_status,record_id))
    return record_id


def insert_splits(cur, record_id: int, record: SwimRankingsRecord) -> None:
    for distance, swimtime_text, seconds in record.splits:
        cur.execute(
            """
            INSERT INTO swimrankings_record_splits (
                record_id,
                distance,
                swimtime_text,
                time_seconds
            )
            VALUES (%s,%s,%s,%s)
            """,
            (record_id, distance, swimtime_text, seconds),
        )


def import_records_for_course(
    conn,
    records: Sequence[SwimRankingsRecord],
    record_list_id: str,
    course: str,
) -> Tuple[int, int]:
    cur = conn.cursor()
    try:
        ensure_schema(cur)
        cur.execute(
            "DELETE FROM swimrankings_records WHERE record_list_id=%s AND course=%s",
            (record_list_id, course),
        )
        deleted = cur.rowcount

        inserted = 0
        for record in records:
            record_id = insert_record(cur, record)
            insert_splits(cur, record_id, record)
            inserted += 1

        conn.commit()
        return deleted, inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def record_list_label(record_list_id: str) -> str:
    return RECORD_LIST_LABELS.get(record_list_id, f"Record list {record_list_id}")


def sync_swimrankings_records(
    *,
    db_url: Optional[str],
    record_list_ids: Sequence[str] = DEFAULT_RECORD_LIST_IDS,
    courses: Sequence[str] = DEFAULT_COURSES,
    points: str = DEFAULT_POINTS,
    language: str = DEFAULT_LANGUAGE,
    save_dir: Path = DEFAULT_SAVE_DIR,
    dry_run: bool = False,
) -> List[SyncResult]:
    try:
        import psycopg2  # type: ignore
    except ImportError as exc:
        if dry_run:
            psycopg2 = None  # type: ignore
        else:
            raise RuntimeError("psycopg2 is required for database import. Install psycopg2-binary first.") from exc

    normalized_record_list_ids = [str(record_list_id).strip() for record_list_id in record_list_ids if str(record_list_id).strip()]
    if not normalized_record_list_ids:
        raise ValueError("At least one record list id must be provided.")

    normalized_courses = [course.strip().upper() for course in courses if course.strip()]
    if not normalized_courses:
        raise ValueError("At least one course must be provided.")

    conn = None
    if not dry_run:
        conn = psycopg2.connect(get_db_url(db_url))  # type: ignore[name-defined]

    results: List[SyncResult] = []
    try:
        for record_list_id in normalized_record_list_ids:
            for course in normalized_courses:
                url = build_record_lenex_url(record_list_id, course, points, language)
                raw_bytes = download_bytes(url)
                source_hash = hashlib.sha1(raw_bytes).hexdigest()
                saved_path = save_record_file(save_dir, record_list_id, course, raw_bytes)
                root = load_root_from_lxf_bytes(raw_bytes)
                records = parse_records(root, url, source_hash, record_list_id)
                course_records = [
                    record
                    for record in records
                    if record.record_list_id == record_list_id and record.course == course
                ]

                if dry_run:
                    deleted = 0
                    inserted = 0
                else:
                    assert conn is not None
                    deleted, inserted = import_records_for_course(
                        conn,
                        course_records,
                        record_list_id,
                        course,
                    )

                results.append(
                    SyncResult(
                        record_list_id=record_list_id,
                        record_list_label=record_list_label(record_list_id),
                        course=course,
                        url=url,
                        file_name=saved_path.name,
                        parsed=len(course_records),
                        deleted=deleted,
                        inserted=inserted,
                        dry_run=dry_run,
                    )
                )
    finally:
        if conn is not None:
            conn.close()

    return results


def sync_swiss_national_records(
    *,
    db_url: Optional[str],
    record_list_id: str = "50018",
    courses: Sequence[str] = DEFAULT_COURSES,
    points: str = DEFAULT_POINTS,
    language: str = DEFAULT_LANGUAGE,
    save_dir: Path = DEFAULT_SAVE_DIR,
    dry_run: bool = False,
) -> List[SyncResult]:
    return sync_swimrankings_records(
        db_url=db_url,
        record_list_ids=[record_list_id],
        courses=courses,
        points=points,
        language=language,
        save_dir=save_dir,
        dry_run=dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and import official records from SwimRankings."
    )
    parser.add_argument("--db-url", help="PostgreSQL connection string. If omitted, SWIMRANKINGS_DATABASE_URL is used.")
    parser.add_argument(
        "--record-list-ids",
        nargs="+",
        default=list(DEFAULT_RECORD_LIST_IDS),
        help="Record list ids to import. Default: Swiss senior/open, Swiss age-group, world, world junior, European, European junior.",
    )
    parser.add_argument("--record-list-id", help=argparse.SUPPRESS)
    parser.add_argument("--courses", nargs="+", default=list(DEFAULT_COURSES), help="Courses to import. Default: LCM SCM")
    parser.add_argument("--points", default=DEFAULT_POINTS)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Download and parse, but do not write database rows.")
    return parser


def print_summary(result: SyncResult) -> None:
    print(
        "SWIMRANKINGS_RECORDS "
        + f"record_list_id={result.record_list_id} "
        + f"record_list={result.record_list_label!r} "
        + f"course={result.course} "
        + f"parsed={result.parsed} "
        + f"deleted={result.deleted} "
        + f"inserted={result.inserted} "
        + f"file={result.file_name} "
        + f"dry_run={result.dry_run}",
        flush=True,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args()
    record_list_ids = [args.record_list_id] if args.record_list_id else args.record_list_ids
    try:
        results = sync_swimrankings_records(
            db_url=args.db_url,
            record_list_ids=record_list_ids,
            courses=args.courses,
            points=args.points,
            language=args.language,
            save_dir=args.save_dir,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for result in results:
        print_summary(result)

    print(
        "SWIMRANKINGS_RECORDS_DONE "
        + f"files={len(results)} "
        + f"record_lists={len(set(result.record_list_id for result in results))} "
        + f"parsed={sum(result.parsed for result in results)} "
        + f"deleted={sum(result.deleted for result in results)} "
        + f"inserted={sum(result.inserted for result in results)} "
        + f"dry_run={args.dry_run}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
