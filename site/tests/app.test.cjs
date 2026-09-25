'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const api = require('../app.js');
function entry(id, system = 'a', overrides = {}) {
 return {run:{run_id:id, task_id:'task', task_version:'1', status:'complete', validation_status:'valid', run_kind:'publication', completed_at:'2026-09-22T00:00:00Z'},system:{system_id:system, evaluated_system_id:system, quality_key:'q',cost_key:'c',latency_key:'l',key_fields:{quality:{cohort:'q'},cost:{pricing_version:'v1'},latency:{concurrency:1}},rankability:Object.fromEntries(['quality','cost','latency'].map(f=>[f,{eligible:true,reason:null}])),...overrides}};
}
test('duplicates pick latest timestamp then greatest run ID and remain explicitly selectable',()=>{
 const a=entry('a'), b=entry('b'), old=entry('z'); old.run.completed_at='2025-01-01T00:00:00Z';
 assert.deepEqual(api.defaults([old,b,a]),[b]);
 const url=api.selectionQuery('task / 1','q',[api.token(old)],api.token(old),false);
 assert.deepEqual(api.exactSelection([a,b,old],url),[api.token(old)]);
 assert.deepEqual(api.exactSelection([a,b],''),[api.token(b)]);
 assert.deepEqual(api.exactSelection([a,b],api.selectionQuery('task','q',[],'',false)),[]);
 const microOld=entry('micro-z'),microNew=entry('micro-a');microOld.run.completed_at='2026-09-22T00:00:00.000001Z';microNew.run.completed_at='2026-09-22T00:00:00.000002Z';
 assert.deepEqual(api.defaults([microOld,microNew]),[microNew]);
});
test('independent families and exact field paths gate deltas',()=>{
 const a=entry('a'),b=entry('b','b',{cost_key:'c2',key_fields:{cost:{pricing_version:'v2'}}});
 assert.equal(api.compatibility(a,b,'quality').eligible,true);
 assert.equal(api.compatibility(a,b,'latency').eligible,true);
 assert.match(api.compatibility(a,b,'cost').reason,/pricing_version/);
 b.system.rankability.cost={eligible:false,reason:'incomplete_cost_coverage'};
 assert.match(api.compatibility(a,b,'cost').reason,/incomplete_cost_coverage/);
 b.run.status='incomplete';
 for(const f of ['quality','cost','latency']) assert.equal(api.compatibility(a,b,f).eligible,false);
 b.run.status='complete';b.run.validation_status='invalid';assert.equal(api.compatibility(a,b,'quality').eligible,false);
});
test('case alignment supports three systems, errors, missing cost/score and all filters',()=>{
 const entries=['a','b','c'].map(s=>entry(s,s));
 const predictions=new Map(entries.map(e=>[e.run.run_id,[{public_case_id:'public-1',evaluated_system_id:e.system.evaluated_system_id,ground_truth:true,source_label:'harmful',decision:e.run.run_id==='c'?null:e.run.run_id==='a',error:e.run.run_id==='c'?'timeout':null,score:null,cost_usd:null}]]));
 const rows=api.caseRows(entries,predictions);assert.equal(rows.length,1);assert.equal(rows[0].rows.size,3);assert.equal(rows[0].disagreement,true);
 for(const filter of ['all','disagreement','error','correct','incorrect']) assert.equal(api.filterCases(rows,'harmful',filter,'score').length,1);
 assert.equal(api.filterCases(rows,'benign','all','cost_usd').length,0);
 assert.equal(api.format(null,'money'),'Unavailable');assert.equal(api.format(0,'money'),'$0.0000');
 assert.equal(api.format(0.000021,'money'),'$0.000021');
 assert.deepEqual(api.knownCost([{evaluated_system_id:'a',cost_usd:0.2},{evaluated_system_id:'a',cost_usd:null},{evaluated_system_id:'b',cost_usd:0.5}],'a'),{usd:0.2,count:1,total:2});
 predictions.get('a').push(predictions.get('a')[0]);assert.throws(()=>api.caseRows(entries,predictions),/Duplicate/);
});
test('artifact URLs stay inside public bundles',()=>{
 const base='https://example.org/results/published/';
 assert.equal(api.artifactUrl(base,'runs/a/aggregate.json'),base+'runs/a/aggregate.json');
 for(const path of ['https://evil.test/x','../preview/x','runs/../aggregate.json','runs/a/raw.json','runs/a/manifest.json?x']) assert.throws(()=>api.artifactUrl(base,path));
});
// A deliberately small DOM harness runs the actual asynchronous rendering code,
// checks fetch destinations and fails if unsafe HTML injection is attempted.
const fs=require('node:fs'), vm=require('node:vm');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this._value='';this.textContent='';this.hidden=false;this.handlers={};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;this._value='';}
 get options(){return this.children.filter(c=>c.tag==='option');}
 get value(){return this._value || (this.tag==='select' ? this.options[0]?.value || '' : '');}
 set value(v){this._value=v;}
 addEventListener(name,fn){this.handlers[name]=fn;}
 set innerHTML(v){throw new Error('Unsafe HTML injection');}
}
async function page(index, search='', artifacts={}){
 const ids=['subtitle','status','controls','task','cohort','choices','reference','systems','metadata','compatibility','explorer','label','filter','sort','case-count','cases'];
 const nodes=Object.fromEntries(ids.map(id=>[id,new Element(['task','cohort','reference','label','filter','sort'].includes(id)?'select':'div')]));
 nodes.filter.value='all';nodes.sort.value='disagreement';nodes.controls.hidden=true;
 const calls=[], history={replaceState(_a,_b,url){this.url=url;}};
 const context={document:{querySelector:s=>nodes[s.slice(1)],createElement:tag=>new Element(tag)},location:{href:'https://example.test/site/index.html',search},history,URL,URLSearchParams,fetch:async url=>{calls.push(String(url));const value=String(url).endsWith('index.json')?index:artifacts[String(url).split('/').slice(-2).join('/')];return {ok:value!==undefined,status:value===undefined?404:200,json:async()=>value,text:async()=>value};}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../app.js'),'utf8'),context);
 for(let i=0;i<15;i++) await new Promise(resolve=>setImmediate(resolve));
 return {nodes,calls,history};
}
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
test('empty index renders without selecting or fetching artifacts',async()=>{
 const p=await page({schema_version:'1.0.0',runs:[]});assert.match(text(p.nodes.status),/No published results/);assert.equal(p.calls.length,1);assert.equal(p.nodes.controls.hidden,true);assert.equal(p.history.url,undefined);
});
test('preview invalid summaries fetch no unsafe artifacts',async()=>{
 const p=await page({schema_version:'1.0.0',runs:[{run_id:'invalid',status:'incomplete',validation_status:'invalid',rule_ids:['missing_coverage']}]},'?preview=1');
 assert.match(p.calls[0],/results\/preview\/index.json/);assert.equal(p.calls.length,1);assert.match(text(p.nodes.status),/incomplete.*invalid.*missing_coverage/);
});
test('actual summary and case DOM renders three systems and inert hostile labels',async()=>{
 const entries=['a','b','c'].map(id=>entry(id,id));const artifacts={};
 entries[2].system.cost_key='different-cost';entries[2].system.key_fields.cost={pricing_version:'v2'};
 for(const e of entries){e.system.identity={display_name:'<img onerror=attack()>',requested_model_id:e.system.system_id,snapshot_status:'unavailable'};e.run.systems=[e.system];e.run.aggregate_uri=`runs/${e.run.run_id}/aggregate.json`;e.run.manifest_uri=`runs/${e.run.run_id}/manifest.json`;e.run.predictions_uri=`runs/${e.run.run_id}/predictions.jsonl`;
 artifacts[`${e.run.run_id}/aggregate.json`]={systems:[{evaluated_system_id:e.system.evaluated_system_id,f1:.5,total_cost_usd:null}]};artifacts[`${e.run.run_id}/manifest.json`]={dataset:{revision:'pinned'},sample_count:1,working_tree_state:'clean'};
 artifacts[`${e.run.run_id}/predictions.jsonl`]=JSON.stringify({public_case_id:'public-1',evaluated_system_id:e.system.evaluated_system_id,source_label:'harmful',ground_truth:true,decision:e.run.run_id==='c'?null:true,error:e.run.run_id==='c'?'timeout':null,score:null,cost_usd:null,cost_status:'unavailable'});}
 const p=await page({schema_version:'1.0.0',runs:entries.map(e=>e.run)},'',artifacts);
 assert.doesNotMatch(text(p.nodes.status),/unavailable/i);assert.match(text(p.nodes.systems),/F1/);assert.match(text(p.nodes.systems),/<img onerror=attack\(\)>/);assert.match(text(p.nodes.systems),/Unavailable/);assert.match(text(p.nodes.cases),/ERROR: timeout/);assert.match(text(p.nodes.metadata),/pinned/);assert.match(text(p.nodes.compatibility),/pricing_version/);assert.equal(new URLSearchParams(p.history.url).getAll('result').length,3);
 p.nodes.reference.value=api.token(entries[0]);p.nodes.reference.onchange();for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));assert.match(text(p.nodes.systems),/Δ/);
});
test('partial cost displays the known subtotal without ranking it as a total',async()=>{
 const e=entry('partial','partial');e.run.systems=[e.system];e.system.rankability.cost={eligible:false,reason:'incomplete_cost_coverage'};
 e.run.aggregate_uri='runs/partial/aggregate.json';e.run.predictions_uri='runs/partial/predictions.jsonl';
 const artifacts={'partial/aggregate.json':{systems:[{evaluated_system_id:'partial',attempted:2,total_cost_usd:null,cost_per_1000_examples_usd:null,cost_known_count:1,cost_coverage:.5}]},
 'partial/predictions.jsonl':[{public_case_id:'case-1',evaluated_system_id:'partial',ground_truth:true,source_label:'harmful',decision:true,error:null,cost_usd:.2342294},{public_case_id:'case-2',evaluated_system_id:'partial',ground_truth:true,source_label:'harmful',decision:null,error:'timeout',cost_usd:null}].map(JSON.stringify).join('\n')};
 const p=await page({schema_version:'1.0.0',runs:[e.run]},'',artifacts);
 assert.match(text(p.nodes.systems),/≥\$0\.2342/);assert.match(text(p.nodes.systems),/Known 1\/2 cases; excludes 1 unknown cost/);
 assert.doesNotMatch(text(p.nodes.systems),/Rank/);
});
test('rankings need an explicit reference and entire selected family compatibility',()=>{
 const entries=[entry('a'),entry('b','b'),entry('c','c')],metrics=[{f1:.8,total_cost_usd:1},{f1:.9,total_cost_usd:3},{f1:.9,total_cost_usd:2}];
 assert.equal(api.metricRank(entries,metrics,0,-1,'quality','f1'),null);
 assert.equal(api.metricRank(entries,metrics,1,0,'quality','f1'),1);
 assert.equal(api.metricRank(entries,metrics,0,0,'quality','f1'),3);
 assert.equal(api.metricRank(entries,metrics,0,0,'cost','total_cost_usd'),1);
 entries[2].system.cost_key='different';
 assert.equal(api.metricRank(entries,metrics,0,0,'cost','total_cost_usd'),null);
 assert.equal(api.metricRank(entries,metrics,1,0,'quality','f1'),1);
});
