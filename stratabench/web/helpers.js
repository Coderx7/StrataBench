'use strict';

const BENCHMARK_LABELS={gsm8k:'GSM8K',science_qa:'OpenBookQA',math500_numeric:'MATH-500 numeric subset',aime2024:'AIME 2024',arithmetic:'Generated arithmetic',structured_data:'Structured JSON',algorithmic_reasoning:'Graph reasoning',python_tracing:'Python tracing',combinatorics:'Subset counting',exact_scheduling:'Exact scheduling',persian:'Persian arithmetic',context_retrieval:'Long-context retrieval'};
function groupLabel(group){return BENCHMARK_LABELS[group]||group.replace(/^bbh_/,'BBH · ').replaceAll('_',' ');}
function planningTime(seconds){if(seconds<60)return Math.max(1,Math.round(seconds))+' sec';if(seconds<3600)return Math.ceil(seconds/60)+' min';if(seconds<86400)return (Math.ceil(seconds/360)/10)+' hr';return (Math.ceil(seconds/8640)/10)+' days';}
function planningRange(row){return row&&Number.isFinite(row.lower_seconds)?'~'+planningTime(row.lower_seconds)+' – '+planningTime(row.upper_seconds):'Estimate unavailable';}
function selectedEstimateRows(result){return (result?.rows||[]).filter(r=>selectedConfigs.has(r.config)&&selectedVersions.has(r.version));}
function selectedEstimateTotal(result){const rows=selectedEstimateRows(result);return rows.length?{lower_seconds:rows.reduce((n,r)=>n+r.lower_seconds,0),upper_seconds:rows.reduce((n,r)=>n+r.upper_seconds,0)}:null;}

function scheduleEstimate(){
  if(!state||page!=='new')return;
  const versions=state.versions.filter(v=>selectedVersions.has(v.name)).map(v=>v.name);
  const configs=state.configs.map(c=>c.id);
  const payload={...form,versions,configs,tasks_id:customTasks?.id,all_suites:true};
  const key=JSON.stringify([payload,state.job?.id,state.job?.state,Math.floor(Date.now()/60000)]);
  if(key===estimateKey)return;
  estimateKey=key;estimateData=null;clearTimeout(estimateTimer);
  if(!versions.length||!configs.length)return;
  estimateTimer=setTimeout(async()=>{
    try{const result=await api('/api/estimate',payload);if(key!==estimateKey)return;estimateData=result;}
    catch(error){if(key!==estimateKey)return;estimateData={error:error.message};}
    if(page==='new'){paintEstimates();}
  },250);
}

function paintEstimates(){
  if(!state||page!=='new')return;
  all('[data-suite-time]').forEach(el=>{
    const suite=estimateData?.suites?.[el.dataset.suiteTime];
    const total=selectedEstimateTotal(suite);
    el.textContent=suite?.error?'No matching estimate':total?planningRange(total):estimateData?.error?'Estimate unavailable':'Estimating time…';
    el.title=suite?.notice||suite?.error||'Approximate duration for your selected versions, configs, reasoning and repeats.';
  });
  all('[data-config-time]').forEach(el=>{
    const rows=(estimateData?.rows||[]).filter(r=>r.config===el.dataset.configTime&&selectedVersions.has(r.version));
    if(!rows.length){el.textContent=estimateData?.error?'Time estimate unavailable':'Estimated time: calculating…';return;}
    const total={lower_seconds:rows.reduce((n,r)=>n+r.lower_seconds,0),upper_seconds:rows.reduce((n,r)=>n+r.upper_seconds,0)};
    el.textContent=planningRange(total)+(rows.length>1?' · '+rows.length+' versions':' · current suite');
    el.title=rows.map(r=>r.version+': '+r.basis).join('\n');
  });
  const box=$('#time-estimate-summary');if(!box)return;
  if(!selectedVersions.size||!selectedConfigs.size){box.innerHTML='<p>Select a version and config for a time estimate.</p>';return;}
  if(estimateData?.error){box.innerHTML='<strong>Time estimate unavailable</strong><p>'+esc(estimateData.error)+'</p>';return;}
  const total=selectedEstimateTotal(estimateData);
  if(!total){box.innerHTML='<strong>Estimating duration…</strong><p>Thinking and model loading are included.</p>';return;}
  const rows=selectedEstimateRows(estimateData);
  const measured=rows.reduce((n,r)=>n+r.local_sample_questions,0);
  const configs=new Map();
  rows.forEach(r=>{if(!configs.has(r.config))configs.set(r.config,{name:r.name,lower_seconds:0,upper_seconds:0,samples:0,warnings:[]});const c=configs.get(r.config);c.lower_seconds+=r.lower_seconds;c.upper_seconds+=r.upper_seconds;c.samples+=r.local_sample_questions;c.warnings.push(...r.warnings);});
  box.innerHTML='<span class="eta-eyebrow">ESTIMATED TOTAL TIME</span><strong class="eta-total">'+planningRange(total)+'</strong><p>'+(measured?'Includes '+measured+' locally timed question(s); unmeasured difficulties are estimated.':'Planning range. This combination has not been timed locally.')+'</p><details><summary>Time by configuration</summary>'+[...configs.values()].map(c=>'<div class="eta-config-row"><span title="'+esc(c.name)+'">'+esc(c.name.replace(/^strata-/,''))+'</span><strong>'+planningRange(c)+'</strong>'+[...new Set(c.warnings)].map(w=>'<small>'+esc(w)+'</small>').join('')+'</div>').join('')+'</details><p class="eta-caveat">Per-combination loading and warm-up included. Builds and downloads excluded. Long thinking can exceed this range.</p>';
}

