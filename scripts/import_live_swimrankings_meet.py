#!/usr/bin/env python3
"""
Import a LENEX `.lxf` meet file with an optional live SwimRankings download step.

Primary workflow:
- use an existing local `.lxf` file as the source of truth
- parse LENEX with the Python standard library
- filter athletes by age using the meet AGEDATE
- write raw staging rows and canonical rows into the SwimRankings database

Optional workflow:
- if no local `.lxf` file is provided, download `results.lxf` from a live meet URL

Examples:
  python scripts/import_live_swimrankings_meet.py \
    --lxf-file data/lenex/results.lxf \
    --ages 11 12 13

  python scripts/import_live_swimrankings_meet.py \
    --live-url https://live.swimrankings.net/49785/ \
    --ages 11 12 13
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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


DEFAULT_SAVE_DIR = Path("data/lenex")


@dataclass(frozen=True)
class AgeGroupInfo:
    source_age_group_id: Optional[str]
    age_group_min: Optional[int]
    age_group_max: Optional[int]
    age_group_label: Optional[str]
    age_group_rank: Optional[int]
    age_group_order: Optional[int]


@dataclass(frozen=True)
class EventInfo:
    event_db_id: int
    distance: int
    stroke: str
    gender: str
    pool_length: int


def normalize_gender(value: Optional[str], fallback: str = "U") -> str:
    value = (value or fallback or "U").strip().upper()
    return value if value in {"M", "F", "X", "U"} else fallback


def parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def time_to_seconds(time_str: Optional[str]) -> Optional[Decimal]:
    if not time_str:
        return None
    parts = time_str.split(":")
    try:
        if len(parts) == 3:
            hours = Decimal(parts[0])
            minutes = Decimal(parts[1])
            seconds = Decimal(parts[2])
            return hours * Decimal("3600") + minutes * Decimal("60") + seconds
        if len(parts) == 2:
            minutes = Decimal(parts[0])
            seconds = Decimal(parts[1])
            return minutes * Decimal("60") + seconds
    except InvalidOperation:
        return None
    return None


def get_pool_length(course: Optional[str]) -> int:
    if not course:
        return 50
    return 25 if "SCM" in course.upper() else 50


def canonical_swimmer_id(
    nation: str,
    gender: str,
    birth_year: int,
    first_name: str,
    last_name: str,
) -> str:
    canonical_key = f"{nation}|{gender}|{birth_year}|{first_name}|{last_name}"
    return "CANON::" + hashlib.sha1(canonical_key.encode("utf-8")).hexdigest()[:32]


def sanitize_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip("._-")
    return ascii_text or "meet"


def build_results_url(live_url: str) -> str:
    if live_url.endswith("/results.lxf"):
        return live_url
    return live_url.rstrip("/") + "/results.lxf"


def extract_live_meet_id(live_url: str) -> str:
    path = urlparse(live_url).path.rstrip("/")
    tail = path.split("/")[-1]
    return tail if tail.isdigit() else "live"


def download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def load_root_from_lxf_bytes(data: bytes) -> ET.Element:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            inner_name = next(
                name for name in archive.namelist() if name.lower().endswith((".lef", ".xml"))
            )
            return ET.fromstring(archive.read(inner_name))
    except zipfile.BadZipFile:
        return ET.fromstring(data)


def load_source_bytes(args: argparse.Namespace) -> Tuple[bytes, str, Optional[Path], str]:
    if args.lxf_file:
        source_path = args.lxf_file.resolve()
        data = source_path.read_bytes()
        return data, source_path.name, source_path, source_path.as_posix()

    results_url = build_results_url(args.live_url)
    data = download_bytes(results_url)
    live_meet_id = extract_live_meet_id(args.live_url)
    source_name = f"live_{live_meet_id}_results.lxf"
    return data, source_name, None, results_url


def parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    return date.fromisoformat(text[:10])


def athlete_age_on(agedate_value: str, agedate_type: str, birthdate: str) -> Optional[int]:
    birth = parse_date(birthdate)
    ref = parse_date(agedate_value)
    if birth is None or ref is None:
        return None
    if (agedate_type or "").upper() == "YEAR":
        return ref.year - birth.year
    years = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        years -= 1
    return years


def iter_club_athletes(root: ET.Element) -> Iterable[Tuple[Optional[str], ET.Element]]:
    clubs = root.find(".//CLUBS")
    if clubs is None:
        for athlete in root.findall(".//ATHLETE"):
            yield None, athlete
        return
    for club in clubs.findall("CLUB"):
        club_name = (club.get("name") or "").strip() or None
        athletes = club.find("ATHLETES")
        if athletes is None:
            continue
        for athlete in athletes.findall("ATHLETE"):
            yield club_name, athlete


def extract_meet_metadata(root: ET.Element) -> Dict[str, object]:
    meet = root.find(".//MEET")
    if meet is None:
        raise ValueError("LENEX file has no MEET element")
    session = root.find(".//SESSION")
    facility = meet.find("FACILITY")
    meet_name = (meet.get("name") or "Unknown").strip()
    meet_date = session.get("date") if session is not None else None
    meet_nation = (meet.get("nation") or "").strip() or None
    meet_city = (
        meet.get("city")
        or (facility.get("city") if facility is not None else "")
        or ""
    ).strip() or None
    pool_length = get_pool_length(meet.get("course", "LCM"))
    agedate = meet.find("AGEDATE")
    agedate_value = agedate.get("value") if agedate is not None else meet_date
    agedate_type = agedate.get("type") if agedate is not None else "YEAR"
    return {
        "meet": meet,
        "name": meet_name,
        "date": meet_date,
        "nation": meet_nation,
        "city": meet_city,
        "pool_length": pool_length,
        "agedate_value": agedate_value,
        "agedate_type": agedate_type,
    }


def build_age_group_rankings(root: ET.Element) -> Dict[Tuple[str, str], AgeGroupInfo]:
    ranking_map: Dict[Tuple[str, str], AgeGroupInfo] = {}
    for event in root.findall(".//EVENT"):
        event_id = (event.get("eventid") or "").strip()
        if not event_id:
            continue
        for agegroup in event.findall("./AGEGROUPS/AGEGROUP"):
            source_age_group_id = (agegroup.get("agegroupid") or "").strip() or None
            age_group_min = parse_int(agegroup.get("agemin"))
            age_group_max = parse_int(agegroup.get("agemax"))
            if age_group_min is not None and age_group_max is not None:
                label = f"{age_group_min}-{age_group_max}"
            elif age_group_min is not None:
                label = f">={age_group_min}"
            elif age_group_max is not None:
                label = f"<={age_group_max}"
            else:
                label = None
            for ranking in agegroup.findall("./RANKINGS/RANKING"):
                result_id = (ranking.get("resultid") or "").strip()
                if not result_id:
                    continue
                ranking_map[(event_id, result_id)] = AgeGroupInfo(
                    source_age_group_id=source_age_group_id,
                    age_group_min=age_group_min,
                    age_group_max=age_group_max,
                    age_group_label=label,
                    age_group_rank=parse_int(ranking.get("place")),
                    age_group_order=parse_int(ranking.get("order")),
                )
    return ranking_map


def build_event_age_groups(root: ET.Element) -> Dict[str, AgeGroupInfo]:
    event_defaults: Dict[str, AgeGroupInfo] = {}
    for event in root.findall(".//EVENT"):
        event_id = (event.get("eventid") or "").strip()
        if not event_id:
            continue
        agegroups = event.findall("./AGEGROUPS/AGEGROUP")
        if len(agegroups) != 1:
            continue
        agegroup = agegroups[0]
        source_age_group_id = (agegroup.get("agegroupid") or "").strip() or None
        age_group_min = parse_int(agegroup.get("agemin"))
        age_group_max = parse_int(agegroup.get("agemax"))
        if age_group_min is not None and age_group_max is not None:
            label = f"{age_group_min}-{age_group_max}"
        elif age_group_min is not None:
            label = f">={age_group_min}"
        elif age_group_max is not None:
            label = f"<={age_group_max}"
        else:
            label = None
        event_defaults[event_id] = AgeGroupInfo(
            source_age_group_id=source_age_group_id,
            age_group_min=age_group_min,
            age_group_max=age_group_max,
            age_group_label=label,
            age_group_rank=None,
            age_group_order=None,
        )
    return event_defaults


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def get_db_url(explicit_db_url: Optional[str]) -> str:
    if explicit_db_url:
        return explicit_db_url
    env_url = os.getenv("SWIMRANKINGS_DATABASE_URL")
    if env_url:
        return env_url
    raise RuntimeError(
        "Set SWIMRANKINGS_DATABASE_URL or pass --db-url before running an import."
    )


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


def resolve_swimmer(
    cur,
    athlete_id: Optional[str],
    first_name: str,
    last_name: str,
    birth_year: int,
    nation: str,
    gender: str,
) -> int:
    if athlete_id and nation and nation != "UNK":
        cur.execute(
            "SELECT swimmer_pk FROM swimmer_aliases "
            "WHERE source_country_code=%s AND source_swimmer_id=%s LIMIT 1",
            (nation, athlete_id),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "SELECT first_name, last_name, birth_year, country_code, gender "
                "FROM swimmers WHERE id=%s",
                (row[0],),
            )
            target = cur.fetchone()
            if (
                target
                and target[0] == first_name
                and target[1] == last_name
                and target[2] == birth_year
                and target[3] == nation
                and target[4] == gender
            ):
                return row[0]

    cur.execute(
        "SELECT id FROM swimmers "
        "WHERE first_name=%s AND last_name=%s AND birth_year=%s "
        "AND country_code=%s AND gender=%s "
        "ORDER BY id LIMIT 1",
        (first_name, last_name, birth_year, nation, gender),
    )
    row = cur.fetchone()
    if row:
        swimmer_pk = row[0]
        if athlete_id and nation and nation != "UNK":
            cur.execute(
                "INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) "
                "VALUES (%s,%s,%s) "
                "ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING",
                (swimmer_pk, athlete_id, nation),
            )
        return swimmer_pk

    swimmer_canon = canonical_swimmer_id(nation, gender, birth_year, first_name, last_name)
    cur.execute(
        "INSERT INTO swimmers (swimmer_id, first_name, last_name, birth_year, country_code, gender) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (swimmer_canon, first_name, last_name, birth_year, nation, gender),
    )
    swimmer_pk = cur.fetchone()[0]
    if athlete_id and nation and nation != "UNK":
        cur.execute(
            "INSERT INTO swimmer_aliases (swimmer_pk, source_swimmer_id, source_country_code) "
            "VALUES (%s,%s,%s) "
            "ON CONFLICT (source_country_code, source_swimmer_id) DO NOTHING",
            (swimmer_pk, athlete_id, nation),
        )
    return swimmer_pk


def ensure_meet(cur, meet_id: str, name: str, city: Optional[str], nation: Optional[str], meet_date: Optional[str], pool_length: int) -> int:
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


def ensure_event(
    cur,
    distance: int,
    stroke: str,
    gender: str,
    pool_length: int,
) -> int:
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


def insert_raw_result_rows(cur, rows: Sequence[Tuple[object, ...]]) -> None:
    if not rows:
        return
    cur.executemany(
        """
        INSERT INTO raw_results (
            raw_file_id,
            source_swimmer_id,
            source_country_code,
            first_name,
            last_name,
            birthdate,
            birth_year,
            gender,
            meet_name,
            meet_country_code,
            meet_date,
            source_event_id,
            distance,
            stroke,
            event_gender,
            pool_length,
            swimtime_text,
            time_seconds,
            lane,
            canonical_swimmer_id,
            canonical_meet_id,
            canonical_event_id,
            status,
            points,
            qualification,
            entry_time_seconds,
            reaction_time,
            comment,
            source_result_id,
            rank,
            heat_id,
            source_age_group_id,
            age_group_min,
            age_group_max,
            age_group_label,
            age_group_rank,
            age_group_order
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        ON CONFLICT DO NOTHING
        """,
        rows,
    )


def upsert_results_rows(cur, rows: Sequence[Tuple[object, ...]]) -> None:
    if not rows:
        return
    cur.executemany(
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
            status,
            points,
            qualification,
            entry_time_seconds,
            reaction_time,
            comment,
            age_group_id,
            age_group_min,
            age_group_max,
            age_group_label,
            age_group_rank,
            age_group_order
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        ON CONFLICT (swimmer_id, meet_id, event_id, heat) DO UPDATE SET
            time_seconds=EXCLUDED.time_seconds,
            rank=EXCLUDED.rank,
            lane=EXCLUDED.lane,
            result_date=EXCLUDED.result_date,
            status=EXCLUDED.status,
            points=EXCLUDED.points,
            qualification=EXCLUDED.qualification,
            entry_time_seconds=EXCLUDED.entry_time_seconds,
            reaction_time=EXCLUDED.reaction_time,
            comment=EXCLUDED.comment,
            age_group_id=EXCLUDED.age_group_id,
            age_group_min=EXCLUDED.age_group_min,
            age_group_max=EXCLUDED.age_group_max,
            age_group_label=EXCLUDED.age_group_label,
            age_group_rank=EXCLUDED.age_group_rank,
            age_group_order=EXCLUDED.age_group_order
        """,
        rows,
    )


