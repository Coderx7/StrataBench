/* Saved answers are the source of truth for live and finished evaluations. */
const outcomeLabels={all:'All tests',passed:'Correct',incorrect:'Incorrect',cutoffs:'Cutoffs',errors:'Request errors',pending:'Pending',unparsed:'Unparsed answers'};
const outcomeEmpty={all:'No tests to show.',passed:'No correct answers yet.',incorrect:'No incorrect answers.',cutoffs:'No cutoffs.',errors:'No request errors.',pending:'No pending tests.',unparsed:'No unparsed answers.'};
const outcomeIcons={passed:'check',incorrect:'close',cutoffs:'activity',errors:'bolt',pending:'clock'};
let explorerRun=null, explorerCategory='all', explorerData=null, explorerOffset=0;
let explorerFilters={search:'',target:'',difficulty:'',group:''}, explorerSequence=0, explorerSearchTimer=null;
let detailSequence=0, detailSelection=null, detailPageKeys=[];
const renderedHTML=new WeakMap();
function stableHTML(selector,html){const node=$(selector);if(node&&renderedHTML.get(node)!==html){node.innerHTML=html;renderedHTML.set(node,html);}}
function outcomeMetrics(id,counts,selected=''){
  return `<div class="outcome-metrics">${['passed','incorrect','cutoffs','errors','pending'].map(k=>`<button class="outcome-metric outcome-${k} ${selected===k?'selected':''}" data-action="inspect-tests" data-run="${esc(id)}" data-category="${k}" aria-label="${outcomeLabels[k]}: ${counts[k]||0}. View tests" ${selected===k?'aria-pressed="true"':'aria-pressed="false"'}><span class="outcome-symbol">${icon(outcomeIcons[k])}</span><span class="metric-label">${outcomeLabels[k]}</span><strong>${formatNumber(counts[k])}</strong><small>View tests ${icon('external')}</small></button>`).join('')}</div>`;
}
function compactOutcomes(run){return `<div class="compact-outcomes">${['passed','incorrect','cutoffs','errors','pending'].filter(k=>run.counts[k]).map(k=>`<button class="outcome-pill outcome-${k}" data-action="inspect-tests" data-run="${esc(run.id)}" data-category="${k}" title="View ${outcomeLabels[k].toLowerCase()} tests">${icon(outcomeIcons[k])}${formatNumber(run.counts[k])}<span class="sr-only"> ${outcomeLabels[k]}</span></button>`).join('')}</div>`;}
function unfinishedRuns(){
  const runs=state.runs.filter(r=>r.resumable);
  if(!runs.length)return '';
  return `<section class="resume-panel"><div class="resume-intro"><span class="card-icon">${icon('play')}</span><div><div class="eyebrow">PICK UP WHERE YOU LEFT OFF</div><h2>${runs.length===1?'An unfinished benchmark is waiting.':`${runs.length} benchmarks can be resumed.`}</h2><p>Saved answers stay in place. Only pending tests and request errors are retried.</p></div></div><div class="resume-items">${runs.map(r=>`<div class="resume-item"><div><strong>${esc(state.profiles.find(p=>p.id===r.profile)?.name||r.profile)}</strong><span>${esc(dateText(r.created))} · ${formatNumber(r.completed)} / ${formatNumber(r.total)} saved · ${formatNumber(r.remaining)} to run</span></div><div class="table-actions"><button class="text-button" data-action="inspect-tests" data-run="${esc(r.id)}">Inspect tests</button><button class="primary-button" data-action="resume" data-run="${esc(r.id)}" ${busy()||r.resume_blocked?'disabled':''}>${icon('play')} Resume</button></div></div>`).join('')}</div></section>`;
}
function reportOutcomePanel(){const r=state.runs.find(r=>r.id===selectedReport);return r?.counts?`<section class="card saved-outcome-panel"><div class="section-title"><div><h2>Every answer has a story.</h2><p>Choose a count to inspect its tests, prompts, and model responses.</p></div><button class="secondary-button" data-action="inspect-tests" data-run="${esc(r.id)}">Explore all tests</button></div>${outcomeMetrics(r.id,r.counts)}</section>`:'';}
function paintReportOutcomes(){const panel=$('#report-outcomes');if(panel)panel.innerHTML=reportOutcomePanel();}
function rememberExplorer(){try{sessionStorage.setItem('stratabench-explorer',JSON.stringify({id:explorerRun,category:explorerCategory}));}catch{}}
function openExplorer(id,category='all'){
  if(explorerRun!==id){explorerData=null;explorerFilters={search:'',target:'',difficulty:'',group:''};}
  explorerRun=id;explorerCategory=category;explorerOffset=0;rememberExplorer();
  if(page==='tests')render();else navigate('tests');
}
function renderTests(){
  if(!explorerRun){try{const saved=JSON.parse(sessionStorage.getItem('stratabench-explorer')||'null');if(state.runs.some(r=>r.id===saved?.id)){explorerRun=saved.id;explorerCategory=saved.category||'all';}}catch{}}
  const run=state.runs.find(r=>r.id===explorerRun);
  if(!run)return heading('TEST EXPLORER','Choose a benchmark to explore.','Open a run from Results to inspect its individual tests.')+`<button class="primary-button" data-action="go-results">Go to Results</button>`;
  return heading('LOOK INSIDE THE SCORE','Every test. Every answer.','Explore the evidence behind your results. Counts update as answers are saved.',`<button class="secondary-button" data-action="go-results">${icon('chart')} All results</button>`)+`
  <section class="explorer-banner"><div><span class="badge neutral">${esc(run.reasoning.toUpperCase())} reasoning</span><h2>${esc(state.profiles.find(p=>p.id===run.profile)?.name||run.profile)} <span>· ${esc(dateText(run.created))}</span></h2><p>${formatNumber(run.questions)} questions · ${run.combinations} combination${run.combinations===1?'':'s'} · ${run.repeats} repeat${run.repeats===1?'':'s'}</p></div><div id="explorer-run-action">${explorerRunAction(run)}</div></section>
  <div id="explorer-counts">${outcomeMetrics(run.id,run.counts||{},explorerCategory)}</div>
  <section class="card test-library"><div class="test-library-heading"><div><h2 id="explorer-list-title">${outcomeLabels[explorerCategory]||'All tests'}</h2><p id="explorer-coverage">Reading saved answers…</p></div><div class="explorer-tabs"><button data-explorer-category="all" class="secondary-button ${explorerCategory==='all'?'chosen':''}">All tests</button><button data-explorer-category="unparsed" class="secondary-button ${explorerCategory==='unparsed'?'chosen':''}">Unparsed <span id="unparsed-count">${run.counts?.unparsed||0}</span></button></div></div>
  <div class="test-filters"><label class="test-search"><span class="sr-only">Search tests</span>${icon('search')}<input id="test-search" placeholder="Search questions or test IDs…" value="${esc(explorerFilters.search)}"></label><label><span class="sr-only">Combination</span><select id="test-target"><option value="">All combinations</option></select></label><label><span class="sr-only">Difficulty</span><select id="test-difficulty"><option value="">All difficulties</option>${levels.map(k=>`<option value="${k}" ${explorerFilters.difficulty===k?'selected':''}>${levelLabel[k]}</option>`).join('')}</select></label><label><span class="sr-only">Task group</span><select id="test-group"><option value="">All task groups</option></select></label></div>
  <div id="test-results" aria-live="polite"><div class="explorer-loading"><div class="spinner"></div> Reading saved tests…</div></div>
  <div id="test-pagination" class="test-pagination"></div></section>
  <p class="outcome-footnote">Correct, incorrect, cutoffs, request errors, and pending are separate categories. Unparsed is an additional filter on saved answers. Resuming keeps scored answers, including incorrect answers and cutoffs.</p>`;
}
function explorerRunAction(run){return run.active?'<span class="live-indicator"><span class="status-dot"></span> Live · updates automatically</span>':run.resumable?`<button class="primary-button" data-action="resume" data-run="${esc(run.id)}" ${busy()||run.resume_blocked?'disabled':''}>${icon('play')} Resume benchmark</button>`:statusBadge(run.status);}
async function loadOutcomes(){
  if(page!=='tests'||!explorerRun||!$('#test-results'))return;
  const sequence=++explorerSequence,id=explorerRun,category=explorerCategory;
  try{
    const data=await api('/api/outcomes',{id,category,offset:explorerOffset,limit:30,...explorerFilters});
    if(sequence!==explorerSequence||page!=='tests'||id!==explorerRun)return;
    explorerData=data;
    stableHTML('#explorer-counts',outcomeMetrics(id,data.counts,category));
    $('#explorer-list-title').textContent=outcomeLabels[category];
    $('#explorer-coverage').textContent=`${formatNumber(data.matched)} matching ${data.matched===1?'evaluation':'evaluations'} · ${formatNumber(data.completed)} of ${formatNumber(data.total)} saved`;
    $('#unparsed-count').textContent=data.counts.unparsed;
    stableHTML('#explorer-run-action',explorerRunAction(data));
    for(const [selector,items,value] of [['#test-target',data.targets,explorerFilters.target],['#test-group',data.groups.map(g=>({id:g,label:g.replaceAll('_',' ')})),explorerFilters.group]]){
      const select=$(selector), html=`<option value="">${selector==='#test-target'?'All combinations':'All task groups'}</option>`+items.map(t=>`<option value="${esc(t.id)}" ${String(t.id)===value?'selected':''}>${esc(t.label)}</option>`).join('');
      if(renderedHTML.get(select)!==html){select.innerHTML=html;renderedHTML.set(select,html);}
    }
    stableHTML('#test-results',data.tests.length?`<div class="test-card-grid">${data.tests.map(testCard).join('')}</div>`:`<div class="test-empty"><span class="empty-icon">${icon(category==='passed'?'check':'search')}</span><h3>${explorerFilters.search||explorerFilters.target||explorerFilters.difficulty||explorerFilters.group?'No tests match these filters.':outcomeEmpty[category]}</h3><p>${data.active?'This view updates automatically as the benchmark runs.':'Choose another category or adjust your filters to explore this run.'}</p></div>`);
    const end=Math.min(data.offset+data.limit,data.matched);
    stableHTML('#test-pagination',`<span>${data.matched?`${data.offset+1}–${end} of ${formatNumber(data.matched)}`:'0 tests'}</span><div class="table-actions"><button class="secondary-button" data-test-offset="${Math.max(0,data.offset-data.limit)}" ${data.offset===0?'disabled':''}>Previous</button><button class="secondary-button" data-test-offset="${data.offset+data.limit}" ${end>=data.matched?'disabled':''}>Next</button></div>`);
  }catch(error){if(sequence===explorerSequence&&page==='tests'&&$('#test-results'))$('#test-results').innerHTML=`<div class="test-empty" role="alert"><h3>Could not read these tests.</h3><p>${esc(error.message)}</p><button class="secondary-button" data-action="reload-tests">Try again</button></div>`;}
}
function testCard(t){return `<button class="test-card outcome-${t.status}" data-test-key="${esc(t.key)}"><div class="test-card-top"><span class="outcome-pill outcome-${t.status}">${icon(outcomeIcons[t.status])}${outcomeLabels[t.status]}</span><span class="test-difficulty">${levelLabel[t.difficulty]||esc(t.difficulty)}</span></div><h3>${esc(t.case_id)}</h3><p dir="auto">${esc(t.preview)}</p><div class="test-card-bottom"><span>${esc(t.label)}</span><span>Repeat ${t.repeat}${t.elapsed_seconds!=null?' · '+duration(t.elapsed_seconds):''}</span></div><div class="test-card-link">${t.status==='pending'?'View question':'Inspect answer'} ${icon('external')}${t.attempts>1?`<span>${t.attempts} attempts</span>`:''}</div></button>`;}
function prettyAnswer(value){return typeof value==='string'?value:JSON.stringify(value,null,2);}
async function openTest(key,navigating=false){
  if(!navigating)detailPageKeys=(explorerData?.tests||[]).map(t=>t.key);
  const sequence=++detailSequence;detailSelection=key;
  showModal('Inside the evaluation',`<div class="explorer-loading"><div class="spinner"></div> Reading this answer…</div>`);$('#modal').classList.add('test-detail-dialog');
  try{
    const data=await api('/api/outcomes',{id:explorerRun,key});
    if(sequence!==detailSequence||detailSelection!==key||!$('#modal').open)return;
    const t=data.test,c=data.case,a=data.answer;
    const message=a.response?.choices?.[0]?.message||{};
    const reasoning=message.reasoning_content||message.reasoning||a.reasoning_content;
    const content=a.content??message.content;
    const text=t.status==='passed'?'The model matched the reference answer.':t.status==='pending'?'This test has not produced a saved answer yet.':t.status==='errors'?'The request failed. Resume this run to retry it.':t.status==='cutoffs'?'The answer reached its generation limit before finishing.':'The saved answer did not match the reference.';
    const position=detailPageKeys.indexOf(key);
    $('#modal-content').innerHTML=`<div class="modal-top"><div><div class="eyebrow">TEST DETAIL · REPEAT ${t.repeat}</div><h2>${esc(t.case_id)}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close')}</button></div><div class="modal-body test-detail-body"><div class="test-verdict outcome-${t.status}"><span class="outcome-pill outcome-${t.status}">${icon(outcomeIcons[t.status])}${outcomeLabels[t.status]}</span><p>${text}</p></div><div class="test-detail-meta"><span>${esc(t.label)}</span><span>${levelLabel[t.difficulty]} · ${esc(t.group)}</span>${a.elapsed_seconds!=null?`<span>${duration(a.elapsed_seconds)} response</span>`:''}<span>${t.attempts} saved attempt${t.attempts===1?'':'s'}</span></div>
    <section class="question-panel"><div class="eyebrow">THE QUESTION</div><pre dir="auto">${esc(c.prompt)}</pre></section>
    <div class="answer-panels"><section class="expected-panel"><div class="eyebrow">REFERENCE ANSWER</div><pre dir="auto">${esc(prettyAnswer(c.answer))}</pre>${a.extracted!==undefined?`<div class="eyebrow extracted-label">EXTRACTED FROM RESPONSE</div><pre dir="auto">${esc(prettyAnswer(a.extracted))}</pre>`:''}<div class="answer-grader">Grader: ${esc(c.grader||'reference')}</div></section><section class="model-answer-panel"><div class="eyebrow">${t.status==='errors'?'REQUEST ERROR':'MODEL RESPONSE'}</div><pre dir="auto">${esc(a.error||content||(t.status==='pending'?'Waiting for an answer.':'The model returned no answer text.'))}</pre></section></div>
    ${reasoning?`<details class="answer-reasoning"><summary>Model reasoning</summary><pre dir="auto">${esc(typeof reasoning==='string'?reasoning:prettyAnswer(reasoning))}</pre></details>`:''}
    ${a.request?`<details class="answer-reasoning"><summary>Request settings & token usage</summary><pre>${esc(prettyAnswer({finish_reason:a.finish_reason,usage:a.usage,settings:Object.fromEntries(Object.entries(a.request).filter(([k])=>k!=='messages')),unparsed:a.unparsed,json_format:a.json_format}))}</pre></details>`:''}
    <div class="test-detail-nav"><button class="secondary-button" data-test-step="-1" ${position<=0?'disabled':''}>Previous test</button><span>In this filtered page</span><button class="secondary-button" data-test-step="1" ${position<0||position>=detailPageKeys.length-1?'disabled':''}>Next test</button></div></div>`;
  }catch(error){if(sequence===detailSequence&&$('#modal').open)$('#modal-content').innerHTML=`<div class="modal-body"><h2>Unable to open this test</h2><p>${esc(error.message)}</p><button class="secondary-button" data-action="close-modal">Close</button></div>`;}
}
document.addEventListener('click',event=>{
  const target=event.target.closest('button');if(!target||target.disabled)return;
  if(target.dataset.action==='inspect-tests'){openExplorer(target.dataset.run,target.dataset.category||'all');return;}
  if(target.dataset.action==='reload-tests'){loadOutcomes();return;}
  if(target.dataset.explorerCategory){explorerCategory=target.dataset.explorerCategory;explorerOffset=0;rememberExplorer();render();return;}
  if(target.dataset.testOffset!==undefined){explorerOffset=Number(target.dataset.testOffset);loadOutcomes();$('#explorer-list-title').scrollIntoView({block:'start',behavior:'smooth'});return;}
  if(target.dataset.testKey){openTest(target.dataset.testKey);return;}
  if(target.dataset.testStep){const index=detailPageKeys.indexOf(detailSelection)+Number(target.dataset.testStep);if(detailPageKeys[index])openTest(detailPageKeys[index],true);}
});
document.addEventListener('input',event=>{if(event.target.id==='test-search'){explorerFilters.search=event.target.value;explorerOffset=0;clearTimeout(explorerSearchTimer);explorerSearchTimer=setTimeout(loadOutcomes,200);}});
document.addEventListener('change',event=>{const key={'test-target':'target','test-difficulty':'difficulty','test-group':'group'}[event.target.id];if(key){explorerFilters[key]=event.target.value;explorerOffset=0;loadOutcomes();}});
document.addEventListener('close',event=>{if(event.target.id==='modal'){detailSelection=null;detailSequence++;event.target.classList.remove('test-detail-dialog');}},true);
