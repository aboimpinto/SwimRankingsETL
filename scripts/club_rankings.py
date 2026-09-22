#!/usr/bin/env python3
"""Complete official all-time Open and exact-age club populations; retain every published row."""
import argparse, hashlib, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from club_record_baselines import canonical, digest, centiseconds, CLUB_ID, source_url, standard_events, AGES, validate_age

STROKES={'Freestyle':'FREE','Backstroke':'BACK','Breaststroke':'BREAST','Butterfly':'FLY','Medley':'IM'}
SCHEMA='''CREATE TABLE IF NOT EXISTS club_ranking_imports (sha256 text PRIMARY KEY,payload jsonb NOT NULL,imported_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS club_ranking_populations (event_key text PRIMARY KEY,payload jsonb NOT NULL,imported_at timestamptz NOT NULL DEFAULT now());'''

def event_name(text):
 m=re.fullmatch(r'(\d+)m (Freestyle|Backstroke|Breaststroke|Butterfly|Medley)',text)
 return (int(m[1]),STROKES[m[2]]) if m else None

def population_key(distance, stroke, course, gender, age='X_X'):
 key=f'{distance}:{stroke}:{course}:{gender}'
 return key if age=='X_X' else f'{key}:{age}'

def category_title(gender, age):
 label='Open' if age=='X_X' else '11 years and younger' if age=='X_11' else f"{age.split('_')[0]} years"
 return f"{'Women' if gender=='F' else 'Men'}, {label}"

def check_titles(soup,course,gender,age):
 if age not in AGES:raise ValueError('Unsupported source age category')
 titles=[e.get_text(' ',strip=True) for e in soup.select('.titleLeft,.titleRight,.titleCenter')]
 if 'Limmat Sharks Zuerich' not in titles or category_title(gender,age) not in titles or ('Long Course (50m)' if course=='LCM' else 'Short Course (25m)') not in titles or 'Alltime' not in titles:
  raise ValueError('Wrong club ranking category or access unavailable')
 return titles

def parse_catalog(html,url,course,gender,age='X_X'):
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(html,'html.parser');titles=check_titles(soup,course,gender,age)
 if 'Top Times' not in titles or not soup.select_one('table.rankingList'):raise ValueError('Incomplete event catalog')
 events=[]
 for a in soup.select('a[href*="rankingClubId="]'):
  event=event_name(a.get_text(' ',strip=True))
  if event:events.append((event,a['href']))
 if len({e[0] for e in events})!=len(events):raise ValueError('Duplicate catalog event')
 return events

def parse_page(html, url, course, gender, distance, stroke, age_group="X_X"):
 from bs4 import BeautifulSoup
 s=BeautifulSoup(html,'html.parser')
 titles=check_titles(s,course,gender,age_group)
 if not any(event_name(t)==(distance,stroke) for t in titles):raise ValueError('Wrong ranking event')
 nav=s.select_one('table.navigation'); match=re.search(r'Places from 1 to (\d+)',nav.get_text(' ',strip=True) if nav else '')
 if not match:raise ValueError('Missing pagination total')
 built=s.select_one('.titleLeftNormal').get_text(' ',strip=True)
 rows=[]
 for tr in s.select('table.rankingList tr[class]'):
  cells=tr.find_all('td',recursive=False)
  if len(cells)!=11:raise ValueError('Unexpected ranking columns')
  text=[c.get_text(' ',strip=True).replace('\xa0',' ') for c in cells]
  if text[3] not in ('Limmat Sharks Zuerich','Limmat Sharks Zürich'):raise ValueError('Wrong result club')
  last,first=[n.strip() for n in text[0].split(',',1)]
  def link_id(cell,key):
   a=cell.select_one('a');v=parse_qs(urlparse(a['href']).query).get(key,[''])[0] if a else ''
   if not v.isdigit():raise ValueError('Missing stable source identity')
   return v
  rows.append(dict(athlete_id=link_id(cells[0],'athleteId'),result_id=link_id(cells[4],'id'),first_name=first,last_name=last,birth_year=int(text[1]),country_code=text[2],club_id=CLUB_ID,time_cs=centiseconds(next(cells[4].select_one('a').stripped_strings)),time_annotation=' '.join(t.get_text(strip=True) for t in cells[4].select('sup')),position=int(text[8].strip('.')),date=datetime.strptime(text[9],'%d %b %Y').date().isoformat(),is_split=bool(cells[4].select('img')),meet=cells[10].select_one('a').get('title',''),city=text[10],meet_id=link_id(cells[10],'meetId')))
 return {'total':int(match[1]),'built':built,'rows':rows,'source_url':url,'sha256':hashlib.sha256(html.encode()).hexdigest()}

