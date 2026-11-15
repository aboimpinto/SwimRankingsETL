#!/usr/bin/env python3
"""Deliver an attribution-only revision without rewriting races or split IDs.

Requires both immutable revisions and a fully published destination. The caller
must subsequently refresh and verify the SwimProfiles club projections.
"""
import argparse
import copy
import json

from psycopg2.extras import RealDictCursor
import meet_delivery as delivery


def without_attribution(packet):
    payload = copy.deepcopy(packet['payload'])
    for result in payload['results']:
        result.pop('club_name', None)
        result.pop('club_source', None)
    return payload


def apply_club_patch(conn, previous, packet, commit=False):
    delivery.validate(previous)
    delivery.validate(packet)
    if (previous['publisher'] != packet['publisher']
            or packet['revision'] != previous['revision'] + 1
            or packet['previous'] != previous['sha256']):
        raise ValueError('Club patch requires consecutive revisions from one publisher')
    if without_attribution(previous) != without_attribution(packet):
        raise ValueError('Club patch contains changes outside race club attribution')
    publisher = packet['publisher']
    key = packet['payload']['meet']['meet_id']
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='10s'")
            cur.execute("SET LOCAL statement_timeout='2min'")
            cur.execute('SET LOCAL search_path=public')
            cur.execute('SELECT pg_advisory_xact_lock(784211990)')
            cur.execute('LOCK TABLE meets, results, splits IN SHARE ROW EXCLUSIVE MODE')
            cur.execute('SELECT * FROM swimrankings_delivery.meets WHERE publisher=%s AND meet_key=%s FOR UPDATE', (publisher, key))
            old = cur.fetchone()
            if not old:
                raise ValueError('Club patch requires an existing delivery receipt')
            before = delivery.meet_digest(conn, old['meet_id'])
            if before != old['result_digest']:
                raise ValueError('Destination meet changed outside delivery')
            replay = old['revision'] == packet['revision'] and old['sha256'] == packet['sha256']
            cur.execute('SELECT d.source_id,d.target_id,r.club_name,r.club_source FROM swimrankings_delivery.results d JOIN results r ON r.id=d.target_id AND r.meet_id=%s WHERE d.publisher=%s AND d.meet_key=%s', (old['meet_id'], publisher, key))
            mapped = {r['source_id']: r for r in cur.fetchall()}
            expected = packet if replay else previous
            if set(mapped) != {r['source_id'] for r in expected['payload']['results']}:
                raise ValueError('Destination result mapping differs from complete package')
            for race in expected['payload']['results']:
                actual_row = mapped[race['source_id']]
                if (actual_row['club_name'], actual_row['club_source']) != (race.get('club_name'), race.get('club_source')):
                    raise ValueError('Destination club evidence changed outside delivery')
            if replay:
                conn.rollback()
                return dict(status='already_applied', meet=key, revision=packet['revision'])
            if old['revision'] != previous['revision'] or old['sha256'] != previous['sha256']:
                raise ValueError('Destination revision does not match previous package')
            if old['needs_summary_refresh']:
                raise ValueError('Complete pending normal publication before club patch')
            targets = {key: row['target_id'] for key, row in mapped.items()}
            changed = 0
            for race in packet['payload']['results']:
                cur.execute('UPDATE results SET club_name=%s,club_source=%s WHERE id=%s AND meet_id=%s AND (club_name,club_source) IS DISTINCT FROM (%s,%s)',
                            (race.get('club_name'), race.get('club_source'), targets[race['source_id']], old['meet_id'], race.get('club_name'), race.get('club_source')))
                changed += cur.rowcount
            actual = delivery.meet_digest(conn, old['meet_id'])
            cur.execute('UPDATE swimrankings_delivery.meets SET revision=%s,sha256=%s,result_digest=%s,applied_at=now() WHERE publisher=%s AND meet_key=%s',
                        (packet['revision'], packet['sha256'], actual, publisher, key))
            cur.execute('INSERT INTO swimrankings_delivery.audit(publisher,meet_key,revision,sha256,before_digest) VALUES(%s,%s,%s,%s,%s)',
                        (publisher, key, packet['revision'], packet['sha256'], before))
        report = dict(status='applied' if commit else 'validated_rolled_back', meet=key,
                      revision=packet['revision'], changedClubAttributions=changed,
                      summary_refresh_required=False, club_publication_required=True)
        conn.commit() if commit else conn.rollback()
        return report
    except BaseException:
        conn.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--expect-host', required=True)
    parser.add_argument('--expect-database', required=True)
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    conn = delivery.connect(args.config, args.expect_host, args.expect_database)
    try:
        print(json.dumps(apply_club_patch(conn, delivery.read_package(args.previous),
                                         delivery.read_package(args.package), args.commit)))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