def collect_filtered_rows(
    root: ET.Element,
    allowed_ages: Sequence[int],
    meet_name: str,
    meet_date: Optional[str],
    meet_nation: str,
    meet_city: Optional[str],
    pool_length: int,
) -> Tuple[
    Dict[Tuple[str, str], AgeGroupInfo],
    Dict[str, AgeGroupInfo],
    List[Tuple[Optional[str], ET.Element, int]],
    Dict[str, Tuple[int, str, str, int]],
]:
    ranking_map = build_age_group_rankings(root)
    event_age_groups = build_event_age_groups(root)
    event_meta: Dict[str, Tuple[int, str, str, int]] = {}
    for event in root.findall(".//EVENT"):
        event_id = (event.get("eventid") or "").strip()
        swimstyle = event.find("SWIMSTYLE")
        if not event_id or swimstyle is None:
            continue
        distance = parse_int(swimstyle.get("distance")) or 0
        stroke = (swimstyle.get("stroke") or "FREE").strip().upper()
        gender = normalize_gender(event.get("gender"), "U")
        event_meta[event_id] = (distance, stroke, gender, pool_length)

    metadata = extract_meet_metadata(root)
    agedate_value = metadata["agedate_value"]
    agedate_type = metadata["agedate_type"]
    filtered_athletes: List[Tuple[Optional[str], ET.Element, int]] = []
    for club_name, athlete in iter_club_athletes(root):
        birthdate = athlete.get("birthdate") or ""
        age = athlete_age_on(str(agedate_value), str(agedate_type), birthdate)
        if age is None or age not in set(allowed_ages):
            continue
        filtered_athletes.append((club_name, athlete, age))
    return ranking_map, event_age_groups, filtered_athletes, event_meta


