"""Delivery contract tests; integration writes only to an explicitly named test DB."""

import copy
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import meet_delivery as d


def packet():
    event = dict(distance=100, stroke="FREE", gender="F", pool_length=50)
    event["key"] = d.digest(event)
    races = []
    for i in (1, 2):
        r = dict.fromkeys(d.RESULT)
        r.update(
            source_id=100 + i,
            swimmer_key=f"fixture-{i}",
            event_key=event["key"],
            time_seconds="61.23",
            result_date="2026-09-01",
            heat=1,
            event_round="FIN",
            is_relay=False,
            relay_count=None,
            points_fina=600,
        )
        races.append(r)
    p = dict(
        meet=dict(
            meet_id="fixture-meet",
            name="Fixture meet",
            city="Test",
            country_code="SUI",
            start_date="2026-08-31",
            end_date="2026-09-01",
            pool_length=50,
        ),
        countries=[dict(code="SUI", name="Switzerland", excluded=False)],
        swimmers=[
            dict(
                swimmer_id=f"fixture-{i}",
                first_name="Test",
                last_name=str(i),
                birth_year=2000,
                gender="F",
                country_code="SUI",
                club="Test club",
            )
            for i in (1, 2)
        ],
        events=[event],
        aliases=[
            dict(
                swimmer_key="fixture-1",
                source_country_code="SUI",
                source_swimmer_id="fixture-alias",
            )
        ],
        results=races,
        splits=[
            dict(
                source_result_id=100 + i,
                distance=50,
                time_seconds="30.00",
                split_order=1,
            )
            for i in (1, 2)
        ],
    )
    return dict(
        format=1,
        publisher="test-desktop",
        revision=1,
        previous=None,
        sha256=d.digest(p),
        payload=p,
    )


def revised(old):
    p = copy.deepcopy(old)
    p.update(revision=old["revision"] + 1, previous=old["sha256"])
    return p


def checksum(p):
    p["sha256"] = d.digest(p["payload"])
    return p


