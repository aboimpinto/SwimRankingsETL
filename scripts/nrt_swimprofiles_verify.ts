import '../../scripts/env';
import {required} from '../../scripts/env';
import {Pool} from 'pg';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {referenceBestsSql} from '../../scripts/fixtures/incremental-import';
const source=new Pool({connectionString:required('SWIMRANKINGS_DATABASE_URL'),max:1,options:'-c default_transaction_read_only=on -c statement_timeout=30000'});
const target=new Pool({connectionString:required('DATABASE_WRITE_URL'),max:1,options:'-c default_transaction_read_only=on -c statement_timeout=30000'});
const queryTimings:any[]=[];
for(const [database,pool] of [['source',source],['application',target]] as const){
 const query=pool.query.bind(pool) as any;
 (pool as any).query=async(statement:string,values?:unknown[])=>{
  const began=performance.now();let failed=false;
  try{return await query(statement,values);}catch(error){failed=true;throw error;}
  finally{const timing={database,statement:statement.split('\n')[0].slice(0,160),ms:Math.round((performance.now()-began)*1000)/1000,failed};queryTimings.push(timing);console.error(JSON.stringify({auditQuery:timing}));}
 };
}
const apiTimings:any[]=[];
const started=performance.now();
const meets=JSON.parse(process.env.LIVE_VERIFY_MEETS ?? '[]');
assert(meets.length>0 && meets.length<=500 && meets.every((m:any)=>Number.isSafeInteger(m.id)&&m.id>0&&(m.results===undefined||(Number.isSafeInteger(m.results)&&m.results>=0))));
const saved:any[]=[];const rankingCandidates=new Set<string>();let factCount=0,splitCount=0,reactionCount=0;
try{
 for (const meet of meets) {
 const facts=(await source.query(`SELECT r.id::text,(r.time_seconds*100)::integer cents,r.points_fina,coalesce(r.status,'') status,e.distance,e.stroke,coalesce(nullif(e.pool_length,0),nullif(m.pool_length,0)) course,m.meet_id,m.name meet_name,m.city meet_city,m.country_code meet_country,r.result_date::text race_date,r.reaction_time,r.heat,r.lane,r.event_round,r.is_relay,r.relay_count,r.points_rudolph,e.gender category FROM results r JOIN events e ON e.id=r.event_id JOIN meets m ON m.id=r.meet_id WHERE m.id=$1 ORDER BY r.id`,[meet.id])).rows;
 if(meet.results!==undefined) assert.equal(facts.length,meet.results);
 factCount+=facts.length;
 const metadata=(await source.query('SELECT meet_id FROM meets WHERE id=$1',[meet.id])).rows;assert.equal(metadata.length,1);
 const meetSaved=(await target.query('SELECT source_result_id::text,athlete_id,time_hundredths,points,coalesce(status,\'\') status,distance,stroke,course,category,race_date::text,payload FROM swimmer_result WHERE meet_key=$1 AND active ORDER BY source_result_id',[metadata[0].meet_id])).rows;
 const splitRows=(await source.query('SELECT s.result_id::text,s.distance,s.time_seconds::text,s.split_order FROM splits s JOIN results r ON r.id=s.result_id WHERE r.meet_id=$1 ORDER BY r.id,s.split_order,s.distance,s.id',[meet.id])).rows;
 const byRace=new Map<string,any[]>();for(const split of splitRows){const list=byRace.get(split.result_id)??[];list.push({distance:split.distance,time_seconds:split.time_seconds,order:split.split_order});byRace.set(split.result_id,list);}splitCount+=splitRows.length;
 assert.equal(meetSaved.length,facts.length);
 for(let i=0;i<facts.length;i++){
  const a=facts[i],b=meetSaved[i];assert.equal(a.id,b.source_result_id);assert.equal(a.cents===null?null:Number(a.cents),b.time_hundredths);assert.equal(a.points_fina===null?null:Number(a.points_fina),b.points);for(const k of ['status','distance','stroke','course','category','race_date'])assert.equal(a[k],b[k]);
  assert.equal(b.payload.date,a.race_date);assert.equal(b.payload.reaction_time,a.reaction_time);if(a.reaction_time!==null)reactionCount++;
  for(const k of ['heat','lane','is_relay','relay_count','points_rudolph'])assert.equal(b.payload[k],a[k]);
  assert.equal(b.payload.round,a.event_round);assert.deepEqual(b.payload.meet,{key:a.meet_id,name:a.meet_name,city:a.meet_city,country:a.meet_country});
  assert.deepEqual(b.payload.splits,byRace.get(a.id)??[]);
 }
 saved.push(...meetSaved);
 // Facts and bests cover every accepted athlete. Only leaderboard selection is sampled.
 for(const id of [...new Set<string>(meetSaved.map(r=>r.athlete_id))].slice(0,25)) rankingCandidates.add(id);
 }
 const athletes=[...new Set(saved.map(r=>r.athlete_id))];
 const expected=referenceBestsSql.replace('WHERE a.active','WHERE r.athlete_id=ANY($1::uuid[]) AND a.active');
 const differences=(await target.query(`WITH expected AS (${expected}), actual AS (SELECT * FROM swimmer_best WHERE athlete_id=ANY($1::uuid[])) SELECT count(*)::int n FROM ((SELECT * FROM actual EXCEPT SELECT * FROM expected) UNION ALL (SELECT * FROM expected EXCEPT SELECT * FROM actual)) d`,[athletes])).rows[0].n;
 assert.equal(differences,0);
 const publication=(await target.query('SELECT generation::text FROM swimmer_publication WHERE singleton')).rows[0].generation;
 if(process.env.LIVE_VERIFY_PUBLICATION) assert.equal(publication,process.env.LIVE_VERIFY_PUBLICATION);
 const choices:any[]=[];
 const candidates=[...rankingCandidates];
 for(let offset=0;offset<candidates.length;offset+=250){
  choices.push(...(await target.query(`SELECT DISTINCT group_key,split_part(group_key,'|',4) scope FROM swimmer_ranking_entry WHERE athlete_id=ANY($1::uuid[])`,[candidates.slice(offset,offset+250)])).rows);
 }
 const groups=(await target.query(`WITH choices AS (SELECT DISTINCT group_key,scope FROM jsonb_to_recordset($1::jsonb) AS x(group_key text,scope text)), ranked AS (SELECT *,row_number() OVER(PARTITION BY scope ORDER BY group_key) n FROM choices) SELECT group_key,scope FROM ranked WHERE n<=8 ORDER BY scope,group_key`,[JSON.stringify(choices)])).rows;
 let checked=0,ownChecked=0;
 for(const {group_key} of groups){
  const rows=(await target.query('SELECT athlete_id,time_hundredths,rank() OVER(ORDER BY time_hundredths)::int position FROM swimmer_ranking_entry WHERE group_key=$1 ORDER BY time_hundredths,athlete_id',[group_key])).rows;
  const own=rows.find(r=>athletes.includes(r.athlete_id));assert(own);
  const params=new URLSearchParams({group:group_key,athlete:own.athlete_id});
  const apiStarted=performance.now();
  const response=await fetch((process.env.LIVE_VERIFY_ORIGIN ?? 'http://127.0.0.1:4340')+'/api/rankings?'+params,{cache:'no-store',signal:AbortSignal.timeout(15000)});assert(response.ok);const data=await response.json();apiTimings.push({endpoint:'/api/rankings',ms:Math.round((performance.now()-apiStarted)*1000)/1000,status:response.status});assert(performance.now()-apiStarted<=2000,'Ranking request exceeded 2 seconds');assert.equal(data.publication,publication);assert.equal(Number(data.population),rows.length);
  assert.equal(data.swimmer.athlete_id,own.athlete_id);assert.equal(Number(data.swimmer.rank),own.position);assert.equal(Number(data.swimmer.time_hundredths),Number(own.time_hundredths));ownChecked++;
  const top=rows.filter(r=>r.position<=10).slice(0,50);assert.equal(data.entries.length,top.length);
  top.forEach((r,i)=>{assert.equal(data.entries[i].athlete_id,r.athlete_id);assert.equal(Number(data.entries[i].rank),r.position);checked++});
 }
 const profileIds=athletes.slice(0,10);
 const profiles=(await target.query('SELECT id,slug FROM directory_entity WHERE id=ANY($1::uuid[]) AND active AND kind=\'swimmer\'',[profileIds])).rows;
 assert.equal(profiles.length,profileIds.length);
 let affectedProfileRequests=0;
 for(const profile of profiles){
  const season=new Date().getUTCFullYear()+(new Date().getUTCMonth()>=8?1:0);
  for(const path of [`/swimmers/${profile.slug}`,`/api/swimmers/${profile.id}`,`/api/swimmers/${profile.id}?season=${season}`,`/api/swimmers/${profile.id}/results`]){
   const begin=performance.now();const response=await fetch((process.env.LIVE_VERIFY_ORIGIN??'http://127.0.0.1:4340')+path,{cache:'no-store',signal:AbortSignal.timeout(15000)});const body=await response.text();
   const ms=Math.round(performance.now()-begin);apiTimings.push({endpoint:path,ms,status:response.status});assert(response.ok);assert(ms<=2000,'Affected profile request exceeded 2 seconds');
   if(path.startsWith('/swimmers/')){assert(!body.includes('Profile temporarily unavailable'));assert(body.includes('Results archive'));}
   else {const data=JSON.parse(body);if(path.endsWith('/results'))assert(Array.isArray(data.results));else{assert.equal(data.profile.id,profile.id);assert.equal(String(data.publication),String(publication));assert(Array.isArray(data.profile.bests));assert(Array.isArray(data.rankings));}}
   affectedProfileRequests++;
  }
 }
 const report={status:'passed',affectedProfiles:profiles.length,affectedProfileRequests,publication,sourceMeetIds:meets.map((m:any)=>m.id),facts:factCount,splits:splitCount,reactions:reactionCount,verifiedRaceDetails:true,athletes:athletes.length,rankingCandidateAthletes:candidates.length,bestDifferences:differences,groups:groups.length,scopes:[...new Set(groups.map(g=>g.scope))],checked,ownChecked,mismatches:0,queryTimings,apiTimings,ms:Math.round(performance.now()-started)};
 console.log(JSON.stringify(report));
}catch(error){console.error(JSON.stringify({status:'failed',queryTimings,apiTimings,ms:Math.round(performance.now()-started)}));throw error;}finally{await source.end();await target.end();}
