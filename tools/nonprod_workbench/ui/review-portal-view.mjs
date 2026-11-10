export const reviewLabels={sample_purpose:'WORKFLOW_DEBUG',human_review:'PENDING',source_authenticity:'UNVERIFIED',raw_source_body_allowed:false,external_model_use_allowed:false,u4_authority:false,paper_authority:false,production_authority:false,trading_authority:false};
const hash=/^[a-f0-9]{64}$/,sha=/^[a-f0-9]{40}$/,uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const statuses=['MATCH','ISSUE','NEEDS_SOURCE','OUT_OF_SCOPE'],severities=['NONE','MINOR','MAJOR','BLOCKING'];
function require(value){if(!value)throw new Error('REVIEW_CONTRACT_INVALID');}
function exact(value,keys){require(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('|')===[...keys].sort().join('|'));}
function text(value,max=4000){require(typeof value==='string'&&value.trim().length>0&&value.length<=max&&!/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value));}
function labels(value){for(const [key,want] of Object.entries(reviewLabels))require(value[key]===want);}
function identity(value,context){require(value.my_workspace?.login===context.login&&value.my_workspace?.workspace_id===context.workspaceId&&value.consumer_code_sha===context.codeSha&&uuid.test(context.workspaceId)&&sha.test(context.codeSha));labels(value);}
const common=['my_workspace','consumer_code_sha',...Object.keys(reviewLabels)];
export function validateReviewList(value,context){
  exact(value,['schema','packets',...common]);identity(value,context);require(value.schema==='ar.human-review-list.v1'&&Array.isArray(value.packets)&&value.packets.length<=20);
  const seen=new Set();for(const row of value.packets){exact(row,['packet_hash','grant_hash','manifest_sha256','packet_id','source_cutoff_at','daily_source_trade_date','source_draft_generated_at']);
    for(const key of ['packet_hash','grant_hash','manifest_sha256'])require(hash.test(row[key]));
    require(!seen.has(row.packet_hash));seen.add(row.packet_hash);for(const key of ['packet_id','source_cutoff_at','daily_source_trade_date','source_draft_generated_at'])text(row[key],200);
  }return value;
}
function annotation(row,audience,items,packetHash){
  exact(row,['packet_hash','item_id','actor','workspace_id','code_sha','status','severity','comment','human_review','research_approval','annotation_id','at','event_hash']);
  require(row.packet_hash===packetHash&&audience.includes(row.actor)&&items.includes(row.item_id)&&uuid.test(row.workspace_id)&&sha.test(row.code_sha)&&hash.test(row.event_hash));
  require(row.human_review==='PENDING'&&row.research_approval===false&&statuses.includes(row.status)&&severities.includes(row.severity)&&Number.isFinite(row.at)&&row.at>=0&&row.at<=253402300799);
  text(row.comment);text(row.annotation_id,200);
}
export function validateReviewDetail(value,context,packetHash){
  exact(value,['schema','packet_hash','packet','grant_hash','audience','annotations',...common]);identity(value,context);
  require(value.schema==='ar.human-review-detail.v1'&&value.packet_hash===packetHash&&hash.test(packetHash)&&hash.test(value.grant_hash));
  require(Array.isArray(value.audience)&&value.audience.length>=1&&value.audience.length<=2&&new Set(value.audience).size===value.audience.length&&value.audience.includes(context.login));
  const p=value.packet;exact(p,['schema','packet_id','sample','items','sources','gaps','original_manifest_sha256','pack_hash','content_hash','basis_hash','source_cutoff_at','daily_source_trade_date','source_draft_generated_at','source_producer','original_source_rights',...Object.keys(reviewLabels)]);labels(p);
  require(p.schema==='ar.human-review-packet.v1'&&p.original_source_rights==='UNVERIFIED_PRIVATE_NOT_CHANGED'&&sha.test(p.source_producer));
  for(const key of ['original_manifest_sha256','pack_hash','content_hash','basis_hash'])require(hash.test(p[key]));
  text(p.sample,65536);require(!/(?:\/Users\/|\/private\/|file:\/\/|[A-Z]:\\)/.test(p.sample));
  for(const key of ['packet_id','source_cutoff_at','daily_source_trade_date','source_draft_generated_at'])text(p[key],200);
  require(Array.isArray(p.items)&&p.items.length>=1&&p.items.length<=100&&new Set(p.items.map(r=>r.id)).size===p.items.length);
  for(const item of p.items){exact(item,['id','layer','title','prompt']);for(const key of Object.keys(item))text(item[key],2000);}
  require(Array.isArray(p.gaps)&&p.gaps.length<=32);for(const gap of p.gaps){exact(gap,['id','title','status','reason']);for(const key of Object.keys(gap))text(gap[key]);}
  require(Array.isArray(p.sources)&&p.sources.length<=32);for(const source of p.sources){exact(source,['id','title','sha256','kind','rights_status','published_at','captured_at','pages','registered_public_url','url_rechecked']);
    text(source.id,200);text(source.title,1000);require(hash.test(source.sha256)&&source.kind==='SOURCE_METADATA_NOT_AUTHENTICATED'&&source.rights_status==='UNVERIFIED_PRIVATE_SOURCE_BODY_DENIED'&&source.url_rechecked===false);
    for(const key of ['published_at','captured_at'])if(source[key]!==null)text(source[key],100);
    require(source.pages===null||(Array.isArray(source.pages)&&source.pages.length<=100&&source.pages.every(n=>Number.isSafeInteger(n)&&n>0)));
    // governance-mutation: REVIEW_CLIENT_SOURCE_URL
    require(source.registered_public_url===null||/^https:\/\/static\.cninfo\.com\.cn\/finalpage\/\d{4}-\d{2}-\d{2}\/\d+\.PDF$/.test(source.registered_public_url));
  }
  require(Array.isArray(value.annotations)&&value.annotations.length<=1000&&new Set(value.annotations.map(r=>r.annotation_id)).size===value.annotations.length);
  for(const row of value.annotations)annotation(row,value.audience,p.items.map(r=>r.id),packetHash);return value;
}
function validatePayload(body,context,packetHash){
  exact(body,['command_id','packet_hash','item_id','expected_workspace_id','expected_code_sha','status','severity','comment']);
  require(body.packet_hash===packetHash&&body.expected_workspace_id===context.workspaceId&&body.expected_code_sha===context.codeSha&&/^[A-Za-z0-9_-]{1,200}$/.test(body.command_id)&&statuses.includes(body.status)&&severities.includes(body.severity));text(body.item_id,100);text(body.comment);return body;
}
export function validateCommentReceipt(value,context,body){
  exact(value,['disposition','annotation',...Object.keys(reviewLabels)]);labels(value);require(['APPENDED','IDEMPOTENT'].includes(value.disposition));
  annotation(value.annotation,[context.login],[body.item_id],body.packet_hash);const row=value.annotation;
  // governance-mutation: REVIEW_CLIENT_RECEIPT
  require(row.annotation_id===body.command_id&&row.workspace_id===context.workspaceId&&row.code_sha===context.codeSha&&row.comment===body.comment&&row.status===body.status&&row.severity===body.severity);return value;
}
export const pendingKey=(context,packetHash)=>'ar.review.pending.v1:'+JSON.stringify([context.login,context.workspaceId,context.codeSha,packetHash]);
export function readPending(storage,context,packetHash){const raw=storage.getItem(pendingKey(context,packetHash));if(raw===null)return null;require(raw.length<=18000);return validatePayload(JSON.parse(raw),context,packetHash);}
export function savePending(storage,context,packetHash,body){validatePayload(body,context,packetHash);const key=pendingKey(context,packetHash);storage.setItem(key,JSON.stringify(body));require(storage.getItem(key)===JSON.stringify(body));}
export function clearPending(storage,context,packetHash){storage.removeItem(pendingKey(context,packetHash));}
export function canSubmitReview({stale,verifiedKey,activeKey,requestKey,posting,packet}){
  // governance-mutation: REVIEW_CLIENT_CONTEXT
  return !stale&&verifiedKey===requestKey&&activeKey===requestKey&&!posting&&!!packet;
}
export function definitiveReviewRejection(error){
  // governance-mutation: REVIEW_CLIENT_DEFINITIVE_REJECTION
  return [400,403,404,413,415,422,429].includes(error.status);
}
