const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const root=process.argv[2]||'.';
function fixture(){
 const elements=new Map(),listeners={};
 const node=()=>({innerHTML:'',textContent:'',hidden:false,open:true,classList:{add(){},remove(){}},addEventListener(){},showModal(){this.open=true}});
 const document={addEventListener(k,fn){(listeners[k]??=[]).push(fn)},querySelector(q){if(!elements.has(q))elements.set(q,node());return elements.get(q)},querySelectorAll(){return []}};
 const context=vm.createContext({document,window:{addEventListener(){}},location:{protocol:'file:',hash:''},console,setTimeout(){},clearTimeout(){},setInterval(){}});
 for(const name of ['app','outcomes','diagnostics'])vm.runInContext(fs.readFileSync(root+'/stratabench/web/'+name+'.js','utf8'),context);
 return {run(code){return vm.runInContext(code,context)},elements,listeners,context};
}
test('statuses are actionable and failure text cannot become HTML',()=>{
 const f=fixture();let html=f.run('statusBadge("failed",{run:"run-test"})');
 assert.ok(html.includes('<button'));assert.ok(html.includes('data-action="diagnostics"'));assert.ok(html.includes('data-run="run-test"'));
 html=f.run('failureNote({failure_reason:"<script>bad</script>"},{job:"abc"})');assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
});
test('details show saved errors and make the full log downloadable',async()=>{
 const f=fixture();f.run(`api=async(path)=>path==='/api/diagnostics'?{title:'Model failed',reason:'CUDA out of memory',issues:[{label:'v1 / config',message:'<error>'}],logs:[{id:'log1',label:'Engine log',bytes:900000}],run:'run-test'}:{text:'<untrusted log text>',truncated:true};`);
 await f.run('openDiagnostics({run:"run-test"})');const html=f.elements.get('#modal-content').innerHTML;
 assert.ok(html.includes('CUDA out of memory'));assert.ok(html.includes('&lt;error&gt;'));
 assert.equal(f.elements.get('#diagnostic-log-text').textContent,'<untrusted log text>');
 assert.ok(f.elements.get('#diagnostic-log-notice').textContent.includes('last 256 KB'));
 assert.equal(f.elements.get('#diagnostic-download').hidden,false);assert.ok(f.elements.get('#diagnostic-download').href.includes('run=run-test&log=log1'));
});
test('late log responses cannot replace a newer selection',async()=>{
 const f=fixture();f.run(`diagnosticScope={run:'run-test'};pending=[];api=()=>new Promise(resolve=>pending.push(resolve));`);
 const first=f.run('loadDiagnosticLog("first")'),second=f.run('loadDiagnosticLog("second")');
 f.run('pending[1]({text:"new selection",truncated:false})');await second;
 f.run('pending[0]({text:"old selection",truncated:false})');await first;
 assert.equal(f.elements.get('#diagnostic-log-text').textContent,'new selection');assert.ok(f.elements.get('#diagnostic-download').href.endsWith('log=second'));
});
test('pre-run failures remain visible in the saved error list',()=>{
 const f=fixture();f.run(`state={failed_operations:[{id:'a',title:'Could not load',state:'failed',started_at:1,failure_reason:'Missing model weights'}]};`);
 const html=f.run('failedOperationCards()');assert.ok(html.includes('Missing model weights'));assert.ok(html.includes('data-job="a"'));
});
