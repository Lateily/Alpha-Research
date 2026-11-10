import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewLabels, validateReviewList, validateReviewDetail, validateCommentReceipt, pendingKey, readPending, savePending } from '../tools/nonprod_workbench/ui/review-portal-view.mjs';

export const context={login:'reed',workspaceId:'11111111-1111-4111-8111-111111111111',codeSha:'b'.repeat(40)};
export const packetHash='a'.repeat(64);
export const base=()=>({...reviewLabels,my_workspace:{login:context.login,workspace_id:context.workspaceId},consumer_code_sha:context.codeSha});
export const detail=()=>({...base(),schema:'ar.human-review-detail.v1',packet_hash:packetHash,grant_hash:'c'.repeat(64),audience:['owner','reed'],annotations:[],packet:{...reviewLabels,schema:'ar.human-review-packet.v1',packet_id:'toy',original_manifest_sha256:'d'.repeat(64),pack_hash:'e'.repeat(64),content_hash:'f'.repeat(64),basis_hash:'1'.repeat(64),source_cutoff_at:'2026-10-04T23:59:59+08:00',daily_source_trade_date:'20261105',source_draft_generated_at:'2026-11-10T01:00:00+08:00',source_producer:'2'.repeat(40),original_source_rights:'UNVERIFIED_PRIVATE_NOT_CHANGED',sample:'<script>not executed</script>',items:[{id:'F1',layer:'F',title:'事实',prompt:'核对口径'}],gaps:[{id:'R1',title:'EPS',status:'NOT_ESTABLISHED',reason:'无依据'}],sources:[{id:'S1',title:'示例',sha256:'3'.repeat(64),kind:'SOURCE_METADATA_NOT_AUTHENTICATED',rights_status:'UNVERIFIED_PRIVATE_SOURCE_BODY_DENIED',published_at:null,captured_at:null,pages:[6],registered_public_url:'https://static.cninfo.com.cn/finalpage/2026-03-31/1225061352.PDF',url_rechecked:false}]}});
export const list=()=>({...base(),schema:'ar.human-review-list.v1',packets:[{packet_hash:packetHash,grant_hash:'c'.repeat(64),manifest_sha256:'d'.repeat(64),packet_id:'toy',source_cutoff_at:detail().packet.source_cutoff_at,daily_source_trade_date:'20261105',source_draft_generated_at:detail().packet.source_draft_generated_at}]});
export const annotation=()=>({packet_hash:packetHash,item_id:'F1',actor:'reed',workspace_id:context.workspaceId,code_sha:context.codeSha,status:'ISSUE',severity:'MAJOR',comment:'口径需复核',human_review:'PENDING',research_approval:false,annotation_id:'review_test',at:1000,event_hash:'4'.repeat(64)});
export const payload=()=>({command_id:'review_test',packet_hash:packetHash,item_id:'F1',expected_workspace_id:context.workspaceId,expected_code_sha:context.codeSha,status:'ISSUE',severity:'MAJOR',comment:'口径需复核'});
test('review contracts bind identity, packet, authority and source permissions',()=>{
  assert.equal(validateReviewList(list(),context).packets.length,1);
  assert.equal(validateReviewDetail(detail(),context,packetHash).packet.sample,'<script>not executed</script>');
  for(const edit of [v=>v.my_workspace.login='other',v=>v.consumer_code_sha='c'.repeat(40),v=>v.raw_source_body_allowed=true,v=>v.packet_hash='0'.repeat(64),v=>v.packet.production_authority=true,v=>v.packet.sources[0].registered_public_url='javascript:alert(1)',v=>v.packet.raw_body='secret',v=>v.annotations=[{...annotation(),research_approval:true}],v=>v.annotations=[{...annotation(),actor:'outsider'}]]){
    const value=detail();edit(value);assert.throws(()=>validateReviewDetail(value,context,packetHash));
  }
});
test('receipt matches complete submitted annotation rather than only command id',()=>{
  const receipt={...reviewLabels,disposition:'APPENDED',annotation:annotation()};
  assert.equal(validateCommentReceipt(receipt,context,payload()).annotation.comment,payload().comment);
  for(const field of ['comment','item_id','status','severity','workspace_id','actor','packet_hash']){
    assert.throws(()=>validateCommentReceipt({...receipt,annotation:{...annotation(),[field]:'wrong'}},context,payload()));
  }
});
test('pending commands are bounded and isolated by actor workspace code and packet',()=>{
  const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
  savePending(storage,context,packetHash,payload());assert.deepEqual(readPending(storage,context,packetHash),payload());
  assert.notEqual(pendingKey(context,packetHash),pendingKey({...context,login:'owner'},packetHash));
  assert.equal(readPending(storage,{...context,codeSha:'c'.repeat(40)},packetHash),null);
  values.set(pendingKey(context,packetHash),JSON.stringify({...payload(),actor:'spoof'}));
  assert.throws(()=>readPending(storage,context,packetHash));
});