function versionOrderControls(){return `<div class="version-order-toolbar"><label>Version order <select id="version-sort">${[['newest','Newest first'],['oldest','Oldest first'],['custom','Custom order']].map(([value,label])=>`<option value="${value}" ${state.version_sort_mode===value?'selected':''}>${label}</option>`).join('')}</select></label><p>Drag cards or use Move earlier / Move later. Your order is saved. New versions join the end of a custom order.</p></div>`;}
async function saveVersionOrder(mode,order){
  if(mode==='custom'&&!order)order=state.versions.map(v=>v.name);
  await api('/api/version-order',{mode,order});state=await api('/api/state');
  estimateKey='';if(['versions','new'].includes(page))render();toast('Version order saved.');
}
async function moveVersion(name,direction){const names=state.versions.map(v=>v.name);const from=names.indexOf(name),to=from+direction;if(from<0||to<0||to>=names.length)return;[names[from],names[to]]=[names[to],names[from]];await saveVersionOrder('custom',names);}
document.addEventListener('dragstart',event=>{const card=event.target.closest?.('[data-version-drag]');if(!card)return;draggedVersion=card.dataset.versionDrag;event.dataTransfer.setData('text/plain',draggedVersion);event.dataTransfer.effectAllowed='move';card.classList.add('dragging');});
document.addEventListener('dragover',event=>{if(draggedVersion&&event.target.closest?.('[data-version-drag]')){event.preventDefault();event.dataTransfer.dropEffect='move';}});
document.addEventListener('drop',event=>{const card=event.target.closest?.('[data-version-drag]');if(!card||!draggedVersion)return;event.preventDefault();const names=state.versions.map(v=>v.name),from=names.indexOf(draggedVersion),to=names.indexOf(card.dataset.versionDrag);if(from>=0&&to>=0&&from!==to){const [name]=names.splice(from,1);names.splice(to,0,name);saveVersionOrder('custom',names).catch(error=>toast(error.message,true));}draggedVersion=null;});
document.addEventListener('dragend',()=>{draggedVersion=null;all('[data-version-drag]').forEach(el=>el.classList.remove('dragging'));});