class Validation(unittest.TestCase):
    def test_checksum_and_format(self):
        p = packet()
        d.validate(p)
        p["payload"]["results"][0]["points_fina"] = 601
        with self.assertRaisesRegex(ValueError, "checksum"):
            d.validate(p)
        p["format"] = 2
        with self.assertRaisesRegex(ValueError, "format"):
            d.validate(p)

    def test_dependency_and_duplicate_detection(self):
        p = packet()
        p["payload"]["splits"][0]["source_result_id"] = 9999
        with self.assertRaisesRegex(ValueError, "split dependencies"):
            d.validate(checksum(p))
        p = packet()
        p["payload"]["results"].append(copy.deepcopy(p["payload"]["results"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            d.validate(checksum(p))

    def test_bounded_decompression(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.json.gz"
            path.write_bytes(gzip.compress(b"x" * 100))
            with patch.object(d, "MAX_BYTES", 50):
                with self.assertRaisesRegex(ValueError, "limit"):
                    d.read_package(path)

    def test_push_plan_has_no_network_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "one.json.gz"
            path.write_bytes(gzip.compress(d.canonical(packet())))
            args = SimpleNamespace(
                directory=folder,
                ssh_host="aws-swimming",
                remote_dir="/srv/delivery",
                commit=False,
            )
            with patch.object(d.subprocess, "run") as run:
                self.assertEqual(d.push(args)["packages"], 1)
                run.assert_not_called()

    def test_export_is_idempotent_and_chains_revisions(self):
        p = packet()["payload"]
        with tempfile.TemporaryDirectory() as folder, patch.object(
            d, "snapshot", return_value=p
        ):
            self.assertEqual(len(d.export_meets(None, [1], "test-desktop", folder)), 1)
            self.assertEqual(d.export_meets(None, [1], "test-desktop", folder), [])
            p["results"][0]["points_fina"] = 650
            result = d.export_meets(None, [1], "test-desktop", folder)
            self.assertEqual(result[0]["revision"], 2)
            first = next(Path(folder).glob("*r000001*"))
            first.unlink()
            with self.assertRaisesRegex(ValueError, "history"):
                d.export_meets(None, [1], "test-desktop", folder)

    def test_push_resumes_from_destination_receipts(self):
        p = packet()
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "one.json.gz").write_bytes(gzip.compress(d.canonical(p)))
            args = SimpleNamespace(
                directory=folder,
                ssh_host="aws-swimming",
                remote_dir="/srv/delivery",
                remote_config="/srv/private/db.json",
                expect_host="localhost",
                expect_database="swimrankings",
                commit=True,
            )
            known = [
                dict(
                    publisher=p["publisher"],
                    meet_key=p["payload"]["meet"]["meet_id"],
                    revision=1,
                    sha256=p["sha256"],
                )
            ]

            def run(argv, **kwargs):
                return SimpleNamespace(
                    stdout=(
                        json.dumps(known)
                        if argv[0] == "ssh" and " status " in argv[-1]
                        else ""
                    )
                )

            with patch.object(d.subprocess, "run", side_effect=run) as transport:
                self.assertEqual(d.push(args)["uploaded"], 0)
                self.assertEqual(
                    sum(c.args[0][0] == "scp" for c in transport.call_args_list), 1
                )
                self.assertFalse(
                    any(" apply " in c.args[0][-1] for c in transport.call_args_list)
                )

    def test_push_transport_failure_stops_before_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "one.json.gz").write_bytes(
                gzip.compress(d.canonical(packet()))
            )
            args = SimpleNamespace(
                directory=folder,
                ssh_host="aws-swimming",
                remote_dir="/srv/delivery",
                remote_config="/srv/private/db.json",
                expect_host="localhost",
                expect_database="swimrankings",
                commit=True,
            )

            def run(argv, **kwargs):
                if argv[0] == "scp" and str(argv[2]).endswith(".json.gz"):
                    raise d.subprocess.CalledProcessError(1, "scp")
                return SimpleNamespace(
                    stdout="[]" if argv[0] == "ssh" and " status " in argv[-1] else ""
                )

            with patch.object(d.subprocess, "run", side_effect=run) as transport:
                with self.assertRaises(d.subprocess.CalledProcessError):
                    d.push(args)
                self.assertFalse(
                    any(" apply " in c.args[0][-1] for c in transport.call_args_list)
                )


@unittest.skipUnless(
    os.environ.get("DELIVERY_TEST_CONFIG"),
    "Set DELIVERY_TEST_CONFIG for isolated PostgreSQL tests",
)
class Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = d.configuration(os.environ["DELIVERY_TEST_CONFIG"])
        if not cfg.get("dbname", "").startswith(
            "swimrankings_delivery_test"
        ) or cfg.get("host") not in ("localhost", "127.0.0.1"):
            raise RuntimeError("Tests refuse any non-local/non-test database")
        cls.conn = d.connect(
            os.environ["DELIVERY_TEST_CONFIG"], cfg["host"], cfg["dbname"]
        )
        with cls.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.results')")
            if cur.fetchone()[0] is None:
                cur.execute(
                    (Path(__file__).parent / "fixtures/delivery_schema.sql").read_text()
                )
            cur.execute("SET search_path=public")
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS swimrankings_delivery CASCADE")
            cur.execute(
                "TRUNCATE countries,clubs,swimmers,events,meets,results,splits,swimmer_aliases RESTART IDENTITY CASCADE"
            )
        self.conn.commit()

    def scalar(self, query):
        with self.conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchone()[0]

    def test_apply_identity_mapping_retry_and_session_date(self):
        p = packet()
        self.assertEqual(d.apply_package(self.conn, p, True)["results"], 2)
        self.assertNotEqual(self.scalar("SELECT min(id) FROM results"), 101)
        self.assertEqual(
            str(self.scalar("SELECT min(result_date) FROM results")), "2026-09-01"
        )
        self.assertEqual(
            d.apply_package(self.conn, p, True)["status"], "already_applied"
        )
        self.assertEqual(self.scalar("SELECT count(*) FROM results"), 2)

    def test_dry_run_rolls_back_ledger_and_data(self):
        self.assertEqual(
            d.apply_package(self.conn, packet())["status"], "validated_rolled_back"
        )
        self.assertEqual(self.scalar("SELECT count(*) FROM meets"), 0)
        self.assertIsNone(
            self.scalar("SELECT to_regclass('swimrankings_delivery.meets')")
        )

    def test_corrections_and_deletions_are_scoped_and_preserve_ids(self):
        p = packet()
        d.apply_package(self.conn, p, True)
        ident = self.scalar("SELECT min(id) FROM results")
        other = packet()
        other["payload"]["meet"]["meet_id"] = "other"
        for r in other["payload"]["results"]:
            r["source_id"] += 1000
        for s in other["payload"]["splits"]:
            s["source_result_id"] += 1000
        d.apply_package(self.conn, checksum(other), True)
        p2 = revised(p)
        p2["payload"]["results"] = p2["payload"]["results"][:1]
        p2["payload"]["results"][0]["time_seconds"] = "60.50"
        p2["payload"]["splits"] = []
        self.assertEqual(d.apply_package(self.conn, checksum(p2), True)["deleted"], 1)
        self.assertEqual(self.scalar("SELECT min(id) FROM results"), ident)
        self.assertEqual(self.scalar("SELECT count(*) FROM results"), 3)
        self.assertEqual(
            str(self.scalar("SELECT time_seconds FROM results ORDER BY id LIMIT 1")),
            "60.50",
        )
        self.assertEqual(self.scalar("SELECT count(*) FROM splits"), 2)

    def test_conflicting_revision_and_drift_rejected(self):
        p = packet()
        d.apply_package(self.conn, p, True)
        p2 = revised(p)
        p2["previous"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "revision"):
            d.apply_package(self.conn, p2, True)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE results SET points_fina=999")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "outside delivery"):
            d.apply_package(self.conn, p, True)

    def test_database_failure_rolls_back_entire_meet(self):
        p = packet()
        p["payload"]["splits"][1]["time_seconds"] = "invalid-number"
        with self.assertRaises(d.psycopg2.Error):
            d.apply_package(self.conn, checksum(p), True)
        for table in ("meets", "swimmers", "results", "splits", "countries"):
            self.assertEqual(self.scalar("SELECT count(*) FROM " + table), 0)

    def test_existing_meet_requires_adoption(self):
        p = packet()
        d.apply_package(self.conn, p, True)
        ident = self.scalar("SELECT min(id) FROM results")
        with self.conn.cursor() as cur:
            cur.execute("DROP SCHEMA swimrankings_delivery CASCADE")
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "adoption"):
            d.apply_package(self.conn, p, True)
        d.apply_package(self.conn, p, True, adopt_existing=True)
        self.assertEqual(self.scalar("SELECT min(id) FROM results"), ident)

    def test_alias_conflict_rolls_back(self):
        p = packet()
        d.apply_package(self.conn, p, True)
        p2 = revised(p)
        p2["payload"]["aliases"][0]["swimmer_key"] = "fixture-2"
        with self.assertRaisesRegex(ValueError, "Alias identity"):
            d.apply_package(self.conn, checksum(p2), True)
        self.assertEqual(
            self.scalar("SELECT revision FROM swimrankings_delivery.meets"), 1
        )

    def test_source_id_collision_rolls_back(self):
        p = packet()
        d.apply_package(self.conn, p, True)
        p2 = packet()
        p2["payload"]["meet"]["meet_id"] = "second-meet"
        with self.assertRaisesRegex(ValueError, "another meet"):
            d.apply_package(self.conn, checksum(p2), True)
        self.assertEqual(self.scalar("SELECT count(*) FROM meets"), 1)

    def test_wrong_expected_target_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected host/database"):
            d.connect(os.environ["DELIVERY_TEST_CONFIG"], "localhost", "wrong_database")


if __name__ == "__main__":
    unittest.main()
