#!/usr/bin/env python3
"""Desktop-built, versioned meet snapshots. No SwimRankings HTTP access on receiver."""

from __future__ import annotations

import argparse
import gzip
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

FORMAT = 1
MAX_BYTES = 256 * 1024 * 1024
MEET = (
    "meet_id",
    "name",
    "city",
    "country_code",
    "start_date",
    "end_date",
    "pool_length",
)
SWIMMER = (
    "swimmer_id",
    "first_name",
    "last_name",
    "birth_year",
    "gender",
    "country_code",
)
EVENT = ("distance", "stroke", "gender", "pool_length")
RESULT = (
    "time_seconds",
    "rank",
    "heat",
    "lane",
    "result_date",
    "status",
    "points",
    "qualification",
    "entry_time_seconds",
    "reaction_time",
    "comment",
    "age_group_id",
    "age_group_min",
    "age_group_max",
    "age_group_label",
    "age_group_rank",
    "age_group_order",
    "event_round",
    "is_relay",
    "relay_count",
    "points_fina",
    "points_rudolph",
)
SPLIT = ("distance", "time_seconds", "split_order")


def canonical(value):
    def encode(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        raise TypeError(type(v).__name__)

    return json.dumps(
        value, default=encode, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def selected(row, columns):
    return {k: row[k] for k in columns}


def rows(cur, query, args=()):
    cur.execute(query, args)
    return [dict(r) for r in cur.fetchall()]


def configuration(path):
    # A local JSON object of psycopg connection parameters; never printed/uploaded.
    cfg = json.loads(Path(path).read_text())
    if (
        not isinstance(cfg, dict)
        or "password" in cfg
        and not isinstance(cfg["password"], str)
    ):
        raise ValueError("Invalid database configuration")
    return cfg


def connect(path, host, database, readonly=False):
    conn = psycopg2.connect(**configuration(path), connect_timeout=10)
    if conn.info.host != host or conn.info.dbname != database:
        conn.close()
        raise ValueError("Connection does not match explicit expected host/database")
    conn.set_session(
        readonly=readonly,
        isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED",
    )
    return conn


def snapshot(conn, meet_id):
    """Export a complete canonical meet, not a partial date-filtered result set."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        meet = rows(cur, "SELECT * FROM meets WHERE id=%s", (meet_id,))
        if len(meet) != 1:
            raise ValueError("Unknown source meet")
        matching = rows(
            cur, "SELECT id FROM meets WHERE meet_id=%s", (meet[0]["meet_id"],)
        )
        if len(matching) != 1:
            raise ValueError("Ambiguous source meet identity")
        races = rows(
            cur, "SELECT * FROM results WHERE meet_id=%s ORDER BY id", (meet_id,)
        )
        swimmer_ids = sorted({r["swimmer_id"] for r in races})
        event_ids = sorted({r["event_id"] for r in races})
        athletes = rows(
            cur,
            "SELECT s.*, c.name AS club FROM swimmers s LEFT JOIN clubs c ON c.id=s.club_id WHERE s.id=ANY(%s) ORDER BY s.swimmer_id",
            (swimmer_ids,),
        )
        events = rows(
            cur,
            "SELECT * FROM events WHERE id=ANY(%s) ORDER BY distance,stroke,gender,pool_length",
            (event_ids,),
        )
        by_swimmer = {r["id"]: r["swimmer_id"] for r in athletes}
        by_event = {r["id"]: digest(selected(r, EVENT)) for r in events}
        aliases = rows(
            cur,
            "SELECT * FROM swimmer_aliases WHERE swimmer_pk=ANY(%s) ORDER BY source_country_code,source_swimmer_id",
            (swimmer_ids,),
        )
        country_codes = (
            {r["country_code"] for r in athletes}
            | {meet[0]["country_code"]}
            | {a["source_country_code"] for a in aliases}
        )
        countries = rows(
            cur,
            "SELECT code,name,excluded FROM countries WHERE code=ANY(%s) ORDER BY code",
            (sorted(c for c in country_codes if c is not None),),
        )
        splits = rows(
            cur,
            "SELECT s.* FROM splits s JOIN results r ON r.id=s.result_id WHERE r.meet_id=%s ORDER BY s.result_id,s.split_order,s.distance",
            (meet_id,),
        )
        return json.loads(
            canonical(
                {
                    "meet": selected(meet[0], MEET),
                    "countries": countries,
                    "swimmers": [
                        dict(selected(r, SWIMMER), club=r["club"]) for r in athletes
                    ],
                    "aliases": [
                        {
                            "swimmer_key": by_swimmer[a["swimmer_pk"]],
                            "source_country_code": a["source_country_code"],
                            "source_swimmer_id": a["source_swimmer_id"],
                        }
                        for a in aliases
                    ],
                    "events": [
                        dict(selected(e, EVENT), key=by_event[e["id"]]) for e in events
                    ],
                    "results": [
                        dict(
                            selected(r, RESULT),
                            **({"club_name": r["club_name"], "club_source": r["club_source"]} if r.get("club_name") and r.get("club_source") else {}),
                            source_id=r["id"],
                            swimmer_key=by_swimmer[r["swimmer_id"]],
                            event_key=by_event[r["event_id"]],
                        )
                        for r in races
                    ],
                    "splits": [
                        dict(selected(s, SPLIT), source_result_id=s["result_id"])
                        for s in splits
                    ],
                }
            )
        )


def validate(packet):
    if not isinstance(packet, dict) or packet.get("format") != FORMAT:
        raise ValueError("Unsupported package format")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", packet.get("publisher", "")):
        raise ValueError("Invalid publisher")
    if type(packet.get("revision")) is not int or packet["revision"] < 1:
        raise ValueError("Invalid revision")
    previous = packet.get("previous")
    if (packet["revision"] == 1 and previous is not None) or (
        packet["revision"] > 1 and not re.fullmatch(r"[a-f0-9]{64}", previous or "")
    ):
        raise ValueError("Invalid revision chain")
    payload = packet.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "meet",
        "countries",
        "swimmers",
        "aliases",
        "events",
        "results",
        "splits",
    }:
        raise ValueError("Incomplete snapshot")
    if digest(payload) != packet.get("sha256"):
        raise ValueError("Package checksum mismatch")
    if set(payload["meet"]) != set(MEET) or not payload["meet"]["meet_id"]:
        raise ValueError("Invalid meet")

    def unique(items, key, fields):
        if not isinstance(items, list) or any(set(r) != set(fields) for r in items):
            raise ValueError("Unexpected snapshot fields")
        values = [key(r) for r in items]
        if len(set(values)) != len(values):
            raise ValueError("Duplicate snapshot identity")
        return set(values)

    countries = unique(
        payload["countries"], lambda r: r["code"], ("code", "name", "excluded")
    )
    swimmers = unique(
        payload["swimmers"], lambda r: r["swimmer_id"], (*SWIMMER, "club")
    )
    events = unique(payload["events"], lambda r: r["key"], (*EVENT, "key"))
    for race in payload["results"]:
        proof = {k: race[k] for k in ("club_name", "club_source") if k in race}
        if proof and (set(proof) != {"club_name", "club_source"} or not isinstance(proof["club_name"], str) or not proof["club_name"].strip() or len(proof["club_name"]) > 300 or not re.fullmatch(r"[a-f0-9]{64}", proof["club_source"] or "")):
            raise ValueError("Invalid per-performance club evidence")
    results = unique(
        [{k:v for k,v in r.items() if k not in ("club_name", "club_source")} for r in payload["results"]],
        lambda r: r["source_id"],
        (*RESULT, "source_id", "swimmer_key", "event_key"),
    )
    unique(
        payload["aliases"],
        lambda r: (r["source_country_code"], r["source_swimmer_id"]),
        ("swimmer_key", "source_country_code", "source_swimmer_id"),
    )
    unique(
        payload["splits"],
        lambda r: (r["source_result_id"], r["split_order"]),
        (*SPLIT, "source_result_id"),
    )
    if any(e["key"] != digest(selected(e, EVENT)) for e in payload["events"]):
        raise ValueError("Event identity mismatch")
    if any(
        type(r["source_id"]) is not int
        or r["source_id"] <= 0
        or r["swimmer_key"] not in swimmers
        or r["event_key"] not in events
        for r in payload["results"]
    ):
        raise ValueError("Missing race dependencies")
    if any(s["source_result_id"] not in results for s in payload["splits"]):
        raise ValueError("Missing split dependencies")
    if any(
        a["swimmer_key"] not in swimmers or a["source_country_code"] not in countries
        for a in payload["aliases"]
    ):
        raise ValueError("Missing alias dependencies")
    if (
        any(
            s["country_code"] is not None and s["country_code"] not in countries
            for s in payload["swimmers"]
        )
        or payload["meet"]["country_code"] is not None
        and payload["meet"]["country_code"] not in countries
    ):
        raise ValueError("Missing country dependencies")
    # A stable signature permits adoption without replacing destination result IDs.
    unique(
        [{k:v for k,v in r.items() if k not in ("club_name", "club_source")} for r in payload["results"]], race_key, (*RESULT, "source_id", "swimmer_key", "event_key")
    )
    return packet


def race_key(r):
    return tuple(
        r[k]
        for k in (
            "swimmer_key",
            "event_key",
            "heat",
            "result_date",
            "event_round",
            "is_relay",
            "relay_count",
        )
    )


def read_package(path):
    with gzip.open(path, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Package exceeds uncompressed limit")
    return validate(json.loads(data))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def export_meets(conn, ids, publisher, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".publisher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _export_meets(conn, ids, publisher, directory)


def _export_meets(conn, ids, publisher, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Immutable previous packages are the publisher ledger; no advancing checkpoint
    # until the complete new package has been atomically saved.
    previous = {}
    for path in sorted(directory.glob("*.json.gz")):
        packet = read_package(path)
        if packet["publisher"] != publisher:
            raise ValueError("Output directory belongs to another publisher")
        key = packet["payload"]["meet"]["meet_id"]
        old = previous.get(key)
        if packet["revision"] != (old["revision"] + 1 if old else 1) or packet[
            "previous"
        ] != (old["sha256"] if old else None):
            raise ValueError("Publisher history has missing or conflicting revisions")
        previous[key] = packet
    published = []
    for meet_id in sorted(set(ids)):
        payload = snapshot(conn, meet_id)
        key = payload["meet"]["meet_id"]
        old = previous.get(key)
        checksum = digest(payload)
        if old and old["sha256"] == checksum:
            continue
        packet = {
            "format": FORMAT,
            "publisher": publisher,
            "revision": old["revision"] + 1 if old else 1,
            "previous": old["sha256"] if old else None,
            "sha256": checksum,
            "payload": payload,
        }
        validate(packet)
        filename = f'{digest(key)[:16]}-r{packet["revision"]:06}-{checksum}.json.gz'
        path = directory / filename
        encoded = canonical(packet)
        if len(encoded) > MAX_BYTES:
            raise ValueError("Package exceeds uncompressed limit")
        atomic_write(path, gzip.compress(encoded, mtime=0))
        published.append(
            {
                "file": filename,
                "meet": key,
                "revision": packet["revision"],
                "bytes": path.stat().st_size,
                "results": len(payload["results"]),
            }
        )
    return published


LEDGER = """
CREATE SCHEMA IF NOT EXISTS swimrankings_delivery;
CREATE TABLE IF NOT EXISTS swimrankings_delivery.meets (
 publisher text NOT NULL, meet_key text NOT NULL, revision integer NOT NULL,
 sha256 text NOT NULL, meet_id integer UNIQUE NOT NULL REFERENCES public.meets(id),
 result_digest text NOT NULL, needs_summary_refresh boolean NOT NULL DEFAULT true,
 applied_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(publisher,meet_key));
CREATE TABLE IF NOT EXISTS swimrankings_delivery.results (
 publisher text NOT NULL, source_id bigint NOT NULL, meet_key text NOT NULL,
 target_id integer UNIQUE NOT NULL REFERENCES public.results(id) ON DELETE CASCADE,
 PRIMARY KEY(publisher,source_id));
CREATE TABLE IF NOT EXISTS swimrankings_delivery.audit (
 publisher text NOT NULL, meet_key text NOT NULL, revision integer NOT NULL,
 sha256 text NOT NULL, before_digest text, applied_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(publisher,meet_key,revision));
ALTER TABLE swimrankings_delivery.meets ADD COLUMN IF NOT EXISTS affected_from date;
ALTER TABLE public.results ADD COLUMN IF NOT EXISTS club_name text;
ALTER TABLE public.results ADD COLUMN IF NOT EXISTS club_source text;
"""


def upsert(cur, table, row, keys, returning="id"):
    cols = list(row)
    changes = [c for c in cols if c not in keys]
    query = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {} RETURNING {}"
    ).format(
        sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, cols)),
        sql.SQL(",").join(sql.Placeholder() for _ in cols),
        sql.SQL(",").join(map(sql.Identifier, keys)),
        sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
            for c in (changes or keys)
        ),
        sql.Identifier(returning),
    )
    cur.execute(query, [row[c] for c in cols])
    return cur.fetchone()[returning]


def meet_digest(conn, meet_id):
    # Local destination edits to owned meet metadata/results/splits must not be overwritten.
    p = snapshot(conn, meet_id)
    return digest({k: p[k] for k in ("meet", "results", "splits")})


def apply_package(conn, packet, commit=False, adopt_existing=False):
    validate(packet)
    p = packet["payload"]
    key = p["meet"]["meet_id"]
    publisher = packet["publisher"]
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='10s'")
            cur.execute("SET LOCAL statement_timeout='10min'")
            cur.execute("SET LOCAL search_path=public")
            cur.execute("SELECT pg_advisory_xact_lock(784211990)")
            # Legacy meets.meet_id has no unique constraint. Serialize against
            # other importers as well as this receiver during reconciliation.
            cur.execute("LOCK TABLE meets, results, splits IN SHARE ROW EXCLUSIVE MODE")
            cur.execute(LEDGER)
            cur.execute(
                "SELECT * FROM swimrankings_delivery.meets WHERE publisher=%s AND meet_key=%s FOR UPDATE",
                (publisher, key),
            )
            old = cur.fetchone()
            if old:
                actual = meet_digest(conn, old["meet_id"])
                if actual != old["result_digest"]:
                    raise ValueError(
                        "Destination meet changed outside delivery; reconcile before applying"
                    )
                if (
                    packet["revision"] == old["revision"]
                    and packet["sha256"] == old["sha256"]
                ):
                    conn.rollback()
                    return {
                        "status": "already_applied",
                        "meet": key,
                        "revision": packet["revision"],
                    }
                if (
                    packet["revision"] != old["revision"] + 1
                    or packet["previous"] != old["sha256"]
                ):
                    raise ValueError("Missing, stale or conflicting package revision")
            elif packet["revision"] != 1:
                raise ValueError("Initial package revision is missing")
            cur.execute("SELECT id FROM meets WHERE meet_id=%s", (key,))
            matching = cur.fetchall()
            if len(matching) > 1:
                raise ValueError("Ambiguous destination meet identity")
            existing = matching[0] if matching else None
            if existing and not old:
                cur.execute(
                    "SELECT publisher FROM swimrankings_delivery.meets WHERE meet_id=%s",
                    (existing["id"],),
                )
                if cur.fetchone():
                    raise ValueError("Meet belongs to another publisher")
                if not adopt_existing:
                    raise ValueError(
                        "Existing meet requires explicit adoption after preview/backup"
                    )
            before = meet_digest(conn, existing["id"]) if existing else None
            for country in p["countries"]:
                upsert(cur, "countries", country, ("code",), "code")
            club_ids = {}
            for athlete in p["swimmers"]:
                if athlete["club"] and athlete["club"] not in club_ids:
                    club_ids[athlete["club"]] = upsert(
                        cur, "clubs", {"name": athlete["club"]}, ("name",)
                    )
            swimmer_ids = {}
            for athlete in p["swimmers"]:
                r = dict(
                    selected(athlete, SWIMMER), club_id=club_ids.get(athlete["club"])
                )
                swimmer_ids[athlete["swimmer_id"]] = upsert(
                    cur, "swimmers", r, ("swimmer_id",)
                )
            for alias in p["aliases"]:
                cur.execute(
                    "SELECT swimmer_pk FROM swimmer_aliases WHERE source_country_code=%s AND source_swimmer_id=%s",
                    (alias["source_country_code"], alias["source_swimmer_id"]),
                )
                found = cur.fetchone()
                target = swimmer_ids[alias["swimmer_key"]]
                if found and found["swimmer_pk"] != target:
                    raise ValueError("Alias identity conflict; no automatic merge")
                if not found:
                    cur.execute(
                        "INSERT INTO swimmer_aliases(swimmer_pk,source_country_code,source_swimmer_id) VALUES(%s,%s,%s)",
                        (
                            target,
                            alias["source_country_code"],
                            alias["source_swimmer_id"],
                        ),
                    )
            event_ids = {
                e["key"]: upsert(cur, "events", selected(e, EVENT), EVENT)
                for e in p["events"]
            }
            if existing:
                target_meet = upsert(
                    cur, "meets", dict(p["meet"], id=existing["id"]), ("id",)
                )
            else:
                cur.execute(
                    sql.SQL("INSERT INTO meets ({}) VALUES ({}) RETURNING id").format(
                        sql.SQL(",").join(map(sql.Identifier, MEET)),
                        sql.SQL(",").join(sql.Placeholder() for _ in MEET),
                    ),
                    [p["meet"][c] for c in MEET],
                )
                target_meet = cur.fetchone()["id"]
            current = rows(
                cur,
                "SELECT * FROM results WHERE meet_id=%s ORDER BY id",
                (target_meet,),
            )
            rev_swimmer = {v: k for k, v in swimmer_ids.items()}
            dates = [r["result_date"] for r in [*current, *p["results"]]]
            if not dates:
                dates = [p["meet"]["start_date"]]
            if old and old["needs_summary_refresh"]:
                dates.append(old["affected_from"])
            affected_from = (
                min(str(d)[:10] for d in dates)
                if all(d is not None for d in dates)
                else None
            )
            rev_event = {v: k for k, v in event_ids.items()}
            natural = {}
            for row in current:
                normalized = json.loads(
                    canonical(
                        dict(
                            row,
                            swimmer_key=rev_swimmer.get(row["swimmer_id"]),
                            event_key=rev_event.get(row["event_id"]),
                        )
                    )
                )
                signature = race_key(normalized)
                if signature in natural:
                    raise ValueError("Ambiguous existing result identity")
                natural[signature] = row["id"]
            cur.execute(
                "SELECT source_id,target_id FROM swimrankings_delivery.results WHERE publisher=%s AND meet_key=%s",
                (publisher, key),
            )
            mapping = {r["source_id"]: r["target_id"] for r in cur.fetchall()}
            incoming_ids = [r["source_id"] for r in p["results"]]
            cur.execute(
                "SELECT 1 FROM swimrankings_delivery.results WHERE publisher=%s AND source_id=ANY(%s) AND meet_key<>%s LIMIT 1",
                (publisher, incoming_ids, key),
            )
            if cur.fetchone():
                raise ValueError(
                    "Source result identity is already assigned to another meet"
                )
            cur.execute(
                "DELETE FROM swimrankings_delivery.results WHERE publisher=%s AND meet_key=%s AND NOT(source_id=ANY(%s))",
                (publisher, key, incoming_ids),
            )
            targets = {}
            used_targets = set()
            for race in p["results"]:
                target = mapping.get(race["source_id"]) or natural.get(race_key(race))
                values = dict(
                    selected(race, RESULT),
                    club_name=race.get("club_name"), club_source=race.get("club_source"),
                    swimmer_id=swimmer_ids[race["swimmer_key"]],
                    event_id=event_ids[race["event_key"]],
                    meet_id=target_meet,
                )
                if target:
                    values["id"] = target
                    target = upsert(cur, "results", values, ("id",))
                else:
                    cols = list(values)
                    cur.execute(
                        sql.SQL(
                            "INSERT INTO results ({}) VALUES ({}) RETURNING id"
                        ).format(
                            sql.SQL(",").join(map(sql.Identifier, cols)),
                            sql.SQL(",").join(sql.Placeholder() for _ in cols),
                        ),
                        [values[c] for c in cols],
                    )
                    target = cur.fetchone()["id"]
                if target in used_targets:
                    raise ValueError(
                        "Two source results resolve to one destination result"
                    )
                targets[race["source_id"]] = target
                used_targets.add(target)
                cur.execute(
                    "INSERT INTO swimrankings_delivery.results(publisher,source_id,meet_key,target_id) VALUES(%s,%s,%s,%s) ON CONFLICT(publisher,source_id) DO UPDATE SET target_id=excluded.target_id,meet_key=excluded.meet_key",
                    (publisher, race["source_id"], key, target),
                )
            target_ids = list(targets.values())
            # Only this complete meet is reconciled; unrelated meets are untouched.
            cur.execute(
                "DELETE FROM results WHERE meet_id=%s AND NOT(id=ANY(%s))",
                (target_meet, target_ids),
            )
            deleted = cur.rowcount
            cur.execute("DELETE FROM splits WHERE result_id=ANY(%s)", (target_ids,))
            for split in p["splits"]:
                cur.execute(
                    "INSERT INTO splits(result_id,distance,time_seconds,split_order) VALUES(%s,%s,%s,%s)",
                    (
                        targets[split["source_result_id"]],
                        split["distance"],
                        split["time_seconds"],
                        split["split_order"],
                    ),
                )
            actual = meet_digest(conn, target_meet)
            cur.execute(
                "INSERT INTO swimrankings_delivery.meets(publisher,meet_key,revision,sha256,meet_id,result_digest) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(publisher,meet_key) DO UPDATE SET revision=excluded.revision,sha256=excluded.sha256,result_digest=excluded.result_digest,needs_summary_refresh=true,applied_at=now()",
                (
                    publisher,
                    key,
                    packet["revision"],
                    packet["sha256"],
                    target_meet,
                    actual,
                ),
            )
            cur.execute(
                "INSERT INTO swimrankings_delivery.audit(publisher,meet_key,revision,sha256,before_digest) VALUES(%s,%s,%s,%s,%s)",
                (publisher, key, packet["revision"], packet["sha256"], before),
            )
            report = {
                "status": "applied" if commit else "validated_rolled_back",
                "meet": key,
                "revision": packet["revision"],
                "results": len(targets),
                "splits": len(p["splits"]),
                "deleted": deleted,
                "summary_refresh_required": True,
            }
            cur.execute(
                "UPDATE swimrankings_delivery.meets SET affected_from=%s WHERE publisher=%s AND meet_key=%s",
                (affected_from, publisher, key),
            )
        if commit:
            conn.commit()
        else:
            conn.rollback()
        return report
    except BaseException:
        conn.rollback()
        raise


def remote_status(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT to_regclass('swimrankings_delivery.meets') AS relation")
        if not cur.fetchone()["relation"]:
            return []
        return rows(
            cur,
            "SELECT publisher,meet_key,revision,sha256,needs_summary_refresh FROM swimrankings_delivery.meets ORDER BY publisher,meet_key",
        )


def push(args):
    # No credential values are included in commands, uploads or package payloads.
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", args.ssh_host):
        raise ValueError("Invalid SSH host/alias")
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.remote_dir)
        or ".." in Path(args.remote_dir).parts
    ):
        raise ValueError("Use an absolute remote directory without spaces/traversal")

    def ssh(argv):
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.ssh_host, shlex.join(argv)],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout

    def scp(path, destination):
        subprocess.run(
            ["scp", "-q", str(path), f"{args.ssh_host}:{destination}"], check=True
        )

    packages = [
        (path, read_package(path)) for path in Path(args.directory).glob("*.json.gz")
    ]
    packages.sort(
        key=lambda x: (
            x[1]["publisher"],
            x[1]["payload"]["meet"]["meet_id"],
            x[1]["revision"],
        )
    )
    if not args.commit:
        return {
            "status": "plan_only",
            "packages": len(packages),
            "bytes": sum(p.stat().st_size for p, _ in packages),
            "destination": args.ssh_host,
        }
    python = getattr(args, "remote_python", "python3")
    ssh([python, "-c", "import psycopg2"])
    ssh(["mkdir", "-p", args.remote_dir])
    runner = Path(__file__).resolve()
    remote_runner = f"{args.remote_dir}/meet_delivery-{hashlib.sha256(runner.read_bytes()).hexdigest()}.py"
    if getattr(args, "publish_config", None):
        files = [
            runner,
            *[
                runner.with_name(name)
                for name in (
                    "publish_delivery.py",
                    "delivery_summaries.py",
                    "delivery_summary_schema.sql",
                )
            ],
        ]
        bundle = digest(
            [hashlib.sha256(path.read_bytes()).hexdigest() for path in files]
        )
        runtime = f"{args.remote_dir}/runtime-{bundle}"
        ssh(["mkdir", "-p", runtime])
        for path in files:
            scp(path, f"{runtime}/{path.name}.part")
            ssh(["mv", f"{runtime}/{path.name}.part", f"{runtime}/{path.name}"])
        remote_runner = f"{runtime}/meet_delivery.py"
    else:
        scp(runner, remote_runner)
    common = [
        "--config",
        args.remote_config,
        "--expect-host",
        args.expect_host,
        "--expect-database",
        args.expect_database,
    ]
    state = json.loads(ssh([python, remote_runner, "status", *common]))
    known = {(r["publisher"], r["meet_key"]): r for r in state}
    sent = []
    for path, packet in packages:
        key = (packet["publisher"], packet["payload"]["meet"]["meet_id"])
        old = known.get(key)
        if old and packet["revision"] <= old["revision"]:
            if (
                packet["revision"] == old["revision"]
                and packet["sha256"] != old["sha256"]
            ):
                raise ValueError("Destination revision conflict")
            continue
        remote = f"{args.remote_dir}/{path.name}"
        scp(path, remote + ".part")
        ssh(["mv", remote + ".part", remote])
        reply = json.loads(
            ssh(
                [
                    python,
                    remote_runner,
                    "apply",
                    *common,
                    "--package",
                    remote,
                    "--commit",
                ]
            )
        )
        sent.append(reply)
        known[key] = {"revision": packet["revision"], "sha256": packet["sha256"]}
    publication = None
    if getattr(args, "publish_config", None):
        publication = json.loads(
            ssh(
                [
                    python,
                    remote_runner,
                    "publish",
                    *common,
                    "--consumers-config",
                    args.publish_config,
                    "--commit",
                ]
            )
        )
    return {
        "status": "complete",
        "uploaded": len(sent),
        "meets": sent,
        "publication": publication,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ["export", "apply", "status", "publish"]:
        cmd = sub.add_parser(action)
        cmd.add_argument(
            "--config", required=True, help="Local JSON connection file; never uploaded"
        )
        cmd.add_argument("--expect-host", required=True)
        cmd.add_argument("--expect-database", required=True)
        if action == "export":
            cmd.add_argument("--meet-id", type=int, action="append", required=True)
            cmd.add_argument("--publisher", required=True)
            cmd.add_argument("--directory", required=True)
        elif action == "publish":
            cmd.add_argument(
                "--consumers-config",
                required=True,
                help="Private destination JSON file with all three website URLs/tokens",
            )
            cmd.add_argument(
                "--commit",
                action="store_true",
                help="Otherwise show pending work without summaries or HTTP calls",
            )
        elif action == "apply":
            cmd.add_argument("--package", required=True)
            cmd.add_argument(
                "--commit",
                action="store_true",
                help="Otherwise validate in a rolled-back transaction",
            )
            cmd.add_argument(
                "--adopt-existing",
                action="store_true",
                help="Explicitly reconcile an existing untracked meet after preview/backup",
            )
    cmd = sub.add_parser("push")
    for field in [
        "directory",
        "ssh-host",
        "remote-dir",
        "remote-config",
        "expect-host",
        "expect-database",
    ]:
        cmd.add_argument("--" + field, required=True)
    cmd.add_argument(
        "--commit", action="store_true", help="Otherwise print a local transfer plan"
    )
    cmd.add_argument(
        "--publish-config",
        help="Private consumers JSON path on the destination; enables summary/website publication after upload",
    )
    cmd.add_argument(
        "--remote-python",
        default="python3",
        help="Destination Python executable, e.g. a virtual environment path",
    )
    args = parser.parse_args()
    try:
        if args.action == "push":
            report = push(args)
        else:
            conn = connect(
                args.config,
                args.expect_host,
                args.expect_database,
                readonly=args.action not in ("apply", "publish"),
            )
            try:
                if args.action == "export":
                    report = export_meets(
                        conn, args.meet_id, args.publisher, args.directory
                    )
                elif args.action == "apply":
                    report = apply_package(
                        conn,
                        read_package(args.package),
                        args.commit,
                        args.adopt_existing,
                    )
                elif args.action == "publish":
                    from publish_delivery import consumers, publish

                    report = publish(
                        conn, consumers(args.consumers_config), args.commit
                    )
                else:
                    report = remote_status(conn)
            finally:
                conn.close()
        print(json.dumps(report, ensure_ascii=False))
        if isinstance(report, dict) and report.get("status") == "failed":
            return 1
    except Exception as exc:
        # Database/transport exception text can contain credentials or row values.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "type": type(exc).__name__,
                    "error": (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "Operation failed; uncommitted meet changes were rolled back. Earlier batch items may be applied; check receipts."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
