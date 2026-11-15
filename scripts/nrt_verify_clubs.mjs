import assert from 'node:assert/strict';

/** Read-only verification: all attributed race projections, bounded public readers. */
export async function verifyClubPublication(source, target, meets, origin, {sampleLimit=8, request=fetch}={}) {
  assert(Number.isSafeInteger(sampleLimit) && sampleLimit > 0 && sampleLimit <= 100);
  const ids=meets.map(m=>m.id);
  const facts=(await source.query(`SELECT r.id::text,r.club_name,r.club_source,m.meet_id AS meet_key,coalesce(r.is_relay,false) AS relay
    FROM results r JOIN meets m ON m.id=r.meet_id WHERE m.id=ANY($1::int[]) AND nullif(btrim(r.club_name),'') IS NOT NULL ORDER BY r.id`,[ids])).rows;
  const directory=(await target.query("SELECT id,display_name FROM directory_entity WHERE kind='club' AND active")).rows;
  const names=new Map();
  for(const club of directory){const key=club.display_name.trim().toLowerCase();names.set(key,names.has(key)?null:club.id);}
  const actual=(await target.query(`SELECT s.source_result_id::text,a.payload,a.active,c.club_id FROM swimmer_result s
    LEFT JOIN club_attribution a ON a.source_result_id=s.source_result_id
    LEFT JOIN club_race c ON c.result_id=s.id WHERE s.active AND s.source_result_id=ANY($1::bigint[])`,[facts.map(r=>r.id)])).rows;
  const byId=new Map(actual.map(r=>[r.source_result_id,r]));
  const pairs=new Map();let unresolved=0,resolved=0;
  for(const race of facts){
    const saved=byId.get(race.id);
    assert(saved?.active,`Missing club attribution for source race ${race.id}`);
    assert.equal(saved.payload.club_name,race.club_name.trim());
    assert.equal(saved.payload.source,race.club_source?.trim()||null);
    const clubId=names.get(race.club_name.trim().toLowerCase());
    if(!clubId){unresolved++;continue;}
    assert.equal(saved.club_id,clubId,`Missing/wrong club projection for source race ${race.id}`);resolved++;
    const key=JSON.stringify([clubId,race.meet_key]);
    const pair=pairs.get(key)??{clubId,meet:race.meet_key,individuals:0};
    if(!race.relay)pair.individuals++;
    pairs.set(key,pair);
  }
  // Check stored competition cards for every resolved pair, even when public readers are sampled.
  const expected=[...pairs.values()];
  const cards=(await target.query(`SELECT c.club_id,c.meet_key FROM club_competition c
    JOIN jsonb_to_recordset($1::jsonb) AS p("clubId" uuid,meet text) ON c.club_id=p."clubId" AND c.meet_key=p.meet`,[JSON.stringify(expected)])).rows;
  assert.equal(new Set(cards.map(c=>JSON.stringify([c.club_id,c.meet_key]))).size,pairs.size,'Missing published club competition cards');
  const timings=[];
  async function get(path){const start=performance.now();const response=await request(origin+path,{cache:'no-store',signal:AbortSignal.timeout(15000)});const body=await response.json();const ms=Math.round(performance.now()-start);timings.push({path,status:response.status,ms});assert(response.ok,`Club reader HTTP ${response.status}`);assert(ms<=2000,'Club reader exceeded two seconds');return body;}
  // Spread the bounded sample across meets before selecting more clubs from one meet.
  const buckets=new Map();for(const pair of expected){const list=buckets.get(pair.meet)??[];list.push(pair);buckets.set(pair.meet,list);}
  const sample=[];while(sample.length<sampleLimit){let added=false;for(const bucket of buckets.values()){if(bucket.length&&sample.length<sampleLimit){sample.push(bucket.shift());added=true;}}if(!added)break;}
  for(const pair of sample){
    let offset=0,generation;let found=false;
    for(let page=0;page<20;page++){
      const params=new URLSearchParams({season:'0',offset:String(offset)});if(generation)params.set('generation',generation);
      const list=await get(`/api/clubs/${pair.clubId}/competitions?${params}`);
      if(list.rows.some(r=>r.meetKey===pair.meet)){found=true;break;}
      if(list.nextOffset===null)break;
      offset=list.nextOffset;generation=list.generation;
    }
    assert(found,`Public competition card missing: ${pair.meet}`);
    const results=await get(`/api/clubs/${pair.clubId}/competition-results?${new URLSearchParams({meet:pair.meet,showNonStarts:'1'})}`);
    assert.equal(results.meet.key,pair.meet);assert.equal(results.club.id,pair.clubId);
    assert(!results.coverage.pending,'Club result projection still pending');
    assert(results.total>=pair.individuals,'Club overlay omits recorded individual races');
    if(pair.individuals)assert(results.rows.length>0,'Club overlay is empty');
  }
  return {attributed:facts.length,resolved,unresolved,clubMeets:pairs.size,publicClubMeets:sample.length,requests:timings.length,timings};
}
