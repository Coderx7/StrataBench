const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=process.argv[2]||'.';
function fixture(){
 const elements=new Map(),calls=[];
 const document={addEventListener(){},querySelector(q){if(!elements.has(q))elements.set(q,{innerHTML:'',textContent:'',disabled:false,dataset:{},classList:{toggle(){}},setAttribute(){},addEventListener(){}});return elements.get(q)},querySelectorAll(){return []}};
 const context=vm.createContext({document,window:{addEventListener(){}},location:{protocol:'file:',hash:''},console,setTimeout(){},clearTimeout(){},setInterval(){},localStorage:{getItem(){},setItem(){}}});
 for(const name of ['app.js','outcomes.js','lab.js'])vm.runInContext(fs.readFileSync(path.join(root,'stratabench/web',name),'utf8'),context);
 context.calls=calls;
 vm.runInContext(`state={profiles:[{id:'full',name:'Full suite'}]};var thinkingDraft=null,thinkingCheckKey='';navigate=to=>{page=to};toast=()=>{};api=async(route,data)=>{calls.push({route,data});return {id:'saved',count:data.questions.length,edited:1,profile:'full'}};`,context);
 return {run:s=>vm.runInContext(s,context),calls,elements};
}
test('question rows and system prompt editor escape content and show default vs edited state',()=>{
 const f=fixture();f.run(`labDetail={id:'q<script>',prompt:'Question <img>',answer:42,images:[],system_prompt:'Default <prompt>'};labData={total:1,matched:1,groups:['math'],questions:[{id:'q<script>',preview:'Question <img>',difficulty:'easy',group:'math'}]};`);
 let html=f.run('renderLab()');assert.ok(html.includes('q&lt;script&gt;'));assert.ok(html.includes('Default &lt;prompt&gt;'));assert.ok(!html.includes('<img>'));assert.ok(html.includes('Use benchmark system prompt'));
 f.run(`labEdits.set(labDetail.id,'');labSelected.add(labDetail.id)`);html=f.run('labEditor()');assert.ok(html.includes('Your system prompt'));assert.ok(html.includes('blank custom prompt sends no system message'));assert.ok(!html.includes('id="lab-system" rows="10" maxlength="50000" dir="auto" disabled'));
});
test('selection handoff preserves an intentional empty override and does not start a benchmark',async()=>{
 const f=fixture();await f.run(`labCatalog='catalog';labSelected=new Set(['q1','q2']);labEdits.set('q1','');useLabSelection()`);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].route,'/api/question-selection');
 assert.deepEqual(JSON.parse(JSON.stringify(f.calls[0].data.questions)),[{id:'q1',system_override:''},{id:'q2'}]);
 assert.equal(f.run('form.selection_count'),2);assert.equal(f.run('form.selection_edited'),1);assert.equal(f.run('page'),'new');assert.equal(f.run('questionCount()'),2);
});
test('format-only outcomes remain a separate, clickable explanation of strict incorrect scores',()=>{
 const f=fixture();const html=f.run(`outcomeMetrics('run',{passed:1,incorrect:2,format_errors:1,pending:0,cutoffs:0,errors:0})`);
 assert.ok(html.includes('data-category="format_errors"'));assert.ok(html.includes('Correct content, wrong format'));assert.ok(html.includes('data-category="incorrect"'));
});
test('restoring advanced settings keeps the selected question seed fixed',()=>{
 const f=fixture();f.run(`form.selection_id='selection';form.seed=17;form.temperature=1;updateSummary=()=>{};resetAdvancedSettings()`);
 assert.equal(f.run('form.seed'),17);assert.equal(f.run('form.temperature'),0);
 assert.equal(f.run('customAdvancedFields().length'),0);
 assert.ok(f.run('renderAdvancedSettings()').includes('value="17" disabled'));
});
