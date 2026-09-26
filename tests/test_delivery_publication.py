import json
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.error import HTTPError
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import meet_delivery as d
import publish_delivery as pub
import test_meet_delivery as fixture

CONFIG = {
    name: {
        "name": name,
        "url": f"https://{name}.example/api/integrations/swimrankings/refresh",
        "token": "test-token-" * 4,
    }
    for name in ("sophia", "colin", "limmatsharks")
}


@unittest.skipUnless(
    os.environ.get("DELIVERY_TEST_CONFIG"), "Requires isolated test database"
)
class Publication(unittest.TestCase):
    setUpClass = classmethod(fixture.Database.setUpClass.__func__)
    tearDownClass = classmethod(fixture.Database.tearDownClass.__func__)
    setUp = fixture.Database.setUp
    scalar = fixture.Database.scalar

    def seed(self):
        p = fixture.packet()
        p["payload"]["results"][0]["result_date"] = "2026-08-31"
        p["payload"]["results"][1].update(swimmer_key="fixture-1", heat=2)
        d.apply_package(self.conn, fixture.checksum(p), True)
        return p

    def test_summary_boundary_and_all_three_notifications(self):
        self.seed()
        sent = []
        result = pub.publish(
            self.conn, CONFIG, True, send=lambda c, n: sent.append((c["name"], n))
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname='splits_result_order_idx'"),1)
        self.assertEqual({c for c, n in sent}, set(CONFIG))
        self.assertTrue(all(n["affectedFrom"] == "2026-08-31" for c, n in sent))
        self.assertEqual(
            self.scalar(
                "SELECT count(DISTINCT season_end_year) FROM athlete_season_points"
            ),
            2,
        )
        self.assertEqual(
            self.scalar(
                "SELECT count(DISTINCT season_end_year) FROM athlete_meet_points"
            ),
            2,
        )
        self.assertEqual(
            self.scalar(
                "SELECT count(DISTINCT meet_date) FROM athlete_meet_points WHERE distance=100"
            ),
            2,
        )
        self.assertEqual(
            self.scalar(
                "SELECT count(*) FROM swimrankings_delivery.meets WHERE needs_summary_refresh"
            ),
            0,
        )
        self.assertEqual(
            self.scalar(
                "SELECT count(*) FROM swimrankings_delivery.notifications WHERE state='complete'"
            ),
            3,
        )
        with self.conn.cursor() as cur:
            cur.execute("SELECT revisions FROM swimrankings_delivery.publications")
            self.assertEqual(
                cur.fetchone()[0][0]["sha256"],
                self.scalar("SELECT sha256 FROM swimrankings_delivery.meets"),
            )

    def test_result_reads_remain_available_during_summary_rebuild(self):
        self.seed()
        def rebuilding(conn):
            cfg=d.configuration(os.environ['DELIVERY_TEST_CONFIG'])
            probe=d.connect(os.environ['DELIVERY_TEST_CONFIG'],cfg['host'],cfg['dbname'],readonly=True)
            try:
                with probe.cursor() as c:
                    c.execute("SET LOCAL lock_timeout='500ms'")
                    c.execute('SELECT count(*) FROM results')
                    self.assertEqual(c.fetchone()[0],2)
                    c.execute('SELECT pg_try_advisory_lock(784211990)')
                    self.assertFalse(c.fetchone()[0])
            finally:
                probe.rollback();probe.close()
            return {'read_check':'passed'}
        result=pub.publish(self.conn,CONFIG,True,send=lambda c,n:None,rebuild=rebuilding)
        self.assertEqual(result['status'],'complete')

    def test_summary_failure_keeps_pending_and_never_notifies(self):
        self.seed()
        send = Mock()

        def failing(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM results")
            raise RuntimeError("simulated summary error")

        with self.assertRaises(RuntimeError):
            pub.publish(self.conn, CONFIG, True, send=send, rebuild=failing)
        self.assertEqual(self.scalar("SELECT count(*) FROM results"), 2)
        self.assertEqual(
            self.scalar(
                "SELECT count(*) FROM swimrankings_delivery.meets WHERE needs_summary_refresh"
            ),
            1,
        )
        send.assert_not_called()

    def test_failed_site_retries_without_raw_import_or_other_refreshes(self):
        self.seed()
        sent = []

        def send(c, n):
            sent.append(c["name"])
            if c["name"] == "colin":
                raise TimeoutError("secret-url")

        first = pub.publish(self.conn, CONFIG, True, send=send)
        self.assertEqual(first["pending_consumers"], ["colin"])
        count = self.scalar("SELECT count(*) FROM results")
        sent.clear()
        second = pub.publish(
            self.conn,
            CONFIG,
            True,
            send=lambda c, n: sent.append(c["name"]),
            rebuild=Mock(side_effect=AssertionError("must not rebuild summaries")),
        )
        self.assertEqual(second["status"], "complete")
        self.assertEqual(sent, ["colin"])
        self.assertEqual(self.scalar("SELECT count(*) FROM results"), count)
        final_send = Mock()
        pub.publish(self.conn, CONFIG, True, send=final_send)
        final_send.assert_not_called()

    def test_preview_changes_nothing_and_never_sends(self):
        self.seed()
        send = Mock()
        rebuild = Mock()
        self.assertEqual(
            pub.publish(self.conn, CONFIG, send=send, rebuild=rebuild)[
                "meets_requiring_summaries"
            ],
            1,
        )
        self.assertEqual(
            self.scalar(
                "SELECT count(*) FROM swimrankings_delivery.meets WHERE needs_summary_refresh"
            ),
            1,
        )
        send.assert_not_called()
        rebuild.assert_not_called()

    def test_unknown_dates_and_invalid_status_are_not_ranked(self):
        p = fixture.packet()
        p["payload"]["results"][0]["result_date"] = None
        p["payload"]["results"][1]["status"] = "DSQ"
        d.apply_package(self.conn, fixture.checksum(p), True)
        sent = []
        pub.publish(self.conn, CONFIG, True, send=lambda c, n: sent.append(n))
        self.assertTrue(all(n["affectedFrom"] is None for n in sent))
        for table in (
            "athlete_season_points",
            "athlete_meet_points",
            "race_points_bands",
        ):
            self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), 0)

    def test_removed_old_session_is_invalidation_input(self):
        p = self.seed()
        pub.publish(self.conn, CONFIG, True, send=lambda c, n: None)
        correction = fixture.revised(p)
        correction["payload"]["results"][0]["result_date"] = "2026-09-02"
        d.apply_package(self.conn, fixture.checksum(correction), True)
        self.assertEqual(
            str(self.scalar("SELECT affected_from FROM swimrankings_delivery.meets")),
            "2026-08-31",
        )