def import_live_meet(args: argparse.Namespace) -> Dict[str, object]:
    raw_bytes, source_name, source_path, source_ref = load_source_bytes(args)
    root = load_root_from_lxf_bytes(raw_bytes)
    meta = extract_meet_metadata(root)
    meet_name = str(meta["name"])
    meet_date = meta["date"]
    meet_nation = str(meta["nation"] or "UNK")
    meet_city = meta["city"]
    pool_length = int(meta["pool_length"])
    live_meet_id = extract_live_meet_id(args.live_url) if args.live_url else "local"

    ranking_map, event_age_groups, filtered_athletes, event_meta = collect_filtered_rows(
        root=root,
        allowed_ages=args.ages,
        meet_name=meet_name,
        meet_date=meet_date,
        meet_nation=meet_nation,
        meet_city=meet_city,
        pool_length=pool_length,
    )

    filtered_result_count = 0
    for _, athlete, _ in filtered_athletes:
        results_elem = athlete.find("RESULTS")
        if results_elem is not None:
            filtered_result_count += len(results_elem.findall("RESULT"))

    meet_id = (
        f"{meet_name}_{meet_date}".replace(" ", "_")[:100]
        if meet_date
        else meet_name.replace(" ", "_")[:100]
    )

    ages_label = "_".join(str(age) for age in sorted(args.ages))
    filename_stem = sanitize_filename(
        f"{meet_nation}_{meet_date}_{live_meet_id}_{meet_name}_ages_{ages_label}"
    )
    saved_path = source_path
    if source_path is None and not args.no_save:
        args.save_dir.mkdir(parents=True, exist_ok=True)
        saved_path = args.save_dir / f"{filename_stem}.lxf"
        saved_path.write_bytes(raw_bytes)

    if args.dry_run:
        return {
            "saved_path": str(saved_path) if saved_path else None,
            "meet_name": meet_name,
            "meet_date": meet_date,
            "meet_city": meet_city,
            "meet_nation": meet_nation,
            "pool_length": pool_length,
            "live_meet_id": live_meet_id,
            "athlete_count": len(filtered_athletes),
            "result_count": filtered_result_count,
            "file_name": f"{filename_stem}.lxf",
            "source_ref": source_ref,
        }

    try:
        import psycopg2  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "psycopg2 is required for database import. Install psycopg2-binary first."
        ) from exc

    db_url = get_db_url(args.db_url)
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    try:
        ensure_country(cur, meet_nation)
        meet_db_id = ensure_meet(cur, meet_id, meet_name, meet_city, meet_nation, meet_date, pool_length)

        raw_file_name = f"{filename_stem}.lxf"
        file_hash = hashlib.sha1(raw_bytes).hexdigest()
        cur.execute("SELECT id FROM raw_import_files WHERE file_name=%s", (raw_file_name,))
        row = cur.fetchone()
        if row:
            raw_file_id = row[0]
            cur.execute(
                """
                UPDATE raw_import_files
                   SET meet_name=%s,
                       meet_city=%s,
                       meet_country_code=%s,
                       meet_date=%s,
                       file_hash=%s,
                       athlete_count=%s,
                       result_count=%s,
                       status='parsed'
                 WHERE id=%s
                """,
                (
                    meet_name,
                    meet_city,
                    meet_nation,
                    meet_date,
                    file_hash,
                    len(filtered_athletes),
                    filtered_result_count,
                    raw_file_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO raw_import_files (
                    file_name,
                    meet_name,
                    meet_city,
                    meet_country_code,
                    meet_date,
                    file_hash,
                    athlete_count,
                    result_count,
                    status
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'parsed')
                RETURNING id
                """,
                (
                    raw_file_name,
                    meet_name,
                    meet_city,
                    meet_nation,
                    meet_date,
                    file_hash,
                    len(filtered_athletes),
                    filtered_result_count,
                ),
            )
            raw_file_id = cur.fetchone()[0]

        event_cache: Dict[str, EventInfo] = {}
        raw_rows: List[Tuple[object, ...]] = []
        final_rows: List[Tuple[object, ...]] = []
        unique_swimmers = set()

        for club_name, athlete, athlete_age in filtered_athletes:
            del club_name, athlete_age
            first_name = (athlete.get("firstname") or "").strip()
            last_name = (athlete.get("lastname") or "").strip()
            if not first_name or not last_name:
                continue
            athlete_id = (athlete.get("athleteid") or "").strip() or None
            birthdate = (athlete.get("birthdate") or "").strip()
            birth_year = parse_int(birthdate[:4])
            if birth_year is None:
                continue
            gender = normalize_gender(athlete.get("gender"), "U")
            nation = (athlete.get("nation") or meet_nation or "UNK").strip() or "UNK"
            ensure_country(cur, nation)
            swimmer_pk = resolve_swimmer(
                cur=cur,
                athlete_id=athlete_id,
                first_name=first_name,
                last_name=last_name,
                birth_year=birth_year,
                nation=nation,
                gender=gender,
            )
            unique_swimmers.add(swimmer_pk)

            results_elem = athlete.find("RESULTS")
            if results_elem is None:
                continue
            for result in results_elem.findall("RESULT"):
                source_event_id = (result.get("eventid") or "").strip()
                if source_event_id not in event_meta:
                    continue
                if source_event_id not in event_cache:
                    distance, stroke, event_gender, event_pool_length = event_meta[source_event_id]
                    event_db_id = ensure_event(cur, distance, stroke, event_gender, event_pool_length)
                    event_cache[source_event_id] = EventInfo(
                        event_db_id=event_db_id,
                        distance=distance,
                        stroke=stroke,
                        gender=event_gender,
                        pool_length=event_pool_length,
                    )

                event_info = event_cache[source_event_id]
                swimtime_text = (result.get("swimtime") or "").strip() or None
                time_seconds = time_to_seconds(swimtime_text)
                if time_seconds is None:
                    continue

                age_group_info = ranking_map.get(
                    (source_event_id, (result.get("resultid") or "").strip())
                ) or event_age_groups.get(source_event_id) or AgeGroupInfo(
                    None, None, None, None, None, None
                )

                status = (result.get("status") or "").strip() or None
                lane = parse_int(result.get("lane"))
                heat_id = parse_int(result.get("heatid"))
                points = parse_decimal(result.get("points"))
                qualification = (result.get("qualify") or result.get("qualification") or "").strip() or None
                entry_time_seconds = time_to_seconds(result.get("entrytime"))
                reaction_time = (result.get("reactiontime") or "").strip() or None
                comment = (result.get("comment") or result.get("remark") or "").strip() or None
                source_result_id = (result.get("resultid") or "").strip() or None
                rank = parse_int(result.get("rank")) or parse_int(result.get("place"))

                raw_rows.append(
                    (
                        raw_file_id,
                        athlete_id,
                        nation,
                        first_name,
                        last_name,
                        birthdate or None,
                        birth_year,
                        gender,
                        meet_name,
                        meet_nation,
                        meet_date,
                        source_event_id,
                        event_info.distance,
                        event_info.stroke,
                        event_info.gender,
                        event_info.pool_length,
                        swimtime_text,
                        time_seconds,
                        lane,
                        swimmer_pk,
                        meet_db_id,
                        event_info.event_db_id,
                        status,
                        points,
                        qualification,
                        entry_time_seconds,
                        reaction_time,
                        comment,
                        source_result_id,
                        rank,
                        heat_id,
                        age_group_info.source_age_group_id,
                        age_group_info.age_group_min,
                        age_group_info.age_group_max,
                        age_group_info.age_group_label,
                        age_group_info.age_group_rank,
                        age_group_info.age_group_order,
                    )
                )
                final_rows.append(
                    (
                        swimmer_pk,
                        meet_db_id,
                        event_info.event_db_id,
                        time_seconds,
                        rank,
                        heat_id,
                        lane,
                        meet_date,
                        status,
                        points,
                        qualification,
                        entry_time_seconds,
                        reaction_time,
                        comment,
                        age_group_info.source_age_group_id,
                        age_group_info.age_group_min,
                        age_group_info.age_group_max,
                        age_group_info.age_group_label,
                        age_group_info.age_group_rank,
                        age_group_info.age_group_order,
                    )
                )

        deduped_rows: List[Tuple[object, ...]] = []
        seen = set()
        for row in final_rows:
            key = (
                row[0],
                row[1],
                row[2],
                row[5],
                str(row[3]),
                row[8] or "",
                row[10] or "",
                row[14] or "",
            )
            if key in seen:
                continue
            seen.add(key)
            deduped_rows.append(row)

        insert_raw_result_rows(cur, raw_rows)
        upsert_results_rows(cur, deduped_rows)

        cur.execute(
            """
            INSERT INTO processing_log (file_name, status, swimmer_count, result_count, error_msg)
            VALUES (%s, 'success', %s, %s, NULL)
            ON CONFLICT (file_name) DO UPDATE SET
                status='success',
                swimmer_count=EXCLUDED.swimmer_count,
                result_count=EXCLUDED.result_count,
                error_msg=NULL
            """,
            (raw_file_name, len(unique_swimmers), len(deduped_rows)),
        )

        conn.commit()
        return {
            "saved_path": str(saved_path) if saved_path else None,
            "meet_name": meet_name,
            "meet_date": meet_date,
            "meet_city": meet_city,
            "meet_nation": meet_nation,
            "pool_length": pool_length,
            "live_meet_id": live_meet_id,
            "athlete_count": len(filtered_athletes),
            "result_count": filtered_result_count,
            "inserted_result_rows": len(deduped_rows),
            "unique_swimmers": len(unique_swimmers),
            "file_name": raw_file_name,
            "source_ref": source_ref,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a live SwimRankings LENEX file and import an age-filtered subset."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--lxf-file",
        type=Path,
        help="Existing local LENEX `.lxf` file to import.",
    )
    source_group.add_argument(
        "--live-url",
        help="Live SwimRankings meet URL, for example https://live.swimrankings.net/49785/",
    )
    parser.add_argument(
        "--ages",
        nargs="+",
        type=int,
        default=[11, 12, 13],
        help="Ages to import, based on the meet AGEDATE. Default: 11 12 13",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=DEFAULT_SAVE_DIR,
        help="Directory where the downloaded LENEX file should be saved.",
    )
    parser.add_argument(
        "--db-url",
        help="PostgreSQL connection string. If omitted, SWIMRANKINGS_DATABASE_URL is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and parse the LENEX file, but do not write to the database.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save the downloaded LENEX file to disk. Ignored when --lxf-file is used.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        summary = import_live_meet(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("IMPORT_SUMMARY")
    for key in sorted(summary):
        print(f"{key}={summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
