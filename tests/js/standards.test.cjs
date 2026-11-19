const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const root=process.argv[2]||'.';
function fixture(enabled=false){
  const suites=[['ifeval','IFEval',541],['bfcl','BFCL',1000],['mmmu','MMMU',900],['writingbench','WritingBench',1000],['swebench','SWE-bench',300]].map(([id,name,count])=>({id,name,count,optional:id==='swebench',enabled:id!=='swebench'||enabled,ready:false,description:'Published dataset',metric:'Metric',size:'Private download',split:'Original split'}));
  const context=vm.createContext({state:{benchmark_library:suites},form:{profile:'ifeval',standard_full:false,standard_limit:12,agent_turns:30,swe_test_timeout:900},document:{addEventListener(){}},
    icon(){return '<svg></svg>';},esc(v){return String(v??'');},busy(){return false;},heading(a,b,c){return a+b+c;}});
  vm.runInContext(fs.readFileSync(root+'/stratabench/web/helpers.js','utf8'),context);
  return {run(code){return vm.runInContext(code,context);}};
}
test('SWE stays off with no preparation action until explicitly enabled',()=>{
  const f=fixture();const html=f.run('renderBenchmarkLibrary()');
  assert.ok(html.includes('Off by default'));assert.ok(html.includes('120 GB'));
  assert.ok(!html.includes('data-suite="swebench"'));assert.ok(!html.includes('id="optional-swebench" type="checkbox" checked'));
  const enabled=fixture(true).run('renderBenchmarkLibrary()');
  assert.ok(enabled.includes('Prepare SWE-bench dataset & evaluator'));assert.ok(enabled.includes('data-suite="swebench"'));
});
test('standard controls distinguish full coverage from seeded samples',()=>{
  const f=fixture();let html=f.run('standardControls()');
  assert.ok(html.includes('Seeded sample size'));assert.ok(html.includes('value="12"'));assert.ok(html.includes('no assigned Easy'));
  html=f.run('form.standard_full=true;standardControls()');assert.ok(!html.includes('Seeded sample size'));assert.ok(html.includes('541 questions'));
});
test('writing quality requires a separate judge and has no pass threshold',()=>{
  const f=fixture();const html=f.run("form.profile='writingbench';standardControls()");
  assert.ok(html.includes('Judge endpoint'));assert.ok(html.includes('five scoring calls'));assert.ok(html.includes('no arbitrary pass/fail threshold'));
});
