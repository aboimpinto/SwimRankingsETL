import test from 'node:test';
import assert from 'node:assert/strict';
import {verifyClubPublication} from '../scripts/nrt_verify_clubs.mjs';
function fixture({missingAttribution=false,missingProjection=false,missingCard=false,unresolved=false,emptyOverlay=false}={}){
 const source={query:async()=>({rows:[{id:'1',club_name:'Test Club',club_source:'proof',meet_key:'Meet',relay:false}]})};
 const target={query:async(sql)=>({rows:sql.includes('directory_entity')?(unresolved?[]:[{id:'club',display_name:'Test Club'}]):sql.includes('club_competition')?(missingCard||unresolved?[]:[{club_id:'club',meet_key:'Meet'}]):[{source_result_id:'1',active:!missingAttribution,payload:{club_name:'Test Club',source:'proof'},club_id:missingProjection?null:'club'}]})};
 const request=async(url)=>({ok:true,status:200,json:async()=>url.includes('/competition-results?')?{meet:{key:'Meet'},club:{id:'club'},coverage:{pending:false},total:emptyOverlay?0:1,rows:emptyOverlay?[]:[{}]}:{rows:[{meetKey:'Meet'}],nextOffset:null}});
 return [source,target,[{id:1}],'https://example.test',{request}];
}
test('checks attributed facts, cards and public overlay',async()=>{const r=await verifyClubPublication(...fixture());assert.equal(r.resolved,1);assert.equal(r.publicClubMeets,1);assert.equal(r.requests,2);});
for(const option of ['missingAttribution','missingProjection','missingCard','emptyOverlay'])test(`rejects ${option}`,async()=>{await assert.rejects(verifyClubPublication(...fixture({[option]:true})));});
test('reports unresolved names instead of inventing membership',async()=>{const r=await verifyClubPublication(...fixture({unresolved:true}));assert.equal(r.unresolved,1);assert.equal(r.clubMeets,0);});
