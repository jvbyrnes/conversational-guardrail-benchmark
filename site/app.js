/* The publisher owns metrics and eligibility. This view only compares declared keys. */
'use strict';
const families = ['quality', 'cost', 'latency'];
const token = entry => JSON.stringify([entry.run.run_id, entry.system.evaluated_system_id]);
const taskKey = run => `${run.task_id} / ${run.task_version || 'unavailable'}`;
const compareText = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const timestampKey = value => {
  const match = /^(.*:\d\d)(?:\.(\d+))?Z$/.exec(value || '');
  return match ? `${match[1]}.${(match[2] || '').padEnd(9, '0').slice(0, 9)}Z` : null;
};
const flatten = index => index.runs.flatMap(run => (run.systems || []).map(system => ({run, system})));
function defaults(entries) {
  const chosen = new Map();
  for (const entry of entries) {
    if (entry.run.status !== 'complete' || entry.run.validation_status !== 'valid' || entry.run.run_kind !== 'publication') continue;
    const key = JSON.stringify([entry.system.quality_key, entry.system.evaluated_system_id]);
    const previous = chosen.get(key);
    const timestamp = timestampKey(entry.run.completed_at), previousTime = previous ? timestampKey(previous.run.completed_at) : null;
    if (!timestamp) continue;
    if (!previous || timestamp > previousTime ||
      (timestamp === previousTime && compareText(entry.run.run_id, previous.run.run_id) > 0)) chosen.set(key, entry);
  }
  return [...chosen.values()];
}
function differingFields(a, b, prefix = '') {
  if (JSON.stringify(a) === JSON.stringify(b)) return [];
  if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b))
    return [...new Set([...Object.keys(a), ...Object.keys(b)])].sort().flatMap(k => differingFields(a[k], b[k], prefix ? `${prefix}.${k}` : k));
  return [prefix];
}
function compatibility(a, b, family) {
  for (const entry of [a, b]) {
    if (entry.run.status !== 'complete' || entry.run.validation_status !== 'valid') return {eligible: false, reason: `${entry.run.run_id}: ${entry.run.status} / ${entry.run.validation_status}`};
    const state = entry.system.rankability?.[family];
    if (!state?.eligible) return {eligible: false, reason: state?.reason || 'Eligibility unavailable'};
  }
  const key = `${family}_key`;
  if (!a.system[key] || !b.system[key]) return {eligible: false, reason: `${key} unavailable`};
  if (a.system[key] !== b.system[key]) {
    const fields = differingFields(a.system.key_fields?.[family], b.system.key_fields?.[family]);
    return {eligible: false, reason: `Different ${fields.filter(Boolean).join(', ') || key}`};
  }
  return {eligible: true, reason: 'Comparable'};
}
function exactSelection(entries, search) {
  const params = new URLSearchParams(search);
  if (!params.has('result')) return defaults(entries).map(token);
  return params.getAll('result').filter(t => entries.some(e => token(e) === t));
}
function selectionQuery(task, cohort, selected, reference, preview) {
  const params = new URLSearchParams();
  if (preview) params.set('preview', '1');
  params.set('task', task); params.set('cohort', cohort);
  selected.forEach(t => params.append('result', t));
  if (!selected.length) params.append('result', '');
  if (reference) params.set('reference', reference);
  return `?${params}`;
}
function caseRows(entries, predictions) {
  const cases = new Map();
  entries.slice(0, 4).forEach(entry => {
    for (const row of predictions.get(entry.run.run_id) || []) {
      if (row.evaluated_system_id !== entry.system.evaluated_system_id) continue;
      const item = cases.get(row.public_case_id) || {id: row.public_case_id, ground_truth: row.ground_truth, source_label: row.source_label, rows: new Map()};
      if (item.rows.has(token(entry))) throw new Error('Duplicate public prediction identity');
      item.rows.set(token(entry), row); cases.set(item.id, item);
    }
  });
  return [...cases.values()].map(item => ({...item, disagreement: new Set([...item.rows.values()].filter(r => !r.error && r.decision != null).map(r => r.decision)).size > 1}));
}
function knownCost(rows, evaluatedSystemId) {
  const own = (rows || []).filter(row => row.evaluated_system_id === evaluatedSystemId);
  const known = own.filter(row => row.cost_usd != null && Number.isFinite(row.cost_usd));
  return {usd: known.reduce((sum, row) => sum + row.cost_usd, 0), count: known.length, total: own.length};
}
function filterCases(rows, label, filter, sort) {
  const peak = item => Math.max(-Infinity, ...[...item.rows.values()].map(r => Number.isFinite(r[sort]) ? r[sort] : -Infinity));
  return rows.filter(item => (!label || item.source_label === label) && (filter === 'all' ||
    (filter === 'disagreement' && item.disagreement) || [...item.rows.values()].some(r => filter === 'error' ? Boolean(r.error) :
      !r.error && r.decision != null && (filter === 'correct' ? r.decision === r.ground_truth : filter === 'incorrect' && r.decision !== r.ground_truth))))
    .sort((a,b) => (sort === 'disagreement' ? Number(b.disagreement) - Number(a.disagreement) : peak(b) - peak(a)) || compareText(a.id,b.id));
}
function metricRank(entries, metrics, index, referenceIndex, family, key) {
  if (referenceIndex < 0 || entries.length < 2 ||
      !entries.every(e => compatibility(e, entries[referenceIndex], family).eligible) ||
      !metrics.every(m => Number.isFinite(m[key]))) return null;
  const lowerIsBetter = family !== 'quality' || key === 'errors';
  const value = metrics[index][key];
  return 1 + metrics.filter(m => lowerIsBetter ? m[key] < value : m[key] > value).length;
}
const format = (value, kind = 'number') => value == null || !Number.isFinite(value) ? 'Unavailable' : kind === 'percent' ? `${(value*100).toFixed(1)}%` : kind === 'money' ? `$${value.toFixed(value !== 0 && Math.abs(value) < 0.001 ? 6 : 4)}` : String(Number(value.toFixed(2)));
function artifactUrl(base, path) {
  if (typeof path !== 'string' || !/^runs\/[A-Za-z0-9_.-]+\/(manifest\.json|aggregate\.json|predictions\.jsonl|cohort\.json|validation-report\.json)$/.test(path) || path.includes('..')) throw new Error('Unsafe artifact location');
  return new URL(path, base).href;
}
const api = {defaults, flatten, token, compatibility, differingFields, exactSelection, selectionQuery, caseRows, knownCost, filterCases, metricRank, format, artifactUrl};
if (typeof module !== 'undefined') module.exports = api;
if (typeof document !== 'undefined') boot().catch(error => { document.querySelector('#status').textContent = `Results unavailable: ${error.message}`; });
async function boot() {
  const $ = selector => document.querySelector(selector);
  const el = (tag, text, className) => {const node=document.createElement(tag); if (text != null) node.textContent=String(text); if(className) node.className=className; return node;};
  const option = (select, value, label) => {const node=el('option', label); node.value=value; select.append(node);};
  const params = new URLSearchParams(location.search), preview=params.get('preview') === '1';
  const base = new URL(preview ? '../results/preview/' : '../results/published/', location.href);
  async function read(url, json = true) { const response=await fetch(url); if(!response.ok) throw new Error(`HTTP ${response.status}`); return json ? response.json() : response.text(); }
  async function readOptional(url) { const response=await fetch(url); if(response.status===404) return null; if(!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }
  function selectTab(selected) {
    const review=selected==='review';
    $('#overview-panel').hidden=review; $('#review-panel').hidden=!review;
    $('#overview-tab').className=review?'tab':'tab active'; $('#review-tab').className=review?'tab active':'tab';
    $('#overview-tab').ariaSelected=String(!review); $('#review-tab').ariaSelected=String(review);
    $('#overview-tab').tabIndex=review?-1:0; $('#review-tab').tabIndex=review?0:-1;
  }
  $('#page-tabs').hidden=true; $('#review-panel').hidden=true; $('#overview-panel').hidden=false;
  $('#overview-tab').onclick=()=>selectTab('overview'); $('#review-tab').onclick=()=>selectTab('review');
  const tabs=[$('#overview-tab'),$('#review-tab')];
  tabs.forEach((tab,index)=>tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const target=event.key==='Home'?tabs[0]:event.key==='End'?tabs[1]:tabs[(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];
    target.onclick(); target.focus();
  }));
  function renderReviewSamples(review) {
    const expectedGroups=[['jev_correct_luna_wrong','Jev correct, Luna incorrect'],['both_wrong','Both incorrect']];
    if(review?.schema_version!=='1.0.0' || review.status!=='reviewed_sample' || review.task_id!=='harmful_jailbreak' || review.task_version!=='1.0.0' ||
      review.source_runs?.jev!=='20260925T004541177372Z-a4c027600058' || review.source_runs?.luna!=='20260925T014904391035Z-ba0833bb4475' ||
      review.selection?.method!=='uniform_random_without_replacement' || review.selection.seed!==20261004 || review.selection.provider_errors_excluded!==true ||
      !Array.isArray(review.groups) || review.groups.length!==2) throw new Error('Unsupported review sample schema');
    const seen=new Set(); $('#review-samples').replaceChildren();
    review.groups.forEach((group,index)=>{
      const [expectedId,expectedTitle]=expectedGroups[index];
      if(group.id!==expectedId || group.title!==expectedTitle || !Array.isArray(group.samples) || group.samples.length!==5) throw new Error('Unsupported review sample group');
      const section=el('section',null,'review-group'); section.append(el('h3',group.title),el('p','5 cases'));
      group.samples.forEach(sample=>{
        if(!sample || typeof sample.case_id!=='string' || seen.has(sample.case_id) || typeof sample.prompt!=='string' || typeof sample.ground_truth!=='boolean' ||
          typeof sample.jev_decision!=='boolean' || typeof sample.luna_decision!=='boolean' || !Number.isFinite(sample.jev_score)) throw new Error('Unsupported review sample');
        const jevCorrect=sample.jev_decision===sample.ground_truth,lunaCorrect=sample.luna_decision===sample.ground_truth;
        if((group.id==='jev_correct_luna_wrong' && (!jevCorrect || lunaCorrect)) || (group.id==='both_wrong' && (jevCorrect || lunaCorrect))) throw new Error('Review sample does not match its group');
        seen.add(sample.case_id);
        const card=el('details',null,'review-card'), summary=el('summary',sample.case_id);
        const facts=el('div',null,'review-facts');
        const decision=value=>value?'Harmful':'Benign';
        facts.append(el('p',`Source label: ${sample.source_label}`),el('p',`Ground truth: ${decision(sample.ground_truth)}`),el('p',`Jev: ${decision(sample.jev_decision)} · score ${format(sample.jev_score)}`),el('p',`Luna: ${decision(sample.luna_decision)}`));
        card.append(summary,facts,el('h4','Case text'),el('p',sample.prompt,'case-prompt')); section.append(card);
      });
      $('#review-samples').append(section);
    });
  }
  function renderHeadline(headline, review) {
    if (headline.schema_version !== '1.1.0' || headline.status !== 'exploratory' || !Array.isArray(headline.systems) || headline.systems.length !== 2) throw new Error('Unsupported headline schema');
    const presentations={
      jev:{displayName:'Jev',provider:'TypeSafe AI',modelId:'jev-latest',runId:'20260925T004541177372Z-a4c027600058',costBasis:'estimated_input_tokens',costNote:'Estimated from published input-token pricing; cost methods differ and are not ranked.'},
      luna:{displayName:'Luna',provider:'OpenRouter',modelId:'openai/gpt-5.6-luna',runId:'20260925T014904391035Z-ba0833bb4475',costBasis:'provider_reported_partial',costNote:'Known provider-reported spend covers 1,611 of 1,614 cases; incomplete cost is shown as a lower bound.'}
    };
    const systems=headline.systems.map(system=>{const presentation=presentations[system.system];if(!presentation || system.run_id!==presentation.runId || system.cost_basis!==presentation.costBasis) throw new Error('Unsupported headline system');return {system,presentation};});
    if(new Set(systems.map(entry=>entry.system.system)).size!==2) throw new Error('Unsupported headline systems');
    $('#subtitle').textContent='Current exploratory comparison on a shared deterministic sample.';
    $('#controls').hidden=true;$('#explorer').hidden=true;
    const rate=Number((headline.sample.rate*100).toFixed(3));
    $('#status').replaceChildren(
      el('p','SUMMARY-ONLY EXPLORATORY COMPARISON — not a full-dataset benchmark.','warning'),
      el('p',`${rate}% sample · ${headline.sample.count.toLocaleString('en-US')} cases · seed ${headline.sample.seed}${review ? ' · ten reviewed cases available.' : ' · no case-level evidence published.'}`)
    );
    const table=el('table'), head=el('tr');head.append(el('th','Metric'));
    systems.forEach(({presentation})=>{const th=el('th',presentation.displayName);th.append(el('p',`${presentation.modelId} · ${presentation.provider}`));head.append(th);});table.append(head);
    const rows=[['F1','f1','percent'],['Precision','precision','percent'],['Recall','recall','percent'],['Accuracy','accuracy','percent'],['Coverage','coverage','percent'],['Errors','errors'],['Latency p50 (ms)','latency_p50_ms'],['Latency p95 (ms)','latency_p95_ms']];
    for(const [label,key,kind] of rows){const tr=el('tr');tr.append(el('th',label));systems.forEach(({system})=>tr.append(el('td',format(system.metrics[key],kind))));table.append(tr);}
    const confusion=el('tr');confusion.append(el('th','Confusion TP / TN / FP / FN'));systems.forEach(({system})=>confusion.append(el('td',['true_positive','true_negative','false_positive','false_negative'].map(key=>format(system.metrics.confusion[key])).join(' / '))));table.append(confusion);
    const cost=el('tr');cost.append(el('th','Observed cost (USD)'));systems.forEach(({system,presentation})=>{const metrics=system.metrics,value=metrics.total_cost_usd ?? metrics.known_cost_usd;const prefix=metrics.total_cost_usd == null && value != null?'≥':'';const td=el('td',value == null?'Unavailable':`${prefix}${format(value,'money')}`);td.append(el('small',presentation.costNote));cost.append(td);});table.append(cost);
    $('#systems').replaceChildren(table);
    const provenance=el('dl',null,'metadata');
    for(const [key,value] of Object.entries({title:'Jev vs Luna — WildJailbreak harmful-jailbreak detection',task:`${headline.task_id} / ${headline.task_version}`,dataset:headline.dataset.name,dataset_revision:headline.dataset.revision,source_runs:systems.map(({presentation})=>presentation.runId).join(', ')})) provenance.append(el('dt',key),el('dd',value));
    $('#metadata').replaceChildren(provenance,el('p','Only aggregate metrics and sampling metadata are published; no case-level downloads are available.','warning'),el('p','Model snapshots were unavailable and provider defaults were unresolved for both systems.','warning'));
    $('#compatibility').textContent='Quality scores use the same task and deterministic cohort. Cost methods differ and are not ranked.';
    if(review){renderReviewSamples(review);$('#page-tabs').hidden=false;selectTab('overview');}
  }
  const index = await read(new URL('index.json', base));
  if (index.schema_version?.split('.')[0] !== '1' || !Array.isArray(index.runs)) throw new Error('Unsupported catalogue schema');
  $('#subtitle').textContent = preview ? 'LOCAL PREVIEW — includes non-publishable runs' : 'Compare exact model runs on a shared benchmark task.';
  if (!index.runs.length) {
    const headline=preview?null:await readOptional(new URL('headline.json',base));
    if(headline){const review=await readOptional(new URL('review-samples.json',base));renderHeadline(headline,review);return;}
    $('#status').textContent = preview ? 'No preview results.' : 'No published results yet.'; return;
  }
  const entries=flatten(index), bundles=new Map(), predictions=new Map();
  for (const run of index.runs.filter(r => !r.systems?.length)) $('#status').append(el('p', `${run.run_id}: ${run.status} / ${run.validation_status} ${run.incomplete_reason || ''} ${(run.rule_ids || []).join(', ')}`));
  if (!entries.length) return;
  $('#controls').hidden=false;
  [...new Set(entries.map(e => taskKey(e.run)))].sort().forEach(t => option($('#task'),t,t));
  if ([...$('#task').options].some(o => o.value === params.get('task'))) $('#task').value=params.get('task');
  let selected=[], reference='', generation=0;
  function updateCohorts(initial) {
    $('#cohort').replaceChildren(); option($('#cohort'), '*', 'All cohorts (inspect incompatibilities)');
    [...new Set(entries.filter(e => taskKey(e.run) === $('#task').value).map(e => e.system.quality_key || 'unavailable'))].sort().forEach(k => option($('#cohort'),k,k));
    $('#cohort').value=initial && [...$('#cohort').options].some(o => o.value === params.get('cohort')) ? params.get('cohort') : $('#cohort').options[1]?.value || '*';
    updateChoices(initial);
  }
  function visibleEntries() { return entries.filter(e => taskKey(e.run) === $('#task').value && ($('#cohort').value === '*' || (e.system.quality_key || 'unavailable') === $('#cohort').value)); }
  const name = e => `${e.system.identity?.display_name || e.system.identity?.requested_model_id || e.system.display_name || e.system.requested_model_id || e.system.system_id} · ${e.run.run_id}`;
  function updateChoices(initial) {
    const visible=visibleEntries(); selected=initial ? exactSelection(visible,location.search) : defaults(visible).map(token);
    reference=initial ? params.get('reference') || '' : ''; $('#choices').replaceChildren();
    const defaultTokens=new Set(defaults(visible).map(token));
    for (const entry of visible) {const label=el('label',null,'choice'), check=el('input'); check.type='checkbox'; check.checked=selected.includes(token(entry));
      check.addEventListener('change',()=>{selected=check.checked ? [...selected, token(entry)] : selected.filter(t=>t !== token(entry)); render().catch(fail);});
      label.append(check,el('span',`${name(entry)}${defaultTokens.has(token(entry)) ? ' — default' : ' — alternative'} · ${entry.run.run_kind} · ${entry.run.status} · ${entry.run.validation_status}${entry.run.potentially_stale ? ' · POTENTIALLY STALE' : ''}`)); $('#choices').append(label);}
    render().catch(fail);
  }
  function fail(error) {$('#status').textContent=`Results unavailable: ${error.message}`;}
  async function load(entry) {
    const run=entry.run;
    if (!bundles.has(run.run_id)) {
      if (!run.aggregate_uri) return {manifest: run, systems: []};
      const aggregate=await read(artifactUrl(base,run.aggregate_uri));
      if (!aggregate.manifest && run.manifest_uri) aggregate.manifest=await read(artifactUrl(base,run.manifest_uri));
      bundles.set(run.run_id,aggregate);
    }
    if (!predictions.has(run.run_id) && run.predictions_uri) { const text=await read(artifactUrl(base,run.predictions_uri),false); predictions.set(run.run_id,text.split('\n').filter(l=>l.trim()).map(l=>JSON.parse(l))); }
    return bundles.get(run.run_id);
  }
  async function render() {
    const version=++generation, chosen=visibleEntries().filter(e=>selected.includes(token(e)));
    $('#systems').replaceChildren(); $('#metadata').replaceChildren(); $('#compatibility').replaceChildren();
    $('#explorer').hidden=true; $('#cases').replaceChildren(); $('#case-count').textContent='';
    $('#reference').replaceChildren(); option($('#reference'),'','Select an explicit reference'); chosen.forEach(e=>option($('#reference'),token(e),name(e)));
    if (!selected.includes(reference)) reference=''; $('#reference').value=reference;
    history.replaceState(null,'',selectionQuery($('#task').value,$('#cohort').value,selected,reference,preview));
    const loaded=await Promise.all(chosen.map(load)); if (version !== generation) return;
    if (!chosen.length) {$('#systems').textContent='Select results to compare.'; $('#explorer').hidden=true; return;}
    const table=el('table'), head=el('tr'); head.append(el('th','Metric')); chosen.forEach((e,i)=>{const th=el('th',name(e)); const identity=e.system.identity || e.system; th.append(el('p', `${identity.requested_model_id || 'See provenance'} · snapshot: ${identity.snapshot_status || 'unavailable'} · ${e.run.completed_at || loaded[i].manifest?.completed_at || 'date unavailable'}`)); head.append(th);}); table.append(head);
    const metrics=chosen.map((e,i)=>(loaded[i].systems || []).find(s=>s.evaluated_system_id === e.system.evaluated_system_id) || {});
    const knownCosts=chosen.map(e=>knownCost(predictions.get(e.run.run_id),e.system.evaluated_system_id));
    const refIndex=chosen.findIndex(e=>token(e)===reference);
    const rows=[['F1','f1','quality','percent'],['Precision','precision','quality','percent'],['Recall','recall','quality','percent'],['Accuracy','accuracy','quality','percent'],['Coverage','coverage','quality','percent'],['Errors','errors','quality'],['Latency p50 (ms)','latency_p50_ms','latency'],['Latency p95 (ms)','latency_p95_ms','latency'],['Total cost (USD)','total_cost_usd','cost','money'],['Cost / 1,000 examples (USD)','cost_per_1000_examples_usd','cost','money'],['Known cost coverage','cost_coverage','cost','percent'],['Known cost records','cost_known_count','cost']];
    for (const [label,key,family,kind] of rows) {
      const tr=el('tr'); tr.append(el('th',label));
      metrics.forEach((m,i)=>{
        const observed=knownCosts[i];
        const costRow=key==='total_cost_usd' || key==='cost_per_1000_examples_usd';
        const showKnown=costRow && m[key] == null && observed.count > 0 && m.attempted > 0;
        const knownValue=key==='cost_per_1000_examples_usd' ? observed.usd * 1000 / m.attempted : observed.usd;
        const td=el('td',showKnown ? `≥${format(knownValue,'money')}` : format(m[key],kind));
        if (showKnown) {
          const missing=observed.total-observed.count;
          td.append(el('small',`Known ${observed.count}/${observed.total} cases; excludes ${missing} unknown cost${missing===1?'':'s'}`));
        }
        const rank=['cost_coverage','cost_known_count'].includes(key) ? null : metricRank(chosen,metrics,i,refIndex,family,key);
        if(rank != null) td.append(el('small',`Rank ${rank} of ${chosen.length}`));
        if(refIndex>=0 && i!==refIndex && compatibility(chosen[i],chosen[refIndex],family).eligible && Number.isFinite(m[key]) && Number.isFinite(metrics[refIndex][key])) td.append(el('small',`Δ ${format(m[key]-metrics[refIndex][key],kind)} vs reference`));
        tr.append(td);
      });
      table.append(tr);
    }
    const confusion=el('tr');confusion.append(el('th','Confusion TP / TN / FP / FN'));metrics.forEach(m=>confusion.append(el('td',m.confusion ? ['true_positive','true_negative','false_positive','false_negative'].map(k=>format(m.confusion[k])).join(' / ') : 'Unavailable')));table.append(confusion);$('#systems').append(table);
    if(refIndex<0) {$('#compatibility').append(el('p','Select a reference to show compatible metric deltas.')); const inspectionReference=chosen[0]; chosen.forEach(e=>families.forEach(f=>{const c=compatibility(e,inspectionReference,f);if(!c.eligible)$('#compatibility').append(el('p',`${name(e)} — ${f}: ${c.reason}`,'warning'));}));}
    else chosen.forEach(e=>families.forEach(f=>{const c=compatibility(e,chosen[refIndex],f);$('#compatibility').append(el('p',`${name(e)} — ${f}: ${c.reason}`,c.eligible?'':'warning'));}));
    chosen.forEach((e,i)=>{const details=el('details'), manifest=loaded[i].manifest || {}, summary=el('summary',name(e)); details.append(summary);
      const states=[e.run.run_kind,e.run.status,e.run.validation_status,e.run.potentially_stale || loaded[i].potentially_stale ? 'POTENTIALLY STALE':null,e.run.incomplete_reason || manifest.incomplete_reason].filter(Boolean);details.append(el('p',states.join(' · '),'warning'));
      // Only validated public projections are fetched; textContent keeps arbitrary strings inert.
      const dl=el('dl',null,'metadata');for(const [k,v] of Object.entries({...manifest, selected_system:e.system, artifact_digests:e.run.artifact_digests})) {dl.append(el('dt',k),el('dd',typeof v==='object' ? JSON.stringify(v,null,2) : v));}details.append(dl);
      const nav=el('nav');for(const [key,label] of [['manifest_uri','Manifest'],['aggregate_uri','Aggregate'],['predictions_uri','Public predictions'],['cohort_uri','Public cohort'],['validation_report_uri','Validation report']]) if(e.run[key]) {const a=el('a',label);a.href=artifactUrl(base,e.run[key]);nav.append(a);}details.append(nav);$('#metadata').append(details);});
    const cases=caseRows(chosen,predictions); $('#explorer').hidden=false;
    const oldLabel=$('#label').value;$('#label').replaceChildren();option($('#label'),'','All labels');[...new Set(cases.map(c=>c.source_label))].filter(Boolean).sort().forEach(l=>option($('#label'),l,l));$('#label').value=oldLabel;
    function renderCases() {const filtered=filterCases(cases,$('#label').value,$('#filter').value,$('#sort').value);$('#case-count').textContent=`${filtered.length} cases · showing up to 200`;const t=el('table'),h=el('tr');h.append(el('th','Public case / truth / label'));chosen.slice(0,4).forEach(e=>h.append(el('th',name(e))));t.append(h);
      for(const item of filtered.slice(0,200)){const tr=el('tr');tr.append(el('th',`${item.id} · ${item.ground_truth} · ${item.source_label}`));chosen.slice(0,4).forEach(e=>{const r=item.rows.get(token(e)),td=el('td');if(!r) td.textContent='No record in this cohort';else {td.append(el('strong',r.error ? `ERROR: ${typeof r.error === 'string' ? r.error : r.error.category || r.error.code || 'provider'}` : String(r.decision)),el('p',`Score ${format(r.score)} · ${format(r.latency_ms)} ms · ${format(r.cost_usd,'money')} (${r.cost_status || 'unavailable'})`),el('small',`Tokens in/out: ${format(r.usage?.input_tokens ?? r.input_tokens)} / ${format(r.usage?.output_tokens ?? r.output_tokens)}`));}tr.append(td);});t.append(tr);}$('#cases').replaceChildren(t);}
    for(const selector of ['#label','#filter','#sort']) $(selector).onchange=renderCases;renderCases();
  }
  $('#task').onchange=()=>updateCohorts(false);$('#cohort').onchange=()=>updateChoices(false);$('#reference').onchange=()=>{reference=$('#reference').value;render().catch(fail);};updateCohorts(true);
}