function renderReferences(){
  const refs=state.references;
  if(!refs)return heading('PUBLISHED ORIGINAL-MODEL RESULTS','Original model references','Reference metadata is not available.');
  const available=refs.rows.filter(r=>r.available);
  const rows=[...refs.rows].sort((a,b)=>Number(b.available)-Number(a.available)||groupLabel(a.group).localeCompare(groupLabel(b.group)));
  return heading('PUBLISHED ORIGINAL-MODEL RESULTS','A reference, with the details.','Compare local scores with published original-model results where the model, precision and method can be verified.')+
    `<div class="reference-overview"><div><span class="badge">Original post-trained model</span><h2>${esc(refs.model)}</h2><p>${esc(refs.precision_note)}</p></div><div><strong>${available.length}</strong><span>verified dataset reference${available.length===1?'':'s'}</span></div></div>`+
    `<div class="insight-box">${icon('book')}<span>${esc(refs.notice)} Missing scores remain unavailable. A pretrained Base-model score, quantized-model score, or different AIME year is not substituted.</span></div>`+
    `<section class="card reference-table"><div class="table-toolbar"><div><h2>Dataset coverage</h2><p>Checked ${esc(refs.checked_on)} · BF16 is not FP16 or INT8.</p></div><a class="text-button" href="${esc(refs.official_config)}" target="_blank" rel="noopener">Original model precision</a></div><div class="table-wrap"><table><thead><tr><th>Dataset / task</th><th>Original score</th><th>Weight precision</th><th>Method & source</th><th>Comparison</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(groupLabel(r.group))}</strong></td><td>${r.available?'<span class="score">'+Number(r.score_percent).toFixed(2)+'%</span>':'<span class="text-muted">Not available</span>'}</td><td>${esc(r.weight_precision||'—')}</td><td class="reference-method">${r.available?'<a href="'+esc(r.source)+'" target="_blank" rel="noopener">'+esc(r.publisher)+'</a><p>'+esc(r.source_type)+'</p><p>'+esc(r.method)+'</p>':esc(r.reason)}</td><td>${r.available?'<span class="badge warn">Context only</span>':'—'}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function capabilityControls(){
  const profile=form.profile;
  if(isStandardProfile())return standardControls();
  if(!['writing','vision','tools','coding'].includes(profile))return '';
  const notes={writing:'Local checks measure writing constraints. Optional judge ratings assess subjective quality separately.',vision:'Uses generated PNG images. Each selected config needs an image encoder and an available vision executable. Vision is enabled automatically.',tools:'Calls controlled test functions over multiple turns. No external tools, accounts, or host commands are exposed.',coding:'Miniature Python repair projects with file tools, visible tests, and hidden acceptance tests. Generated code runs only inside resource-limited Docker containers.'};
  return `<div class="capability-controls"><p>${notes[profile]}</p>${['tools','coding'].includes(profile)?`<label>Maximum model turns per task<input data-field="agent_turns" type="number" min="1" max="32" value="${esc(form.agent_turns)}"><small>Default answer budget: up to 4,096 tokens per turn unless you set a custom limit. Multi-turn tasks take longer.</small></label>`:''}
  ${profile==='coding'?`<label>Docker Python image<input data-field="coding_image" value="${esc(form.coding_image)}"></label><button class="secondary-button" data-action="prepare-coding" ${busy()?'disabled':''}>Prepare coding runtime</button><p class="form-note">Docker must be running in Linux-container mode. Preparation downloads the image once. Test containers have no network or host folders mounted.</p>`:''}
  ${profile==='writing'?`<label class="check-pill"><input data-field="style_judge_enabled" type="checkbox" ${form.style_judge_enabled?'checked':''}>Add an independent writing-quality judge</label>${form.style_judge_enabled?`<div class="source-field-pair"><label>Judge endpoint<input data-field="style_judge_endpoint" type="url" placeholder="http://127.0.0.1:8081/v1" value="${esc(form.style_judge_endpoint)}"></label><label>Judge model<input data-field="style_judge_model" value="${esc(form.style_judge_model)}"></label></div><label>Judge API key <span class="optional-label">optional</span><input data-field="style_judge_key" type="password" value="${esc(form.style_judge_key)}" autocomplete="off"><small>Kept in browser, app-session and worker memory; not saved in settings or reports. The configured judge receives the writing brief and response.</small></label>`:''}`:''}</div>`;
}

function isStandardProfile(){return !!state?.benchmark_library?.some(s=>s.id===form.profile);}
function standardControls(){
  const s=state.benchmark_library.find(s=>s.id===form.profile);if(!s)return '';
  return `<div class="capability-controls standard-controls"><div class="standard-label"><span class="badge ${s.ready?'':'warn'}">${s.ready?'Prepared locally':'Prepare before running'}</span><span>${esc(s.metric)}</span></div><p>${esc(s.description)}</p><p class="form-note">${esc(s.size)}. Preparation uses a private folder inside this app.</p>${!s.ready?`<button class="primary-button" data-action="prepare-suite" data-suite="${s.id}" ${busy()?'disabled':''}>${icon('upload')} Prepare ${esc(s.name)}</button>`:''}
  <label class="check-pill"><input data-field="standard_full" type="checkbox" ${form.standard_full?'checked':''}>Run the full configured split (${s.installed_count||s.count} questions)</label>
  ${!form.standard_full?`<label>Seeded sample size<input data-field="standard_limit" type="number" min="1" max="${s.installed_count||s.count}" value="${esc(form.standard_limit)}"><small>The same seed selects the same questions for every version and config. Sample results are labelled separately from full-split results.</small></label>`:''}
  <p class="form-note">Original benchmark categories are preserved. These questions have no assigned Easy–Extreme rating. Full coverage alone does not make settings identical to a published leaderboard run.</p>
  ${s.id==='writingbench'?`<div class="standard-warning">WritingBench requires a separate judge and normally makes five scoring calls per answer. The writing brief, response and rubric are sent to that endpoint. Compare only with the same judge and rubric.</div><div class="source-field-pair"><label>Judge endpoint<input data-field="style_judge_endpoint" type="url" value="${esc(form.style_judge_endpoint)}" placeholder="http://127.0.0.1:8081/v1"></label><label>Judge model<input data-field="style_judge_model" value="${esc(form.style_judge_model)}"></label></div><label>Judge API key <span class="optional-label">optional</span><input data-field="style_judge_key" type="password" autocomplete="off" value="${esc(form.style_judge_key)}"><small>Kept in memory, never in settings or reports. Writing quality uses rubric scores, with no arbitrary pass/fail threshold.</small></label>`:''}
  ${s.id==='swebench'?`<div class="standard-warning"><strong>Large, optional evaluation</strong><p>Plan for at least 120 GB free in Docker storage. Selected issue images download before the model loads; this can take substantial time and bandwidth. Full runs can take hours or days. Docker must run Linux containers. Image preparation is excluded from the estimate.</p></div><label>Maximum model turns per issue<input data-field="agent_turns" type="number" min="1" max="64" value="${esc(form.agent_turns)}"></label><label>Acceptance-test timeout per issue (seconds)<input data-field="swe_test_timeout" type="number" min="30" max="3600" value="${esc(form.swe_test_timeout)}"></label>`:''}</div>`;
}
function renderBenchmarkLibrary(){
  const suites=state.benchmark_library||[],swe=suites.find(s=>s.id==='swebench');
  return heading('STANDARD EVALUATIONS','A benchmark for each capability.','Prepare only what you need. Each suite keeps its source revision, evaluator and download inside this app.')+`<div class="benchmark-library-grid">${suites.filter(s=>!s.optional).map(s=>`<section class="card card-pad benchmark-library-card"><div class="standard-label"><span class="card-icon">${icon({ifeval:'document',bfcl:'sliders',mmmu:'monitor',writingbench:'book'}[s.id])}</span><span class="badge ${s.ready?'':'neutral'}">${s.ready?'Ready':'Not downloaded'}</span></div><h2>${esc(s.name)}</h2><p>${esc(s.description)}</p><dl><dt>Coverage</dt><dd>${s.installed_count||s.count} · ${esc(s.split)}</dd><dt>Scoring</dt><dd>${esc(s.metric)}</dd></dl><p class="form-note">${esc(s.size)}</p><button class="${s.ready?'secondary-button':'primary-button'}" data-action="${s.ready?'choose-standard':'prepare-suite'}" data-suite="${s.id}" ${busy()?'disabled':''}>${s.ready?'Use this suite':'Prepare suite'}</button>${s.ready?`<button class="text-button" data-action="prepare-suite" data-suite="${s.id}" ${busy()?'disabled':''}>Repair / reprepare</button>`:''}</section>`).join('')}</div><section class="card card-pad optional-swe"><div class="standard-label"><div><div class="eyebrow">OPTIONAL · LARGE DOWNLOAD</div><h2>SWE-bench Lite</h2></div><span class="badge ${swe?.enabled?'warn':'neutral'}">${swe?.enabled?'Enabled':'Off by default'}</span></div><p>Evaluate an agent on 300 real repository issues. Expect large Docker images and long runs. Normal setup and the other suites never download SWE-bench.</p><div class="standard-warning">Plan for at least 120 GB free in Docker storage. Images for the selected issues download when you explicitly start an enabled SWE-bench run. Preparing this library entry downloads the dataset and evaluator only.</div><label class="check-pill"><input id="optional-swebench" type="checkbox" ${swe?.enabled?'checked':''} ${busy()?'disabled':''}>Include optional SWE-bench in my suite choices</label><p class="form-note">Turning this on only reveals the suite. It does not download data or images. Turning it off preserves any existing downloads and saved results.</p>${swe?.enabled?`<button class="${swe.ready?'secondary-button':'primary-button'}" data-action="${swe.ready?'choose-standard':'prepare-suite'}" data-suite="swebench" ${busy()?'disabled':''}>${swe.ready?'Configure SWE-bench run':'Prepare SWE-bench dataset & evaluator'}</button>`:''}</section>`;
}

function showJudgeResume(run){showModal('Resume with the original writing judge',`<p>This run used ${esc(run.judge_model)} at ${esc(run.judge_endpoint)}. Its API key was kept in the previous app session’s memory. Re-enter that judge’s key to continue.</p><form data-resume-judge="${esc(run.id)}" class="modal-form"><label>Judge API key<input name="key" type="password" required autocomplete="off"></label><div class="inline-error" role="alert"></div><div class="modal-bottom"><button type="button" class="secondary-button" data-action="close-modal">Cancel</button><button type="submit" class="primary-button">Resume benchmark</button></div></form>`);}
document.addEventListener('submit',async event=>{const form=event.target.closest('[data-resume-judge]');if(!form)return;event.preventDefault();const button=$('[type="submit"]',form);button.disabled=true;try{await begin('/api/resume',{id:form.dataset.resumeJudge,style_judge_key:form.elements.key.value});$('#modal').close();}catch(error){$('.inline-error',form).textContent=error.message;button.disabled=false;}});
