#!/usr/bin/env python3
"""Refresh published official record lists using the established ETL HTTP/LENEX tools."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse, urljoin

from import_Swiss_NationalRecords import (
    DEFAULT_RECORD_LIST_IDS, build_record_lenex_url, load_root_from_lxf_bytes,
    parse_records, ensure_schema, insert_record, insert_splits,
)
from swimrankings_http import (
    SwimRankingsHttpClient, SwimRankingsAuthenticationError, SwimRankingsRateLimitError,
    validate_lenex_payload, DownloadedFile,
)

CATALOGUE = 'https://www.swimrankings.net/index.php?page=recordSelect'
SCHEMA = """
CREATE TABLE IF NOT EXISTS swimrankings_record_refresh (
 record_list_id text NOT NULL, course text NOT NULL,
 status text NOT NULL, checked_at timestamptz NOT NULL DEFAULT now(),
 successful_at timestamptz, content_hash text, source_hash text,
 record_count integer NOT NULL DEFAULT 0, split_count integer NOT NULL DEFAULT 0,
 nations jsonb NOT NULL DEFAULT '[]', record_types jsonb NOT NULL DEFAULT '[]',
 error text, PRIMARY KEY(record_list_id,course));
"""

class CatalogueParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = set(); self.pages = set(); self.anchor = None; self.label = []; self.entries = {}; self.anchor_ids = []
    def handle_starttag(self, tag, attrs):
        if tag != 'a': return
        href = dict(attrs).get('href', '')
        url = urlparse(href)
        if url.netloc and url.netloc not in ('www.swimrankings.net','swimrankings.net'): return
        self.anchor = href; self.label = []; self.anchor_ids = []
        for key, values in parse_qs(url.query).items():
            if key.lower() == 'recordlistid':
                self.anchor_ids.extend(value for value in values if value.isdigit())
                self.ids.update(self.anchor_ids)


    def handle_data(self, text):
        if self.anchor is not None: self.label.append(text)

    def handle_endtag(self, tag):
        if tag != 'a' or self.anchor is None: return
        query = parse_qs(urlparse(self.anchor).query)
        page = query.get('page', [''])[0].lower()
        label = ''.join(self.label).strip()
        for list_id in self.anchor_ids:
            entry = self.entries.setdefault(list_id, {'id': list_id, 'labels': [], 'links': []})
            if label and label not in entry['labels']: entry['labels'].append(label)
            if self.anchor not in entry['links']: entry['links'].append(self.anchor)
        # Follow only published country navigation / record catalogue links.
        # Never crawl athlete pages or scrape individual ranking results.
        if page == 'recordselect' or (
            page.startswith('ranking') and len(label) == 3 and label.isupper() and label.isalpha()
        ):
            self.pages.add(self.anchor)
        self.anchor = None


def discover_catalogue(client, url=CATALOGUE, delay=1, inventory=None):
    pending = [(url, 0)]
    visited, ids, errors = set(), set(), []
    while pending:
        page_url, depth = pending.pop(0)
        if page_url in visited: continue
        if len(visited) >= 100:
            errors.append('Catalogue navigation exceeds 100 pages; discovery is incomplete')
            break
        visited.add(page_url)
        try:
            downloaded = client.download(page_url)
            parser = CatalogueParser()
            parser.feed(downloaded.data.decode('utf-8', errors='replace'))
            ids.update(parser.ids)
            if inventory is not None: inventory.update(parser.entries)
            if depth < 2:
                for href in sorted(parser.pages):
                    linked = urljoin(page_url, href)
                    target = urlparse(linked)
                    if target.scheme == 'https' and target.netloc in ('www.swimrankings.net', 'swimrankings.net'):
                        pending.append((linked, depth + 1))
        except Exception as error:
            errors.append(str(error))
            if isinstance(error, (SwimRankingsAuthenticationError, SwimRankingsRateLimitError)) or isinstance(error, HTTPError) and error.code in (401, 403, 429):
                break
        if pending: time.sleep(max(0, delay))
    if not ids: errors.append('Catalogue contains no record-list links; keep previous catalogue')
    return sorted(ids, key=int), errors

def discover_lists(html):
    parser = CatalogueParser(); parser.feed(html)
    if not parser.ids: raise ValueError('Catalogue contains no record-list links; keep previous catalogue')
    return sorted(parser.ids, key=int)

def parse_snapshot(data, list_id, course, url):
    root = load_root_from_lxf_bytes(data)
    if root.tag != 'LENEX': raise ValueError('Not a LENEX document')
    records = parse_records(root,url,hashlib.sha256(data).hexdigest(),list_id)
    if not records: raise ValueError('Empty record file; keep the previous snapshot')
    if len(records) != len(root.findall('.//RECORDLIST/RECORDS/RECORD')):
        raise ValueError('One or more record rows could not be parsed; keep the previous snapshot')
    if any(r.record_list_id != list_id or r.course != course for r in records):
        raise ValueError('Record list/course mismatch; keep the previous snapshot')
    if any(r.time_seconds <= 0 or r.distance <= 0 for r in records):
        raise ValueError('Invalid record measurements')
    # Stable semantic hash ignores ZIP packaging/date and raw source hash.
    canonical = [dict(asdict(r), source_hash='') for r in records]
    content_hash = hashlib.sha256(json.dumps(canonical,sort_keys=True,default=str).encode()).hexdigest()
    return records,content_hash

def snapshot_inventory(records):
    definitions = {}
    for record in records:
        key = (record.record_list_name, record.nation, record.record_type,
               record.gender, record.age_min, record.age_max,
               record.comparison_scope, record.scope_reason)
        item = definitions.setdefault(key, {
            'name': record.record_list_name, 'nation': record.nation,
            'type': record.record_type, 'gender': record.gender,
            'age_min': record.age_min, 'age_max': record.age_max,
            'comparison_scope': record.comparison_scope,
            'scope_reason': record.scope_reason, 'records': 0, 'splits': 0,
        })
        item['records'] += 1
        item['splits'] += len(record.splits)
    return list(definitions.values())


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(report, indent=2) + '\n')
    tmp.replace(path)


def publish_snapshot(conn,records,content_hash,list_id,course):
    with conn.cursor() as cur:
        ensure_schema(cur); cur.execute(SCHEMA)
        cur.execute('SELECT content_hash FROM swimrankings_record_refresh WHERE record_list_id=%s AND course=%s',(list_id,course))
        old=cur.fetchone(); changed=not old or old[0]!=content_hash
        if changed:
            cur.execute('DELETE FROM swimrankings_records WHERE record_list_id=%s AND course=%s',(list_id,course))
            for record in records:
                record_id=insert_record(cur,record);insert_splits(cur,record_id,record)
        cur.execute("""INSERT INTO swimrankings_record_refresh(record_list_id,course,status,successful_at,content_hash,source_hash,record_count,split_count,nations,record_types)
          VALUES(%s,%s,'ok',now(),%s,%s,%s,%s,%s::jsonb,%s::jsonb)
          ON CONFLICT(record_list_id,course) DO UPDATE SET status='ok',checked_at=now(),successful_at=now(),content_hash=excluded.content_hash,
          source_hash=excluded.source_hash,record_count=excluded.record_count,split_count=excluded.split_count,nations=excluded.nations,record_types=excluded.record_types,error=null""",
          (list_id,course,content_hash,records[0].source_hash,len(records),sum(len(r.splits) for r in records),json.dumps(sorted({r.nation for r in records if r.nation})),json.dumps(sorted({r.record_type for r in records if r.record_type}))))
    conn.commit()
    return changed

def report_failure(conn,list_id,course,error):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("""INSERT INTO swimrankings_record_refresh(record_list_id,course,status,error) VALUES(%s,%s,'failed',%s)
          ON CONFLICT(record_list_id,course) DO UPDATE SET status='failed',checked_at=now(),error=excluded.error""",(list_id,course,str(error)[:500]))
    conn.commit()

def refresh(conn,client,*,catalogue_html=None,list_ids=(),save_dir=Path('data/records'),dry_run=False,delay=1,catalogue_provided=False,catalogue_url=CATALOGUE,inventory_path=None):
    known=set(list_ids)
    if conn:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(734341)');
            if not cur.fetchone()[0]: raise RuntimeError('Another record refresh is running')
            if not dry_run: ensure_schema(cur)
            if not catalogue_provided:
                cur.execute("SELECT to_regclass('swimrankings_records')")
                if cur.fetchone()[0] is not None:
                    cur.execute('SELECT DISTINCT record_list_id FROM swimrankings_records')
                    known.update(r[0] for r in cur.fetchall())
        conn.commit()
    report={'catalogue':'ok','started_at':datetime.now(timezone.utc).isoformat(),
            'catalogue_source':catalogue_url,'inventory':{},'files':[],'errors':[]}
    if inventory_path and inventory_path.exists() and not catalogue_provided:
        saved=json.loads(inventory_path.read_text())
        report['inventory'].update(saved.get('inventory',{}))
        known.update(report['inventory'])
        report['previous_catalogue_at']=saved.get('checked_at')
    try:
        try:
            if catalogue_html is not None:
                known.update(discover_lists(catalogue_html))
                parser=CatalogueParser();parser.feed(catalogue_html)
                report['inventory'].update(parser.entries)
                report['catalogue']='provided_files_only' if catalogue_provided else 'saved_html'
                report['catalogue_source']='offline bundle' if catalogue_provided else 'saved HTML'
                report['catalogue_sha256']=hashlib.sha256(catalogue_html.encode()).hexdigest()
            else:
                discovered, errors = discover_catalogue(client,catalogue_url,delay,report['inventory'])
                known.update(discovered)
                if errors: raise ValueError('; '.join(errors))
            if conn and not dry_run and not catalogue_provided:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA)
                    cur.execute("""INSERT INTO swimrankings_record_refresh(record_list_id,course,status,successful_at) VALUES('catalogue','',%s,now())
                      ON CONFLICT(record_list_id,course) DO UPDATE SET status=excluded.status,checked_at=now(),successful_at=now(),error=null""",(report['catalogue'],))
                conn.commit()
        except Exception as error:
            report['catalogue']='failed';report['errors'].append({'catalogue':str(error)})
            if conn and not dry_run: report_failure(conn,'catalogue','',error)
            # Catalogue access is separate from the known RecordLenex service.
        if not known:
            known.update(DEFAULT_RECORD_LIST_IDS)
            report['seed_lists_only']=True
        report['requested_lists']=sorted(known,key=int)
        if inventory_path and report['inventory'] and not catalogue_provided:
            write_report(inventory_path,{'checked_at':report['started_at'],'status':report['catalogue'],
                'source':report['catalogue_source'],'inventory':report['inventory']})
        for list_id in sorted(known,key=int):
            for course in ('LCM','SCM'):
                url=build_record_lenex_url(list_id,course,'fina_2025','us')
                try:
                    downloaded=client.download(url);validate_lenex_payload(downloaded)
                    records,fingerprint=parse_snapshot(downloaded.data,list_id,course,url)
                    save_dir.mkdir(parents=True,exist_ok=True)
                    path=save_dir/f'swimrankings_records_{list_id}_{course}.lxf'
                    tmp=path.with_suffix('.part');tmp.write_bytes(downloaded.data);tmp.replace(path)
                    changed=publish_snapshot(conn,records,fingerprint,list_id,course) if conn and not dry_run else False
                    item={'list':list_id,'course':course,'records':len(records),'splits':sum(len(r.splits) for r in records),'changed':changed,'dry_run':dry_run,
                          'source_url':url,'sha256':hashlib.sha256(downloaded.data).hexdigest(),
                          'content_hash':fingerprint,'definitions':snapshot_inventory(records)}
                    report['files'].append(item);print(json.dumps({k:v for k,v in item.items() if k != 'definitions'}),flush=True)
                except Exception as error:
                    report['errors'].append({'list':list_id,'course':course,'error':str(error)})
                    if conn and not dry_run:report_failure(conn,list_id,course,error)
                    if isinstance(error,(SwimRankingsAuthenticationError,SwimRankingsRateLimitError)) or isinstance(error,HTTPError) and error.code in (401,403,429):
                        return report
                time.sleep(max(0,delay))
        return report
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        report['complete_published_catalogue']=report['catalogue']=='ok' and not report['errors']
        report['countries_with_comparisons']=sorted({d['nation'] for f in report['files'] for d in f['definitions']
            if d['nation'] and d['comparison_scope'] in ('national','age')})
        report['unmapped_definitions']=[dict(list=f['list'],course=f['course'],**d)
            for f in report['files'] for d in f['definitions'] if d['comparison_scope']=='unmapped']
        if conn:
            with conn.cursor() as cur:cur.execute('SELECT pg_advisory_unlock(734341)')
            conn.commit()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,help='Private PostgreSQL connection JSON')
    p.add_argument('--catalogue-html',type=Path,help='Catalogue saved from the normal SwimRankings browser session')
    p.add_argument('--record-list-id',action='append',default=[])
    p.add_argument('--catalogue-url',default=CATALOGUE,help='Published homepage or record catalogue URL')
    p.add_argument('--input-directory',type=Path,help='Import previously downloaded record files without network access (e.g. AWS)')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--save-dir',type=Path,default=Path('data/records'))
    p.add_argument('--report',type=Path)
    p.add_argument('--inventory',type=Path,help='Persist published IDs for retry when catalogue is unavailable')
    a=p.parse_args()
    if any(not value.isdigit() for value in a.record_list_id):p.error('Record list IDs must be numeric')
    url=urlparse(a.catalogue_url)
    if url.scheme != 'https' or url.netloc not in ('www.swimrankings.net','swimrankings.net'):p.error('Catalogue must be an HTTPS SwimRankings URL')
    if not a.dry_run and not a.config:p.error('--config is required for database updates')
    import psycopg2
    conn=psycopg2.connect(**json.loads(a.config.read_text())) if a.config else None
    try:
        client=SwimRankingsHttpClient.from_environment()
        catalogue_html=a.catalogue_html.read_text() if a.catalogue_html else None
        if a.input_directory:
            files=list(a.input_directory.glob('swimrankings_records_*_*.lxf'))
            ids={f.name.split('_')[2] for f in files if f.name.split('_')[2].isdigit()}
            if not ids:raise ValueError('No record files found in input directory')
            catalogue_html=''.join(f'<a href="?recordListId={i}">List</a>' for i in sorted(ids))
            class Files:
                def download(self,url):
                    args=parse_qs(urlparse(url).query)
                    path=a.input_directory/f"swimrankings_records_{args['RecordListId'][0]}_{args['Course'][0]}.lxf"
                    return DownloadedFile(path.read_bytes(),url,'application/zip')
            client=Files()
        report=refresh(conn,client,catalogue_html=catalogue_html,list_ids=a.record_list_id,save_dir=a.save_dir,dry_run=a.dry_run,catalogue_provided=bool(a.input_directory),catalogue_url=a.catalogue_url,inventory_path=a.inventory)
        if a.input_directory:report['catalogue']='provided_files_only'
        if a.report:write_report(a.report,report)
        print(json.dumps(report,indent=2))
        return 1 if report['errors'] else 0
    finally:
        if conn:conn.close()
if __name__=='__main__':raise SystemExit(main())