class Transport(unittest.TestCase):
    def test_consumer_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consumers.json"
            items = list(CONFIG.values())
            path.write_text(json.dumps(items))
            self.assertEqual(set(pub.consumers(path)), set(CONFIG))
            for bad in (
                "http://public.example/refresh",
                "https://user:pass@example/refresh",
                "https://example/refresh?token=x",
            ):
                items[0] = {**items[0], "url": bad}
                path.write_text(json.dumps(items))
                with self.assertRaises(ValueError):
                    pub.consumers(path)

    def test_http_acknowledgement_and_no_redirect(self):
        notice = {"version": 1, "batchId": "b" * 64, "affectedFrom": None}
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append(
                    (
                        self.path,
                        self.headers.get("Authorization"),
                        json.loads(
                            self.rfile.read(int(self.headers["Content-Length"]))
                        ),
                    )
                )
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/stolen")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "ok": True,
                            "batchId": (
                                notice["batchId"] if self.path == "/ok" else "wrong"
                            ),
                        }
                    ).encode()
                )

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            consumer = {
                **CONFIG["sophia"],
                "url": f"http://127.0.0.1:{server.server_port}/ok",
            }
            pub.notify(consumer, notice)
            self.assertEqual(requests[0][1:], (f"Bearer {consumer['token']}", notice))
            with self.assertRaises(ValueError):
                pub.notify(
                    {**consumer, "url": consumer["url"].replace("/ok", "/wrong")},
                    notice,
                )
            with self.assertRaises(HTTPError):
                pub.notify(
                    {**consumer, "url": consumer["url"].replace("/ok", "/redirect")},
                    notice,
                )
            self.assertEqual([r[0] for r in requests], ["/ok", "/wrong", "/redirect"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
