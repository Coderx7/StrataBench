const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const root=process.argv[2]||'.';
function fixture(){
 const elements=new Map(),listeners=new Map(),timers=[];
 const document={addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);},querySelector(q){if(!elements.has(q))elements.set(q,{dataset:{},writes:0,html:'',get innerHTML(){return this.html},set innerHTML(v){this.html=v;this.writes++},classList:{toggle(){}},setAttribute(){},addEventListener(){}});return elements.get(q)},querySelectorAll(){return []}};
 const context=vm.createContext({document,window:{addEventListener(){}},location:{protocol:'file:',hash:''},console,setTimeout(fn){timers.push(fn);return timers.length},clearTimeout(){},setInterval(){},WeakMap});
 for(const name of ['helpers','budgets','outcomes','setup','app'])vm.runInContext(fs.readFileSync(root+'/stratabench/web/'+name+'.js','utf8'),context);
 vm.runInContext(`state={configs:[{id:'small',context:128144},{id:'large',context:262144}],benchmark_library:[{id:'ifeval'}],profiles:[{id:'quick',name:'Quick'}],profile_counts:{quick:{easy:1,extreme:1}}};selectedConfigs=new Set(['small','large']);selectedVersions=new Set(['v1']);form.thinking_budgets=displayedThinkingDefaults();render=()=>{};updateSummary=()=>{};toast=()=>{};`,context);
 return {run(code){return vm.runInContext(code,context)},elements,listeners,timers,context};
}
test('default checkbox displays per-level values and unlocks initialized inputs',()=>{
 const f=fixture();let html=f.run('renderThinkingBudgets()');
 assert.ok(html.includes('id="thinking-use-defaults" checked'));assert.equal((html.match(/data-thinking-level=/g)||[]).length,5);
 assert.ok(html.includes('value="15360" disabled'));assert.ok(html.includes('data-thinking-default="extreme" role="cell">15,360</span>'));
 for(const change of f.listeners.get('change'))change({target:{id:'thinking-use-defaults',checked:false,dataset:{}}});
 html=f.run('renderThinkingBudgets()');assert.ok(html.includes('value="15360" >'));assert.ok(f.run('thinkingChanged()'));
 f.run("form.profile='ifeval'");html=f.run('renderThinkingBudgets()');assert.ok(html.includes('Original benchmark category thinking tokens'));assert.equal((html.match(/data-thinking-level=/g)||[]).length,1);
});
test('draft editing keeps selected configs until the explicit Apply action',async()=>{
 const f=fixture();f.run(`thinkingDraft={useDefaults:false,values:{...displayedThinkingDefaults(),extreme:180000}};
 api=async()=>({invalid:[{id:'small',name:'Small',context_limit:128144,required_tokens:182048,levels:['extreme']}],unknown:[],levels:['extreme'],thinking_budgets:thinkingDraft.values});thinkingCheckKey=thinkingSignature();`);
 f.run(`thinkingCheck={invalid:[{id:'small',name:'Small',context_limit:128144,required_tokens:182048,levels:['extreme']}],unknown:[],levels:['extreme']};paintThinkingStatus()`);
 assert.ok(f.elements.get('#thinking-budget-status').innerHTML.includes('Small'));
 assert.equal(f.elements.get('[data-action="apply-thinking-budgets"]').textContent,'Apply budgets & deselect 1 incompatible config');
 assert.equal(f.run('selectedConfigs.size'),2);assert.equal(f.run('thinkingReady()'),false);
 assert.equal(f.elements.get('#thinking-budget-overview').textContent,'Needs attention');
 assert.equal(f.run('thinkingSettingsOpen'),false);
 await f.run('applyThinkingBudgets()');assert.equal(f.run('selectedConfigs.has("small")'),false);assert.equal(f.run('selectedConfigs.has("large")'),true);
 assert.equal(f.run('form.thinking_budgets.extreme'),180000);assert.equal(f.run('form.use_default_thinking_budgets'),false);
});
test('changing drafts during a capacity request cannot apply stale removals',async()=>{
 const f=fixture();f.run(`thinkingDraft={useDefaults:false,values:{...displayedThinkingDefaults(),extreme:180000}};api=()=>new Promise(resolve=>{finishCheck=resolve});`);
 const applying=f.run('applyThinkingBudgets()');f.run('thinkingDraft.values.extreme=10000;finishCheck({invalid:[{id:"small"}],thinking_budgets:{extreme:180000}})');await applying;
 assert.equal(f.run('selectedConfigs.size'),2);assert.equal(f.run('form.use_default_thinking_budgets'),true);
});
test('errors block Apply and Start while unknown context can proceed',()=>{
 const f=fixture();f.run(`thinkingCheckKey=thinkingSignature();thinkingCheck={error:'Enter a whole token count.'};paintThinkingStatus()`);
 assert.equal(f.run('thinkingReady()'),false);assert.equal(f.elements.get('[data-action="apply-thinking-budgets"]').disabled,true);
 f.run(`thinkingCheck={invalid:[],unknown:[{name:'Unknown config'}],levels:['easy']};paintThinkingStatus()`);
 assert.equal(f.run('thinkingReady()'),true);assert.ok(f.elements.get('#thinking-budget-status').innerHTML.includes('Unknown config'));
});
test('time details preserve open and closed state across polling and replacement',()=>{
 const f=fixture(),details=f.elements.get('#time-by-config')||{};Object.assign(details,{id:'time-by-config',isConnected:true,open:true});f.elements.set('#time-by-config',details);
 f.run(`estimateData={rows:[{config:'small',version:'v1',name:'Small',lower_seconds:10,upper_seconds:20,local_sample_questions:0,warnings:[]}]};paintEstimates()`);
 const box=f.elements.get('#time-estimate-summary');assert.ok(box.innerHTML.includes('id="time-by-config" open'));
 const writes=box.writes;f.run('paintEstimates();paintEstimates();paintEstimates()');assert.equal(box.writes,writes);
 details.open=false;for(const fn of f.listeners.get('toggle'))fn({target:details});f.run('paintEstimates()');assert.ok(!box.innerHTML.includes('id="time-by-config" open'));
 // A delayed event from a removed details node cannot close its replacement.
 details.open=true;for(const fn of f.listeners.get('toggle'))fn({target:details});for(const fn of f.listeners.get('toggle'))fn({target:{id:'time-by-config',isConnected:false,open:false}});
 assert.equal(f.run('timeByConfigOpen'),true);
});

