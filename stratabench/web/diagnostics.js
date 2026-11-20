'use strict';

let diagnosticSequence=0,diagnosticLogSequence=0,diagnosticScope=null;
function failureNote(item,scope){return item?.failure_reason?`<div class="failure-note"><span>${esc(item.failure_reason)}</span><button class="text-button" data-action="diagnostics" ${scope.run?`data-run="${esc(scope.run)}"`:`data-job="${esc(scope.job)}"`}>View error & logs ${icon('external')}</button></div>`:'';}
function failedOperationCards(exclude=''){
  const jobs=(state.failed_operations||[]).filter(j=>j.id!==exclude);if(!jobs.length)return '';
  return `<section class="card failed-operation-list"><div class="section-title"><div><h2>Launch & preparation errors</h2><p>Saved details are available even when a benchmark could not start.</p></div></div>${jobs.map(j=>`<div class="failed-operation"><div><strong>${esc(j.title)}</strong><small>${esc(dateText(j.started_at*1000))}</small>${failureNote(j,{job:j.id})}</div>${statusBadge(j.state,{job:j.id})}</div>`).join('')}</section>`;
}
function diagnosticDownloadURL(scope,log){const args=Object.entries({...scope,log}).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');return '/api/diagnostic-log/download?'+args;}
async function openDiagnostics(scope){
  const sequence=++diagnosticSequence;diagnosticLogSequence++;diagnosticScope=scope;detailSelection=null;detailSequence++;
  showModal('Benchmark details',`<div class="explorer-loading"><div class="spinner"></div> Reading saved errors and logs…</div>`);$('#modal').classList.add('diagnostic-dialog');
  try{
    const data=await api('/api/diagnostics',scope);
    if(sequence!==diagnosticSequence||!$('#modal').open)return;
    $('#modal-content').innerHTML=`<div class="modal-top"><div><div class="eyebrow">ERROR DETAILS & LOGS</div><h2>${esc(data.title)}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close')}</button></div><div class="modal-body diagnostic-body"><section class="diagnostic-reason"><span class="card-icon">${icon('activity')}</span><div><h3>${esc(data.reason)}</h3><p>${data.issues.length?'Saved errors are shown below. Select a log to see the surrounding output.':'The available logs are listed below. Test-level outcomes remain in the test explorer.'}</p></div></section>${data.issues.length?`<section class="diagnostic-issues"><h3>Saved errors <span class="meta-chip">${data.issues.length}${data.issues.length===100?'+':''}</span></h3>${data.issues.map((issue,i)=>`<details ${i===0?'open':''}><summary>${esc(issue.label)}</summary><pre dir="auto">${esc(issue.message)}</pre></details>`).join('')}</section>`:''}<section class="diagnostic-logs"><div class="diagnostic-log-toolbar"><label for="diagnostic-log-select">Saved log<select id="diagnostic-log-select" ${data.logs.length?'':'disabled'}>${data.logs.length?data.logs.map(log=>`<option value="${esc(log.id)}">${esc(log.label)} · ${formatNumber(Math.ceil(log.bytes/1024))} KB</option>`).join(''):'<option>No log files were saved</option>'}</select></label><button class="secondary-button" data-action="refresh-diagnostic-log" ${data.logs.length?'':'disabled'}>${icon('refresh')} Refresh log</button><a class="secondary-button" id="diagnostic-download" hidden download>Download full log ${icon('external')}</a></div><p id="diagnostic-log-notice" class="form-note">${data.logs.length?'Reading the selected log…':'Older runs may have saved errors without activity logs. Logs are captured automatically for new operations.'}</p><pre id="diagnostic-log-text" class="diagnostic-log-output" tabindex="0" dir="auto">${data.logs.length?'Loading…':'No saved log is available for this operation.'}</pre></section>${data.run?`<div class="diagnostic-footer"><button class="secondary-button" data-action="diagnostic-tests" data-run="${esc(data.run)}">Inspect individual tests</button></div>`:''}</div>`;
    if(data.logs.length)await loadDiagnosticLog(data.logs[0].id);
  }catch(error){if(sequence===diagnosticSequence&&$('#modal').open)$('#modal-content').innerHTML=`<div class="modal-top"><h2>Could not read benchmark details</h2><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close')}</button></div><div class="modal-body"><p>${esc(error.message)}</p></div>`;}
}
async function loadDiagnosticLog(log){
  const sequence=++diagnosticLogSequence,scope=diagnosticScope;
  const output=$('#diagnostic-log-text'),link=$('#diagnostic-download');if(!output||!scope)return;
  output.textContent='Reading log…';link.hidden=true;
  try{
    const data=await api('/api/diagnostic-log',{...scope,log});
    if(sequence!==diagnosticLogSequence||scope!==diagnosticScope||!$('#modal').open)return;
    output.textContent=data.text||'This log is empty.';
    $('#diagnostic-log-notice').textContent=data.truncated?'Showing the last 256 KB. Download full log to read the complete saved output.':'Showing the complete saved log. Runtime credentials are redacted where identifiable.';
    link.href=diagnosticDownloadURL(scope,log);link.hidden=false;output.scrollTop=0;
  }catch(error){if(sequence===diagnosticLogSequence&&$('#modal').open){output.textContent=error.message;$('#diagnostic-log-notice').textContent='The log could not be read.';}}
}
document.addEventListener('click',event=>{
  const button=event.target.closest?.('[data-action]');if(!button||button.disabled)return;
  if(button.dataset.action==='refresh-diagnostic-log')loadDiagnosticLog($('#diagnostic-log-select').value);
  if(button.dataset.action==='diagnostics')openDiagnostics(button.dataset.run?{run:button.dataset.run}:{job:button.dataset.job});
  if(button.dataset.action==='diagnostic-tests'){$('#modal').close();openExplorer(button.dataset.run,'all');}
});
document.addEventListener('change',event=>{if(event.target.id==='diagnostic-log-select')loadDiagnosticLog(event.target.value);});
document.addEventListener('close',event=>{if(event.target.id==='modal'){diagnosticSequence++;diagnosticLogSequence++;diagnosticScope=null;event.target.classList.remove('diagnostic-dialog');}},true);