def validate_population(p):
 if p['club_id']!=CLUB_ID or p['course'] not in ('SCM','LCM') or p['gender'] not in ('F','M') or p['stroke'] not in STROKES.values() or not isinstance(p['distance'],int) or p['distance']<=0:raise ValueError('Invalid event')
 age=p.get('age_group','X_X')
 if age not in AGES or p['key']!=population_key(p['distance'],p['stroke'],p['course'],p['gender'],age):raise ValueError('Invalid key/category')
 stamp=datetime.fromisoformat(p['captured_at'])
 if stamp.tzinfo is None or not p['built'].startswith('Last built '):raise ValueError('Invalid source timestamp')
 for page in p['pages']:
  url=urlparse(page['source_url']);params=parse_qs(url.query)
  if url.scheme!='https' or url.hostname!='www.swimrankings.net' or url.username or params.get('page')!=['rankingDetail'] or not params.get('rankingClubId',[''])[0].isdigit() or params.get('firstPlace')!=[str(page['offset'])] or not re.fullmatch('[a-f0-9]{64}',page['sha256']):raise ValueError('Invalid page provenance')
 rows=p['rows']
 if not rows or len(rows)!=p['total'] or len({r['athlete_id'] for r in rows})!=len(rows):raise ValueError('Incomplete/duplicate athlete population')
 if sum(x['count'] for x in p['pages'])!=p['total'] or [x['offset'] for x in p['pages']]!=list(range(1,p['total']+1,25)):raise ValueError('Incomplete pagination')
 for i,r in enumerate(rows):
  if r['club_id']!=CLUB_ID or not r['athlete_id'].isdigit() or not r['result_id'].isdigit() or not r['first_name'] or not r['last_name'] or type(r['birth_year']) is not int or not 1800<r['birth_year']<=int(r['date'][:4]) or type(r['time_cs']) is not int or r['time_cs']<=0 or type(r['is_split']) is not bool:raise ValueError('Invalid performance')
  datetime.strptime(r['date'],'%Y-%m-%d')
  validate_age(r['birth_year'],r['date'],age)
  if r['date']>p['captured_at'][:10]:raise ValueError('Future source performance')
  if i and r['time_cs']<rows[i-1]['time_cs']:raise ValueError('Unsorted population')
  expected=next(j+1 for j,v in enumerate(rows) if v['time_cs']==r['time_cs'])
  if r['position']!=expected:raise ValueError('Inconsistent source ranks/ties')

def build_package(populations, age_groups=None, catalogs=None):
 populations=sorted(populations,key=lambda p:p['key'])
 if len({p['key'] for p in populations})!=len(populations):raise ValueError('Duplicate populations')
 for p in populations:validate_population(p)
 if age_groups is None:
  if any(p.get('age_group','X_X')!='X_X' for p in populations):raise ValueError('Age populations require version 2')
  expected={population_key(int(e.split(':')[2]),e.split(':')[3],c,g) for c in ('LCM','SCM') for g in ('F','M') for e in standard_events(c)}
  missing=sorted(expected-{p['key'] for p in populations})
  payload={'club_id':CLUB_ID,'scope':'alltime-open','coverage':{'complete':not missing,'missing_events':missing},'populations':populations}
  version=1
 else:
  age_groups=sorted(age_groups)
  if not age_groups or len(set(age_groups))!=len(age_groups) or set(age_groups)-set(AGES):raise ValueError('Invalid requested categories')
  if any(p.get('age_group','X_X') not in age_groups for p in populations):raise ValueError('Unrequested population')
  catalogs=sorted(catalogs or [],key=lambda c:c['key']);seen=set();published=set();unlisted=set()
  for cat in catalogs:
   c,g,age=cat['course'],cat['gender'],cat['age_group'];key=f'{c}:{g}:{age}'
   if c not in ('LCM','SCM') or g not in ('F','M') or age not in age_groups or cat['key']!=key or key in seen:raise ValueError('Invalid catalog category')
   seen.add(key)
   if cat['source_url']!=source_url(c,g,age) or not re.fullmatch('[a-f0-9]{64}',cat['sha256']) or datetime.fromisoformat(cat['captured_at']).tzinfo is None:raise ValueError('Invalid catalog provenance')
   if len(set(cat['events']))!=len(cat['events']):raise ValueError('Duplicate catalog events')
   for event in cat['events']:
    parts=event.split(':');d,stroke=int(parts[0]),parts[1]
    if d<=0 or stroke not in STROKES.values() or event!=population_key(d,stroke,c,g,age):raise ValueError('Wrong catalog event')
   standard={population_key(int(e.split(':')[2]),e.split(':')[3],c,g,age) for e in standard_events(c)}
   published.update(cat['events']);unlisted.update(standard-set(cat['events']))
  expected_cats={f'{c}:{g}:{age}' for c in ('LCM','SCM') for g in ('F','M') for age in age_groups}
  expected={population_key(int(e.split(':')[2]),e.split(':')[3],c,g,age) for c in ('LCM','SCM') for g in ('F','M') for age in age_groups for e in standard_events(c)} | published
  available={p['key'] for p in populations}
  if available & unlisted:raise ValueError('Population contradicts catalog')
  missing=sorted(expected-available-unlisted);missing_cats=sorted(expected_cats-seen)
  payload={'club_id':CLUB_ID,'scope':'alltime','requested_age_groups':age_groups,'catalogs':catalogs,'coverage':{'complete':not missing and not missing_cats,'missing_events':missing,'missing_catalogs':missing_cats,'unlisted_events':sorted(unlisted)},'populations':populations}
  version=2
 return {'format':'swimrankings-club-rankings','version':version,'sha256':digest(payload),'payload':payload}

