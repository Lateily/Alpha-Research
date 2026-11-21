import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
let ui;
try {
  const built=await build({entryPoints:['tools/nonprod_workbench/daily-ui/app.jsx'],bundle:true,write:false,platform:'node',format:'esm',
    plugins:[{name:'shared-react',setup(b){b.onResolve({filter:/^(react|lucide-react)$/},args=>({path:pathToFileURL(require.resolve(args.path)).href,external:true}));}}]});
  const text=built.outputFiles[0].text;
  ui=await import('data:text/javascript;base64,'+Buffer.from(text).toString('base64'));
} catch(error) { if(error.message&&!error.message.includes('Could not resolve'))throw new Error(error.message.slice(0,400)); }
const data={schema:'ar.daily-preview.v1',mode:'ISOLATED_READ_ONLY',source:{source_trade_date:'20261119'},
  captured_at:1,original_observed_at:'2026-11-19T20:46:59Z',capabilities:{submit_research:false},
  cards:{library:{results:[],total:0},inputs:{inputs:[]}},shared:{team_jobs:[],common_data:{}},
  task_details:{},macro:{},portfolio:null,acceptance:{code_sha:'a'.repeat(40),local_ci:{passed:125,total:125},local_mutations:{killed:1740,total:1740}},provenance:{human_review:'PENDING'}};
test('all five destinations render without inventing business records',()=>{
  assert.equal(typeof ui?.DailyView,'function');
  for(const route of ['today','research','holdings','macro','tests']) {
    const html=renderToStaticMarkup(React.createElement(ui.DailyView,{route,data,fresh:true,onEvidence:()=>{},navigate:()=>{}}));
    assert.ok(html.length>100);assert.ok(!html.includes('NaN'));assert.ok(!html.includes('undefined'));
  }
});
test('empty holdings are unavailable, not a zero position assertion',()=>{
  assert.equal(typeof ui?.DailyView,'function');
  const html=renderToStaticMarkup(React.createElement(ui.DailyView,{route:'holdings',data,fresh:true}));
  assert.ok(html.includes('持仓数据未接入'));assert.ok(!html.includes('¥0'));
});
test('expired preview cannot offer a metadata download or an execution command',()=>{
  assert.equal(typeof ui?.DailyView,'function');
  const html=renderToStaticMarkup(React.createElement(ui.DailyView,{route:'research',data,fresh:false}));
  assert.ok(!html.includes('提交研究'));assert.ok(!html.includes('运行测试'));
});
test('missing macro keeps the data gap visible',()=>{
  assert.equal(typeof ui?.DailyView,'function');
  const html=renderToStaticMarkup(React.createElement(ui.DailyView,{route:'macro',data,fresh:true}));
  assert.ok(html.includes('宏观数据未接入'));
});
