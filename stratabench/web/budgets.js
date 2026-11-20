'use strict';

let thinkingDraft=null,thinkingCheck=null,thinkingCheckKey='',thinkingCheckTimer;
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
  const draft=currentThinkingDraft(),values=draft.useDefaults?displayedThinkingDefaults():draft.values,defaults=displayedThinkingDefaults();
  const shown=Object.keys(thinkingLabels).filter(l=>l!=='unrated'||isStandardProfile());
  return `<section class="thinking-settings" aria-labelledby="thinking-title"><div class="thinking-heading"><div><h3 id="thinking-title">Thinking tokens by difficulty</h3><p>Set how long the model can think before writing its answer.</p></div><span class="meta-chip">Per request / agent turn</span></div><label class="thinking-default-toggle"><input type="checkbox" id="thinking-use-defaults" ${draft.useDefaults?'checked':''}>Use default thinking budgets</label><div class="thinking-budget-grid">${shown.map(l=>`<label class="thinking-budget-field"><span>${thinkingLabels[l]}</span><input aria-label="${thinkingLabels[l]} thinking tokens" data-thinking-level="${l}" type="number" min="1" max="1000000" step="1" value="${esc(values[l]??defaults[l])}" ${draft.useDefaults?'disabled':''}><small data-thinking-default="${l}">Default: ${formatNumber(defaults[l])} tokens</small></label>`).join('')}</div><p class="form-note">${isStandardProfile()?'This standard suite uses its original categories; the “Original benchmark category” budget applies to every question. ':''}Custom budgets automatically leave another 1,024 tokens for the answer and wrap-up, unless you set an overall answer limit below. Reasoning Off ignores thinking caps.</p><div id="thinking-budget-status" class="thinking-budget-status" aria-live="polite"></div><button class="secondary-button" data-action="apply-thinking-budgets" disabled>Apply budgets</button><p class="thinking-capacity-note">Capacity checks reserve 1,024 prompt tokens against each config’s declared context window. Long prompts, images and conversation history may need more space; Strata checks the actual request when it runs.</p></section>`;
}
function paintThinkingStatus(){
  const box=$('#thinking-budget-status');if(!box)return;
  const button=$('[data-action="apply-thinking-budgets"]'),check=thinkingCheck,current=thinkingCheckKey===thinkingSignature();
  let text='Checking selected configurations…',kind='';
  if(current&&check){
    if(check.error){text=esc(check.error);kind='error';}
    else if(check.invalid.length){kind='warning';text=`<strong>${check.invalid.length} selected configuration${check.invalid.length===1?'':'s'} cannot fit these budgets</strong><ul>${check.invalid.map(c=>`<li><strong>${esc(c.name)}</strong><span>${formatNumber(c.context_limit)} context tokens; ${formatNumber(c.required_tokens)} needed for ${c.levels.map(l=>thinkingLabels[l]).join(', ')}.</span></li>`).join('')}</ul><p>Apply these budgets to deselect the incompatible configs and keep the others.</p>`;}
    else{text=thinkingChanged()?'Ready to apply. Selected configurations fit these budgets.':form.reasoning==='off'?'Reasoning is Off. Thinking budgets are saved but ignored.':'Budgets applied. Selected configurations fit these budgets.';}
    if(!check.error&&check.unknown?.length)text+=`<p>Context size unknown for ${check.unknown.map(c=>esc(c.name)).join(', ')}. These configs stay selected; capacity will be checked at runtime.</p>`;
    if(!check.error&&check.levels?.length)text+=`<small>Checked: ${check.levels.map(l=>thinkingLabels[l]).join(', ')}.</small>`;
  }
  box.className='thinking-budget-status '+kind;box.innerHTML=text;
  if(button){button.disabled=!current||!check||!!check.error||!thinkingChanged()&&!check.invalid.length;button.textContent=check?.invalid?.length?`Apply budgets & deselect ${check.invalid.length} incompatible config${check.invalid.length===1?'':'s'}`:'Apply budgets';}
  const draft=currentThinkingDraft();
  if(draft.useDefaults){const values=displayedThinkingDefaults();all('[data-thinking-level]').forEach(el=>{el.value=values[el.dataset.thinkingLevel];});all('[data-thinking-default]').forEach(el=>{el.textContent='Default: '+formatNumber(values[el.dataset.thinkingDefault])+' tokens';});}
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
document.addEventListener('change',event=>{if(event.target.id!=='thinking-use-defaults')return;const draft=currentThinkingDraft();thinkingDraft={useDefaults:event.target.checked,values:{...(draft.useDefaults?displayedThinkingDefaults():draft.values)}};const box=$('.thinking-settings');box.outerHTML=renderThinkingBudgets();updateSummary();});