test('thinking controls start collapsed and preserve explicit expansion while editing',()=>{
 const f=fixture();assert.ok(!f.run('renderThinkingBudgets()').match(/<details id="thinking-settings"[^>]*\bopen\b/));
 const panel={id:'thinking-settings',open:true,isConnected:true};f.elements.set('#thinking-settings',panel);
 for(const toggle of f.listeners.get('toggle'))toggle({target:panel});
 assert.ok(f.run('renderThinkingBudgets()').match(/<details id="thinking-settings"[^>]*\bopen\b/));
 for(const change of f.listeners.get('change'))change({target:{id:'thinking-use-defaults',checked:false,dataset:{}}});
 assert.ok(f.elements.get('.thinking-settings').outerHTML.match(/<details id="thinking-settings"[^>]*\bopen\b/));
 f.run('thinkingCheckKey=thinkingSignature();thinkingCheck={invalid:[],unknown:[]};paintThinkingStatus()');
 assert.equal(f.elements.get('#thinking-budget-overview').textContent,'Unapplied changes');
 panel.open=false;for(const toggle of f.listeners.get('toggle'))toggle({target:panel});
 assert.ok(!f.run('renderThinkingBudgets()').match(/<details id="thinking-settings"[^>]*\bopen\b/));
 panel.open=true;for(const toggle of f.listeners.get('toggle'))toggle({target:panel});
 for(const toggle of f.listeners.get('toggle'))toggle({target:{id:'thinking-settings',isConnected:false,open:false}});
 assert.equal(f.run('thinkingSettingsOpen'),true);
});