def validate_package(package):
 payload=package['payload']
 expected=build_package(payload['populations']) if package.get('version')==1 else build_package(payload['populations'],payload['requested_age_groups'],payload['catalogs']) if package.get('version')==2 else None
 if package!=expected:raise ValueError('Invalid package/digest')


def apply(conn, package, commit=False):
 validate_package(package)
 if conn.autocommit:raise ValueError('Transaction required')
 report={'imported':0,'unchanged':0}
 try:
  from psycopg2.extras import Json
  with conn.cursor() as c:
   c.execute('SELECT pg_advisory_xact_lock(65634002)');c.execute(SCHEMA)
   for p in package['payload']['populations']:
    c.execute('SELECT payload FROM club_ranking_populations WHERE event_key=%s FOR UPDATE',(p['key'],));old=c.fetchone()
    if old and {**old[0],'age_group':old[0].get('age_group','X_X')}=={**p,'age_group':p.get('age_group','X_X')}:report['unchanged']+=1;continue
    if old and (p['captured_at']<=old[0]['captured_at'] or p['total']<old[0]['total']):raise ValueError('Stale or truncated revision requires review')
    if old:
     current={r['athlete_id']:r['time_cs'] for r in p['rows']}
     if any(r['athlete_id'] not in current or current[r['athlete_id']]>r['time_cs'] for r in old[0]['rows']):raise ValueError('Ranking regression requires source correction review')
    c.execute('INSERT INTO club_ranking_populations VALUES(%s,%s,now()) ON CONFLICT(event_key) DO UPDATE SET payload=excluded.payload,imported_at=now()',(p['key'],Json(p)));report['imported']+=1
   c.execute('INSERT INTO club_ranking_imports(sha256,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING',(package['sha256'],Json(package['payload'])))
  conn.commit() if commit else conn.rollback()
  return {**report,'committed':commit,'performances':sum(p['total'] for p in package['payload']['populations']),'coverage':package['payload']['coverage']}
 except BaseException:conn.rollback();raise

