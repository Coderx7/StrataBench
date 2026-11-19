const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(process.argv[2]||'stratabench/web/setup.js','utf8');
function fixture(setup={show_welcome:true,source_configured:false,has_versions:false,has_configs:false}){
  const events={},calls=[],shown=[],pages=[],feedback={textContent:''},picker={value:'chosen.zip'},preview={innerHTML:'old result'};
  const classes=new Set();
  const modal={open:false,dataset:{},classList:{add(v){classes.add(v)},remove(v){classes.delete(v)}},close(){this.open=false;}};
  const context=vm.createContext({console,state:{setup},document:{addEventListener(name,handler){(events[name]??=[]).push(handler)}},
    $(selector){return {'#modal':modal,'.welcome-error':feedback,'[data-source-field="asset"]':picker,'#source-release-preview':preview}[selector]},
    icon(){return '<svg></svg>';},esc(v){return String(v??'');},
    showModal(title,body){shown.push({title,body});modal.open=true;},
    api(path,data){calls.push({path,data});return Promise.resolve({ok:true});},navigate(page){pages.push(page);},toast(){}});
  vm.runInContext(source,context);
  return {context,events,calls,shown,pages,modal,feedback,picker,preview,run(code){return vm.runInContext(code,context)}};
}
test('first run explains all setup steps and never downloads or starts a model',()=>{
  const f=fixture();f.run('maybeShowSetupWelcome();maybeShowSetupWelcome()');
  assert.equal(f.shown.length,1);assert.equal(f.shown[0].title,'Welcome to StrataBench');
  for(const text of ['Configure Strata','Prepare your first version','Connect your model configuration'])assert.ok(f.shown[0].body.includes(text));
  assert.deepEqual(f.calls,[]);
});
test('Configure Strata acknowledges the welcome and opens settings',async()=>{
  const f=fixture();f.run('maybeShowSetupWelcome()');await f.run('dismissSetupWelcome(true)');
  assert.deepEqual(f.pages,['system']);assert.equal(f.modal.open,false);
  assert.equal(f.calls.length,1);assert.equal(f.calls[0].path,'/api/setup-welcome');
  assert.equal(f.context.state.setup.show_welcome,false);
});
test('Explore first closes the welcome without pretending setup is complete',async()=>{
  const f=fixture();f.run('maybeShowSetupWelcome()');await f.run('dismissSetupWelcome(false)');
  assert.deepEqual(f.pages,['new']);assert.equal(f.context.state.setup.has_versions,false);
  assert.ok(f.run('setupChecklist()').includes('Three steps to your first run.'));
});
test('existing users are not interrupted and another dialog is respected',()=>{
  const existing=fixture({show_welcome:false});existing.run('maybeShowSetupWelcome()');assert.equal(existing.shown.length,0);
  const other=fixture();other.modal.open=true;other.run('maybeShowSetupWelcome()');assert.equal(other.shown.length,0);
  other.modal.open=false;other.run('maybeShowSetupWelcome()');assert.equal(other.shown.length,1);
});
test('a failed acknowledgment keeps the welcome open with a useful error',async()=>{
  const f=fixture();f.context.api=()=>Promise.reject(Error('Settings could not be saved'));
  f.run('maybeShowSetupWelcome()');await f.run('dismissSetupWelcome(true)');
  assert.equal(f.modal.open,true);assert.deepEqual(f.pages,[]);assert.equal(f.feedback.textContent,'Settings could not be saved');
});
test('CMake options remain an array after typing and blurring the field',()=>{
  const f=fixture();f.run('sourceDraft={cmake_args:[]}');
  const field={dataset:{sourceField:'cmake_args'},value:'-DFOO=ON\n\n-DBAR=OFF\n',type:'textarea'};
  f.events.input[0]({target:field});f.events.change[0]({target:field});
  assert.equal(f.run('JSON.stringify(sourceDraft.cmake_args)'),JSON.stringify(['-DFOO=ON','-DBAR=OFF']));
});
test('checksum checkbox stays boolean and backend changes discard stale asset selections',()=>{
  const f=fixture();f.run('sourceDraft={asset:"chosen.zip"};sourceRelease={tag:"old"}');
  f.events.change[0]({target:{dataset:{sourceField:'allow_unverified'},checked:true,value:'on',type:'checkbox'}});
  assert.equal(f.run('sourceDraft.allow_unverified'),true);
  f.events.change[0]({target:{dataset:{sourceField:'backend'},value:'cuda13',type:'select'}});
  assert.equal(f.run('sourceDraft.asset'),'auto');assert.equal(f.run('sourceRelease'),null);
  assert.equal(f.picker.value,'auto');assert.equal(f.preview.innerHTML,'');
});
test('completed setup hides the checklist',()=>{
  const f=fixture({show_welcome:false,source_configured:true,has_versions:true,has_configs:true});
  assert.equal(f.run('setupChecklist()'),'');
});
