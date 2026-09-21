"""Publish summaries and reliably notify all website consumers after raw delivery."""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from psycopg2.extras import RealDictCursor, Json
from meet_delivery import LEDGER, digest, rows
from delivery_summaries import rebuild_summary

OUTBOX = """
CREATE TABLE IF NOT EXISTS swimrankings_delivery.publications (
 batch_id text PRIMARY KEY, notice jsonb NOT NULL, revisions jsonb NOT NULL,
 summary jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS swimrankings_delivery.notifications (
 batch_id text NOT NULL REFERENCES swimrankings_delivery.publications(batch_id),
 consumer text NOT NULL, endpoint text NOT NULL, state text NOT NULL DEFAULT 'pending',
 attempts integer NOT NULL DEFAULT 0, error text, completed_at timestamptz,
 PRIMARY KEY(batch_id,consumer));
"""


def consumers(path):
    config = json.loads(Path(path).read_text())
    if (
        not isinstance(config, list)
        or len(config) != 3
        or {x.get("name") for x in config} != {"sophia", "colin", "limmatsharks"}
    ):
        raise ValueError("Configure exactly sophia, colin and limmatsharks consumers")
    for consumer in config:
        url = urlparse(consumer.get("url", ""))
        if (
            url.username
            or url.password
            or url.query
            or url.fragment
            or not url.hostname
        ):
            raise ValueError(
                "Consumer URLs must not contain credentials/query/fragment"
            )
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
        ):
            raise ValueError("Consumer requires HTTPS or local loopback HTTP")
        if not isinstance(consumer.get("token"), str) or len(consumer["token"]) < 32:
            raise ValueError("Each consumer needs a token of at least 32 characters")
    return {c["name"]: c for c in config}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def notify(consumer, notice):
    request = Request(
        consumer["url"],
        data=json.dumps(notice).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {consumer['token']}",
            "Content-Type": "application/json",
        },
    )
    with build_opener(NoRedirect).open(request, timeout=900) as reply:
        response = json.loads(reply.read(1024 * 1024))
        if (
            reply.status != 200
            or response.get("ok") is not True
            or response.get("batchId") != notice["batchId"]
        ):
            raise ValueError("Consumer did not confirm this publication")


def publish(conn, config, commit=False, send=notify, rebuild=rebuild_summary):
    """A source session lock spans summary publication and consumer notifications.

    Apply uses the same advisory key, so another delivery cannot change the
    source halfway through a consumer refresh. Receipts survive process restarts.
    """
    locked = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET search_path=public")
            cur.execute("SET lock_timeout='10s'")
            cur.execute("SELECT pg_try_advisory_lock(784211990) AS locked")
            if not cur.fetchone()["locked"]:
                raise ValueError("Another import/publication is running; retry")
            locked = True
            cur.execute(LEDGER + OUTBOX)
            pending = rows(
                cur,
                "SELECT publisher,meet_key,revision,sha256,affected_from FROM swimrankings_delivery.meets WHERE needs_summary_refresh ORDER BY publisher,meet_key",
            )
            queued = rows(
                cur,
                "SELECT batch_id,consumer,state FROM swimrankings_delivery.notifications WHERE state<>'complete'",
            )
            if not commit:
                conn.rollback()
                return {
                    "status": "plan_only",
                    "meets_requiring_summaries": len(pending),
                    "pending_notifications": len(queued),
                }
            if pending:
                # Legacy receipts have unknown dates: conservatively invalidate history.
                dates = [p["affected_from"] for p in pending]
                affected = min(dates).isoformat() if all(dates) else None
                revisions = [
                    {k: r[k] for k in ("publisher", "meet_key", "revision", "sha256")}
                    for r in pending
                ]
                batch_id = digest(revisions)
                notice = {"version": 1, "batchId": batch_id, "affectedFrom": affected}
                cur.execute(
                    (
                        Path(__file__).with_name("delivery_summary_schema.sql")
                    ).read_text()
                )
                with redirect_stdout(sys.stderr):
                    summary = rebuild(conn)
                cur.execute(
                    "INSERT INTO swimrankings_delivery.publications(batch_id,notice,revisions,summary) VALUES(%s,%s,%s,%s)",
                    (batch_id, Json(notice), Json(revisions), Json(summary)),
                )
                for name, consumer in config.items():
                    cur.execute(
                        "INSERT INTO swimrankings_delivery.notifications(batch_id,consumer,endpoint) VALUES(%s,%s,%s)",
                        (batch_id, name, consumer["url"]),
                    )
                cur.execute(
                    "UPDATE swimrankings_delivery.meets SET needs_summary_refresh=false WHERE needs_summary_refresh"
                )
            conn.commit()
            queued = rows(
                cur,
                "SELECT n.*,p.notice FROM swimrankings_delivery.notifications n JOIN swimrankings_delivery.publications p USING(batch_id) WHERE n.state<>'complete' ORDER BY p.created_at,n.consumer",
            )
            conn.commit()
            completed = []
            failed = []
            for item in queued:
                consumer = config[item["consumer"]]
                if consumer["url"] != item["endpoint"]:
                    raise ValueError(
                        "Consumer endpoint changed; reconcile its pending receipts explicitly"
                    )
                key = (item["batch_id"], item["consumer"])
                cur.execute(
                    "UPDATE swimrankings_delivery.notifications SET state='running',attempts=attempts+1,error=NULL WHERE batch_id=%s AND consumer=%s",
                    key,
                )
                conn.commit()
                print(
                    f"Refreshing {item['consumer']} for batch {item['batch_id'][:12]}",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    send(consumer, item["notice"])
                except Exception as exc:
                    # HTTP/body/driver errors may contain secrets. Persist type only.
                    cur.execute(
                        "UPDATE swimrankings_delivery.notifications SET state='failed',error=%s WHERE batch_id=%s AND consumer=%s",
                        (type(exc).__name__, *key),
                    )
                    failed.append(item["consumer"])
                else:
                    cur.execute(
                        "UPDATE swimrankings_delivery.notifications SET state='complete',completed_at=now(),error=NULL WHERE batch_id=%s AND consumer=%s",
                        key,
                    )
                    completed.append(item["consumer"])
                conn.commit()
            return {
                "status": "failed" if failed else "complete",
                "refreshed": completed,
                "pending_consumers": failed,
            }
    except BaseException:
        conn.rollback()
        raise
    finally:
        if locked:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(784211990)")
            conn.commit()
