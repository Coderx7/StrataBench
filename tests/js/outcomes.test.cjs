const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=process.argv[2]||'.';
function fixture(saved){
 const elements=new Map(),storage=new Map(saved?[['stratabench-test-layout',saved]]:[]);
 const document={addEventListener(){},querySelector(q){if(!elements.has(q))elements.set(q,{dataset:{},innerHTML:'',classList:{toggle(){}},setAttribute(){},addEventListener(){}});return elements.get(q)},querySelectorAll(){return []}};
 const context=vm.createContext({document,window:{addEventListener(){}},location:{protocol:'file:',hash:''},console,
  localStorage:{getItem(k){return storage.get(k)},setItem(k,v){storage.set(k,v)}},setTimeout(){},clearTimeout(){},setInterval(){}});
 vm.runInContext(fs.readFileSync(path.join(root,'stratabench/web/app.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(root,'stratabench/web/outcomes.js'),'utf8'),context);
 context.tests=[{key:'0.1.0',case_id:'task/<unsafe>',label:'v1 / config',preview:'Question <b>text</b>',status:'passed',difficulty:'easy',repeat:1,attempts:1,elapsed_seconds:2,group:'test'},
 {key:'0.2.0',case_id:'second',label:'v1 / config',preview:'Other question',status:'errors',difficulty:'hard',repeat:2,attempts:2,elapsed_seconds:3,group:'test'}];
 return {run(code){return vm.runInContext(code,context)},storage,elements};
}
test('grid remains the default and list includes the same test identities',()=>{
 const f=fixture();const grid=f.run('renderTestCollection(tests)');assert.ok(grid.includes('test-card-grid'));
 f.run('setExplorerLayout("list")');const list=f.run('renderTestCollection(tests)');assert.ok(list.includes('test-list-row'));
 for(const id of ['0.1.0','0.2.0']){assert.ok(grid.includes(`data-test-key="${id}"`));assert.ok(list.includes(`data-test-key="${id}"`));}
 assert.ok(list.includes('Request errors'));assert.ok(list.includes('Repeat 2'));assert.ok(list.includes('2 attempts'));
 assert.ok(list.includes('&lt;unsafe&gt;'));assert.ok(!list.includes('<b>text</b>'));
});
test('layout preference is persisted and loaded without changing filters or pagination',()=>{
 const f=fixture();f.run('explorerOffset=30;explorerFilters.search="keep this";setExplorerLayout("list")');
 assert.equal(f.storage.get('stratabench-test-layout'),'list');assert.equal(f.run('explorerOffset'),30);assert.equal(f.run('explorerFilters.search'),'keep this');
 assert.equal(fixture('list').run('explorerLayout'),'list');assert.equal(fixture('invalid').run('explorerLayout'),'grid');
 f.run('setExplorerLayout("invalid")');assert.equal(f.run('explorerLayout'),'list');
});
