'use strict';

let thinkingDraft=null,thinkingCheck=null,thinkingCheckKey='',thinkingCheckTimer,thinkingSettingsOpen=false;
function rememberThinkingSettings(){const panel=$('#thinking-settings');if(panel&&typeof panel.open==='boolean')thinkingSettingsOpen=panel.open;}
document.addEventListener('toggle',event=>{if(event.target.id==='thinking-settings'&&event.target.isConnected)thinkingSettingsOpen=event.target.open;},true);
const thinkingLabels={easy:'Easy',medium:'Medium',hard:'Hard',very_hard:'Very hard',extreme:'Extreme',unrated:'Original benchmark category'};
function displayedThinkingDefaults(){
  const base={...(state?.thinking_budget_defaults?.[form.profile]||{easy:1024,medium:3072,hard:7168,very_hard:11264,extreme:15360,unrated:7168})};
  if(form.max_tokens!==''&&form.max_tokens!=null){const total=Number(form.max_tokens),reserve=Math.min(1024,Math.max(1,Math.floor(total/2)));for(const key in base)base[key]=Math.max(1,Math.min(base[key],total-reserve));}
  return base;
}
function currentThinkingDraft(){return thinkingDraft||{useDefaults:form.use_default_thinking_budgets,values:{...form.thinking_budgets}};}
function thinkingPayload(){const draft=currentThinkingDraft();return {profile:form.profile,reasoning:form.reasoning,max_tokens:form.max_tokens,difficulties:[...form.difficulties],context_words:form.context_words,tasks_id:customTasks?.id,configs:[...selectedConfigs],use_default_thinking_budgets:draft.useDefaults,thinking_budgets:draft.useDefaults?displayedThinkingDefaults():draft.values};}
function thinkingSignature(){return JSON.stringify([thinkingPayload(),state?.configs.map(c=>[c.id,c.budget_context_limit??c.context])]);}
function thinkingChanged(){const draft=currentThinkingDraft();if(draft.useDefaults!==form.use_default_thinking_budgets)return true;if(draft.useDefaults)return false;return Object.keys(thinkingLabels).some(l=>Number(draft.values[l])!==Number(form.thinking_budgets[l]));}
function thinkingReady(){return !thinkingChanged()&&thinkingCheckKey===thinkingSignature()&&thinkingCheck&&!thinkingCheck.error&&!thinkingCheck.invalid.length;}
function renderThinkingBudgets(){
  rememberThinkingSettings();
  const draft=currentThinkingDraft(),values=draft.useDefaults?displayedThinkingDefaults():draft.values,defaults=displayedThinkingDefaults();
  const shown=isStandardProfile()?['unrated']:Object.keys(thinkingLabels).filter(l=>l!=='unrated');
  return `<details id="thinking-settings" class="advanced thinking-settings" ${thinkingSettingsOpen?'open':''}><summary><span>Thinking tokens by difficulty</span><span id="thinking-budget-overview" class="thinking-summary-meta">${draft.useDefaults?'Default limits':'Custom limits'}</span></summary><div class="thinking-panel"><label class="thinking-default-toggle"><input type="checkbox" aria-label="Use default thinking budgets" aria-describedby="thinking-default-description" id="thinking-use-defaults" ${draft.useDefaults?'checked':''}><span><strong>Use default thinking budgets</strong><small id="thinking-default-description">Recommended token limits for this suite.</small></span></label>${isStandardProfile()?'<p class="thinking-suite-note">This suite keeps its original categories. One budget applies to every question.</p>':''}<div class="thinking-budget-list" role="table" aria-label="Thinking token limits"><div class="thinking-budget-row thinking-budget-columns" role="row"><span role="columnheader">Difficulty</span><span role="columnheader">Default</span><span role="columnheader">Token limit</span></div>${shown.map(l=>`<div class="thinking-budget-row" role="row"><span class="thinking-level-name" role="cell">${l==='unrated'?'Original category':thinkingLabels[l]}</span><span class="thinking-default-value" data-thinking-default="${l}" role="cell">${formatNumber(defaults[l])}</span><label class="thinking-limit-cell" role="cell"><input aria-label="${thinkingLabels[l]} thinking tokens" data-thinking-level="${l}" type="number" min="1" max="1000000" step="1" value="${esc(values[l]??defaults[l])}" ${draft.useDefaults?'disabled':''}></label></div>`).join('')}</div><div id="thinking-budget-status" class="thinking-budget-status" aria-live="polite"></div><div class="thinking-actions"><button class="secondary-button" data-action="apply-thinking-budgets" hidden disabled>Apply budgets</button></div><details class="thinking-help"><summary>How limits and capacity checks work</summary><div><p>Limits apply per request or agent turn. Custom budgets leave another 1,024 tokens for the answer and wrap-up, unless you set an overall answer limit in Advanced settings. Reasoning Off ignores thinking caps.</p><p>Capacity checks reserve 1,024 prompt tokens against each config’s declared context window. Long prompts, images and conversation history may need more space; Strata checks the actual request when it runs.</p></div></details></div></details>`;
}
function paintThinkingStatus(){
  const box=$('#thinking-budget-status');if(!box)return;
  const button=$('[data-action="apply-thinking-budgets"]'),check=thinkingCheck,current=thinkingCheckKey===thinkingSignature();
  let text='Checking selected configurations…',kind='';
  if(current&&check){
    if(check.error){text=esc(check.error);kind='error';}
    else if(check.invalid.length){kind='warning';text=`<strong>${check.invalid.length} selected configuration${check.invalid.length===1?'':'s'} cannot fit these budgets</strong><ul>${check.invalid.map(c=>`<li><strong>${esc(c.name)}</strong><span>${formatNumber(c.context_limit)} context tokens; ${formatNumber(c.required_tokens)} needed for ${c.levels.map(l=>thinkingLabels[l]).join(', ')}.</span></li>`).join('')}</ul><p>Apply these budgets to deselect the incompatible configs and keep the others.</p>`;}
    else{text=thinkingChanged()?'Ready to apply. Selected configs fit these limits.':form.reasoning==='off'?'Reasoning is Off. Thinking limits are ignored.':'Selected configs fit these limits.';}
    if(!check.error&&check.unknown?.length)text+=`<p>Context size unknown for ${check.unknown.map(c=>esc(c.name)).join(', ')}. These configs stay selected; capacity will be checked at runtime.</p>`;
  }
  box.className='thinking-budget-status '+kind;box.innerHTML=text;
  const overview=$('#thinking-budget-overview');
  if(overview){const attention=current&&check&&(check.error||check.invalid?.length);overview.textContent=attention?'Needs attention':thinkingChanged()?'Unapplied changes':form.reasoning==='off'?'Reasoning off':form.use_default_thinking_budgets?'Default limits':'Custom limits';overview.className='thinking-summary-meta'+(attention?' attention':thinkingChanged()?' pending':'');}
  if(button){button.hidden=!thinkingChanged()&&!check?.invalid?.length;button.disabled=!current||!check||!!check.error||!thinkingChanged()&&!check.invalid.length;button.textContent=check?.invalid?.length?`Apply budgets & deselect ${check.invalid.length} incompatible config${check.invalid.length===1?'':'s'}`:'Apply budgets';}
  const draft=currentThinkingDraft();
  if(draft.useDefaults){const values=displayedThinkingDefaults();all('[data-thinking-level]').forEach(el=>{el.value=values[el.dataset.thinkingLevel];});all('[data-thinking-default]').forEach(el=>{el.textContent=formatNumber(values[el.dataset.thinkingDefault]);});}
}
function scheduleThinkingCheck(){
  if(!state||page!=='new')return;
  const key=thinkingSignature();if(key===thinkingCheckKey){paintThinkingStatus();return;}
  thinkingCheckKey=key;thinkingCheck=null;clearTimeout(thinkingCheckTimer);paintThinkingStatus();
  const payload=thinkingPayload();thinkingCheckTimer=setTimeout(async()=>{let result;try{result=await api('/api/budget-compatibility',payload);}catch(error){result={error:error.message};}if(key!==thinkingCheckKey)return;thinkingCheck=result;if(page==='new')updateSummary();},200);
}
async function applyThinkingBudgets(){
  const key=thinkingSignature(),payload=thinkingPayload();
  const check=await api('/api/budget-compatibility',payload);
  if(key!==thinkingSignature())return;
  form.use_default_thinking_budgets=payload.use_default_thinking_budgets;form.thinking_budgets=check.thinking_budgets;
  for(const config of check.invalid)selectedConfigs.delete(config.id);
  thinkingDraft=null;thinkingCheckKey='';render();
  toast(check.invalid.length?`Budgets applied. ${check.invalid.length} incompatible config(s) deselected${selectedConfigs.size?'.':'; select a compatible config to continue.'}`:'Thinking budgets applied.');
}
document.addEventListener('input',event=>{const el=event.target;if(!el.dataset.thinkingLevel)return;const draft=currentThinkingDraft();thinkingDraft={useDefaults:false,values:{...(draft.useDefaults?displayedThinkingDefaults():draft.values),[el.dataset.thinkingLevel]:el.value}};updateSummary();});
document.addEventListener('change',event=>{if(event.target.id!=='thinking-use-defaults')return;const draft=currentThinkingDraft();thinkingDraft={useDefaults:event.target.checked,values:{...(draft.useDefaults?displayedThinkingDefaults():draft.values)}};rememberThinkingSettings();const box=$('.thinking-settings');box.outerHTML=renderThinkingBudgets();updateSummary();});
