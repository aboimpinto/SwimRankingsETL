"""ETL-owned compact sync projection. No Redis or consumer credentials required."""
import argparse
import json
from pathlib import Path


def refresh_if_installed(conn, batch_size=500, max_batches=10):
    """Within the caller's transaction; leave detectable pending work when capped."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regprocedure(current_schema()||'.swim_sync_refresh(integer)') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {"installed": False}
        totals = dict(installed=True, processed=0, changed=0, removed=0, pending=True)
        for _ in range(max_batches):
            cur.execute('SELECT swim_sync_refresh(%s)', (batch_size,))
            report = cur.fetchone()[0]
            for key in ('processed', 'changed', 'removed'):
                totals[key] += report[key]
            totals['pending'] = report['pending']
            if not report['pending']:
                break
        return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--expect-host', required=True)
    parser.add_argument('--expect-database', required=True)
    parser.add_argument('--install', action='store_true', help='Explicit install/rebuild; queues existing facts once')
    parser.add_argument('--batch-size', type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 5000:
        parser.error('batch-size must be 1..5000')
    import psycopg2
    with psycopg2.connect(**json.loads(args.config.read_text()), connect_timeout=10) as conn:
        if conn.info.host != args.expect_host or conn.info.dbname != args.expect_database:
            raise ValueError('Unexpected target host/database')
        if args.install:
            with conn.cursor() as cur:
                cur.execute(Path(__file__).with_suffix('.sql').read_text())
            conn.commit()
        while True:
            report = refresh_if_installed(conn, args.batch_size, max_batches=1)
            conn.commit()  # Each bounded batch is independently durable.
            print(json.dumps(report), flush=True)
            if not report.get('pending'):
                break


if __name__ == '__main__':
    main()