def collect(output,cdp,age_groups=AGES):
 from playwright.sync_api import sync_playwright
 from bs4 import BeautifulSoup
 if urlparse(cdp).hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('Loopback browser only')
 output.mkdir(parents=True,exist_ok=True);output.chmod(0o700)
 age_groups=tuple(age_groups)
 if not age_groups or len(set(age_groups))!=len(age_groups) or set(age_groups)-set(AGES):raise ValueError('Invalid requested categories')
 requested=set(age_groups);populations=[];catalogs=[]
 target=output/'rankings.json'
 if target.exists():
  previous=json.loads(target.read_text());validate_package(previous)
  populations=previous['payload']['populations']
  catalogs=previous['payload'].get('catalogs',[])
  requested.update(previous['payload'].get('requested_age_groups',['X_X']))
 def save():
  target.write_bytes(canonical(build_package(populations,requested,catalogs)));target.chmod(0o600)
 with sync_playwright() as pw:
  browser=pw.chromium.connect_over_cdp(cdp);page=next(p for p in browser.contexts[0].pages if 'www.swimrankings.net'==urlparse(p.url).hostname)
  def fetch(url,path,validate):
   if path.exists():
    result=path.read_text();validate(result);return result
   result=page.evaluate('''async url=>{const r=await fetch(url,{credentials:'include'});if(!r.ok)throw Error('Source unavailable');return await r.text()}''',url)
   if 'rankingList' not in result:
    denied=output/'unavailable.html';denied.write_text(result);denied.chmod(0o600)
    raise ValueError(f'Ranking access unavailable at {url}; collection stopped. Restore source access in the browser before resuming.')
   validate(result)
   path.write_text(result);path.chmod(0o600);time.sleep(2.0)
   return result
  for age in age_groups:
   for course in ('LCM','SCM'):
    for gender in ('F','M'):
     prefix=f'{course}-{gender}'+('' if age=='X_X' else f'-{age}')
     url=source_url(course,gender,age);catalog_path=output/f'{prefix}-catalog.html';html=fetch(url,catalog_path,lambda h:parse_catalog(h,url,course,gender,age))
     events=parse_catalog(html,url,course,gender,age)
     cat={'key':f'{course}:{gender}:{age}','course':course,'gender':gender,'age_group':age,'source_url':url,'sha256':hashlib.sha256(html.encode()).hexdigest(),'captured_at':datetime.fromtimestamp(catalog_path.stat().st_mtime,timezone.utc).isoformat(),'events':[population_key(d,st,course,gender,age) for (d,st),_ in events]}
     catalogs=[c for c in catalogs if c['key']!=cat['key']]+[cat];save()
     for (distance,stroke),url in events:
      rid=parse_qs(urlparse(url).query)['rankingClubId'][0];pages=[];rows=[];total=None;built=None
      offset=1
      while total is None or offset<=total:
       u=f'https://www.swimrankings.net/index.php?page=rankingDetail&rankingClubId={rid}&firstPlace={offset}'
       h=fetch(u,output/f'{prefix}-{distance}-{stroke}-{offset}.html',lambda h:parse_page(h,u,course,gender,distance,stroke,age));part=parse_page(h,u,course,gender,distance,stroke,age)
       if total is not None and (part['total']!=total or part['built']!=built):raise ValueError('Source changed during pagination; recollect event')
       total=part['total'];built=part['built']
       if len(part['rows'])!=min(25,total):raise ValueError('Incomplete page')
       existing={r['athlete_id']:r for r in rows}
       for r in part['rows']:
        if r['athlete_id'] in existing and existing[r['athlete_id']]!=r:raise ValueError('Conflicting overlap')
       fresh=[r for r in part['rows'] if r['athlete_id'] not in existing]
       if len(fresh)!=min(25,total-offset+1):raise ValueError('Pagination gap or duplicate')
       rows.extend(fresh);pages.append({'offset':offset,'count':len(fresh),'sha256':part['sha256'],'source_url':u});offset+=25
       print(f'{course} {gender} {age} {distance} {stroke}: {len(rows)}/{total}',flush=True)
      p={'club_id':CLUB_ID,'key':population_key(distance,stroke,course,gender,age),'age_group':age,'course':course,'gender':gender,'distance':distance,'stroke':stroke,'total':total,'built':built,'captured_at':datetime.fromtimestamp(max((output/f'{prefix}-{distance}-{stroke}-{v}.html').stat().st_mtime for v in range(1,total+1,25)),timezone.utc).isoformat(),'pages':pages,'rows':rows}
      validate_population(p);populations=[v for v in populations if v['key']!=p['key']]+[p]
      save()
  browser.close()
 print(json.dumps({'events':len(populations),'performances':sum(p['total'] for p in populations)}))

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 c=sub.add_parser('collect');c.add_argument('--output',type=Path,required=True);c.add_argument('--cdp',default='http://127.0.0.1:9334');c.add_argument('--age-group',action='append',choices=AGES,help='Repeat to select categories; default all official categories')
 a=sub.add_parser('apply');a.add_argument('--package',type=Path,required=True);a.add_argument('--db-config',type=Path,required=True);a.add_argument('--commit',action='store_true')
 args=parser.parse_args()
 if args.command=='collect':collect(args.output,args.cdp,args.age_group or AGES)
 else:
  import psycopg2
  with psycopg2.connect(**json.loads(args.db_config.read_text())) as conn:print(json.dumps(apply(conn,json.loads(args.package.read_text()),args.commit)))
