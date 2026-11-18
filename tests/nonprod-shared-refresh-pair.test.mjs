import assert from 'node:assert/strict';
import test from 'node:test';
import * as shared from '../tools/nonprod_workbench/ui/shared-view.mjs';
test('fast common reads cannot cancel the independent detail failure cooldown',async()=>{
  let now=0,id=0;const timers=new Map(),starts=[];
  const schedule=(fn,delay)=>{timers.set(++id,{fn,at:now+delay});return id;},cancel=key=>timers.delete(key);
  const sleep=delay=>new Promise(resolve=>schedule(resolve,delay));
  const pair=shared.createSharedRefreshPair({read:async()=>{await sleep(100);return {};},apply:()=>{},
    readDetails:async()=>{starts.push(now);await sleep(12400);throw new Error('INVALID_DETAIL');},fail:()=>{},
    cadenceFromStart:true,now:()=>now,schedule,cancel});
  pair.refresh();
  for(;;){const entry=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!entry||entry[1].at>20000)break;
    const [key,timer]=entry;timers.delete(key);now=timer.at;timer.fn();for(let i=0;i<15;i++)await Promise.resolve();}
  pair.stop();assert.equal(starts[0],100);assert.equal(starts[1],17500);
});
test('selected detail verification has its own cadence instead of skipping common cycles',async()=>{
  let now=0,id=0;const timers=new Map(),completed=[];
  const schedule=(fn,delay)=>{timers.set(++id,{fn,at:now+delay});return id;},cancel=key=>timers.delete(key);
  const sleep=delay=>new Promise(resolve=>schedule(resolve,delay));
  const pair=shared.createSharedRefreshPair({read:async()=>{await sleep(12000);return {};},apply:()=>{},
    readDetails:async()=>{await sleep(12400);completed.push(now);},fail:assert.fail,cadenceFromStart:true,now:()=>now,schedule,cancel});
  pair.refresh();
  for(;;){const entry=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!entry||entry[1].at>50000)break;
    const [key,timer]=entry;timers.delete(key);now=timer.at;timer.fn();for(let i=0;i<15;i++)await Promise.resolve();}
  pair.stop();
  assert.ok(completed.length>=3,'detail must not wait for another common completion');
  assert.ok(completed.slice(1).every((value,index)=>value-completed[index]<=15000));
});

test('slow detail work cannot hold the next common read or fake freshness',async()=>{
  assert.equal(typeof shared.createSharedRefreshPair,'function');
  let now=1000,query,release,reads=0,details=0,detailStale=true;
  const timers=[],held=new Promise(resolve=>{release=resolve;});
  const pair=shared.createSharedRefreshPair({read:async()=>{reads++;return {revision:reads};},
    apply:data=>{query=shared.sharedQueryState(query,data,'',now);},
    readDetails:async()=>{details++;await held;detailStale=false;},fail:assert.fail,
    schedule:(fn,delay)=>{timers.push({fn,delay});return 1;},cancel:()=>{}});
  const first=pair.refresh();let completed=false;first.then(()=>{completed=true;});
  for(let i=0;i<10;i++)await Promise.resolve();
  const early=completed;if(!early){release();await first;pair.stop();}
  assert.equal(early,true,'common refresh must settle before held detail work');
  assert.equal(timers.length,1);assert.equal(timers[0].delay,5000);
  now=16001;assert.equal(shared.sharedViewFreshness(query,detailStale,now).downloadsEnabled,false);
  await pair.refresh();assert.equal(reads,2);assert.equal(details,1);assert.equal(query.lastSuccessAt,16001);
  release();await Promise.resolve();await Promise.resolve();
  assert.equal(shared.sharedViewFreshness(query,detailStale,16002).downloadsEnabled,true);
  pair.stop();
});

test('disposed paired reads cannot apply late detail failure or schedule common work',async()=>{
  assert.equal(typeof shared.createSharedRefreshPair,'function');
  let reject,failures=0,applied=0;const held=new Promise((_,no)=>{reject=no;});
  const pair=shared.createSharedRefreshPair({read:async()=>({}),apply:()=>{applied++;},
    readDetails:()=>held,fail:()=>{failures++;},schedule:()=>null,cancel:()=>{}});
  const pending=pair.refresh();for(let i=0;i<10;i++)await Promise.resolve();
  pair.stop();reject(new Error('LATE_DETAIL'));await pending;
  await Promise.resolve();await Promise.resolve();await pair.refresh();
  assert.equal(failures,0);assert.equal(applied,1);
});

test('detail failures stay explicit without disabling future common reads',async()=>{
  assert.equal(typeof shared.createSharedRefreshPair,'function');
  let fail=true,errors=0,reads=0;
  const pair=shared.createSharedRefreshPair({read:async()=>{reads++;return {};},apply:()=>{},
    readDetails:async()=>{if(fail)throw new Error('DETAIL_UNAVAILABLE');},fail:()=>{errors++;},schedule:()=>null,cancel:()=>{}});
  await pair.refresh();await Promise.resolve();await Promise.resolve();assert.equal(errors,1);
  fail=false;await pair.refresh();assert.equal(reads,2);pair.stop();
});
