import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mapLimit} from '../scripts/nrt_verify_concurrency.mjs';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
test('bounds active work, covers every item once and preserves result order', async () => {
  let active=0,peak=0;const seen=[];
  const results=await mapLimit([3,1,4,2,5],2,async(value,index)=>{
    active++;peak=Math.max(peak,active);seen.push(index);await delay(value*3);active--;return value*2;
  });
  assert.equal(peak,2);assert.equal(active,0);assert.deepEqual(seen.sort(),[0,1,2,3,4]);assert.deepEqual(results,[6,2,8,4,10]);
});
test('failure stops new work and drains already running checks before rejecting', async()=>{
  let active=0;const started=[];const expected=new Error('HTTP check failed');
  await assert.rejects(mapLimit([0,1,2,3],2,async value=>{
    started.push(value);active++;
    try {await delay(value===0?5:25);if(value===0)throw expected;}
    finally{active--;}
  }), error=>error===expected);
  assert.deepEqual(started,[0,1]);assert.equal(active,0);
});
test('invalid limits fail before invoking work and empty input succeeds',async()=>{
  for(const limit of [0,-1,1.5,9])await assert.rejects(mapLimit([1],limit,()=>assert.fail()));
  assert.deepEqual(await mapLimit([],2,()=>assert.fail()),[]);
});
