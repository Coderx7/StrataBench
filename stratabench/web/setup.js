/* Source preferences are separate from model configuration and saved run provenance. */
let sourceDraft=null, sourceRelease=null, sourceBusy=false;
const sourceMethods={
  local:{name:'Existing build',icon:'layers',detail:'Copy an engine and its matching server from an existing Strata folder.'},
  release:{name:'Portable release',icon:'external',detail:'Download a compatible engine package and matching server. No compiler needed.'},
  repository:{name:'Clone & build',icon:'sliders',detail:'Fetch a revision from a Git repository and build it in a separate folder.'},
  folder:{name:'Build from folder',icon:'document',detail:'Build a committed revision from a local Git checkout. Your checkout stays in place.'}
};
function renderSystem(){return renderHardwareSetup();}
function renderSourceSettings(){
  if(!sourceDraft)sourceDraft={...state.strata_source,cmake_args:[...(state.strata_source?.cmake_args||[])]};
  const c=sourceDraft,method=c.method||'release',build=['repository','folder'].includes(method);
  return `<section class="card source-settings"><div class="source-settings-head"><div><div class="eyebrow">STRATA CONNECTION</div><h2>Your engine. Your source.</h2><p>Choose how versions are prepared. Model weights are configured separately.</p></div><span class="badge neutral">${esc(state.platform||'Local machine')}</span></div>
  <div class="source-methods">${Object.entries(sourceMethods).map(([key,m])=>`<button class="source-method ${method===key?'selected':''}" data-source-method="${key}" aria-pressed="${method===key}"><span class="card-icon">${icon(m.icon)}</span><strong>${m.name}</strong><span>${m.detail}</span>${method===key?'<span class="source-selected">'+icon('check')+' Selected</span>':''}</button>`).join('')}</div>
  <form id="source-settings-form"><div class="source-fields">
  ${['release','repository'].includes(method)?`<label>Strata Git repository<input data-source-field="repository" type="url" value="${esc(c.repository||'')}" placeholder="https://github.com/Niko1221/Strata.git" required><small>${method==='release'?'GitHub release API; only portable ZIP or tar archives are used. Installers are not run.':'An HTTPS Git repository. Sources are cloned into the app’s own cache.'}</small></label>`:''}
  ${['local','folder'].includes(method)?`<label>${method==='local'?'Existing Strata installation':'Strata Git source folder'}<div class="source-path-row"><input data-source-field="folder" value="${esc(c.folder||'')}" placeholder="${state.platform==='Windows'?'C:\\Models\\Strata':'/path/to/Strata'}" required>${method==='local'?'<button type="button" class="secondary-button" data-source-action="detect">Detect</button>':''}</div><small>${method==='local'?'Supports both the original layout and the newer terminal/ layout.':'The revision must already be present in this repository. Uncommitted changes are not included.'}</small></label>`:''}
  <label>Model configuration folder <span class="optional-label">optional</span><input data-source-field="config_folder" value="${esc(c.config_folder||'')}" placeholder="Folder containing strata-*.json"><small>Keep model paths separate from engine sources. You can also import individual JSON configs in New benchmark.</small></label>
  ${method==='release'?`<div class="source-field-pair"><label>Binary backend<select data-source-field="backend">${Object.entries({cuda12:'NVIDIA · CUDA 12',cuda13:'NVIDIA · CUDA 13',hip:'AMD · HIP',sycl:'Intel · SYCL'}).map(([k,v])=>`<option value="${k}" ${c.backend===k?'selected':''}>${v}</option>`).join('')}</select><small>Choose a backend supported by your GPU and driver.</small></label><label>Portable asset<select data-source-field="asset"><option value="auto">Auto · matching OS, architecture & backend</option>${[...new Set([c.asset,...(sourceRelease?.assets||[]).map(a=>a.name)])].filter(x=>x&&x!=='auto').map(name=>`<option value="${esc(name)}" ${c.asset===name?'selected':''}>${esc(name)}</option>`).join('')}</select><small>Check a release below to list compatible files. Auto requires one matching asset.</small></label></div><label class="source-checkbox"><input type="checkbox" data-source-field="allow_unverified" ${c.allow_unverified?'checked':''}><span>Allow portable packages with no published SHA-256 checksum<small>Published checksums are always verified. Leave this off to require one.</small></span></label>`:''}
  ${build?`<div class="source-field-pair"><label>Parallel build jobs<input data-source-field="build_jobs" type="number" min="1" max="64" value="${esc(c.build_jobs||4)}"><small>Four is a reasonable starting point.</small></label><label>CUDA architecture<input data-source-field="cuda_architectures" value="${esc(c.cuda_architectures||'native')}" placeholder="native"><small>native detects your GPU. RTX 3080: 86. Multiple targets: 86;89.</small></label></div><label>Extra CMake definitions <span class="optional-label">one per line</span><textarea data-source-field="cmake_args" rows="2" placeholder="-DNAME=value">${esc((c.cmake_args||[]).join('\n'))}</textarea><small>Source builds currently use the CUDA backend and your existing CMake, CUDA Toolkit, and C++ compiler.</small></label>`:''}
  <div class="source-field-pair"><label>Strata Python environment<select data-source-field="python_mode"><option value="managed" ${c.python_mode==='managed'?'selected':''}>Create an isolated environment per version</option><option value="existing" ${c.python_mode==='existing'?'selected':''}>Reuse an existing environment</option></select><small>Isolated mode installs runtime requirements inside versions/. It does not change global packages.</small></label><label>Python executable <span class="optional-label">optional</span><input data-source-field="python" value="${esc(c.python||'')}" placeholder="Auto-detect Python"><small>Existing mode checks the installation’s .venv, then the app’s Python. In isolated mode, this interpreter creates the environment.</small></label></div>
  </div><div id="source-feedback" class="source-feedback" role="status"></div>
  <div class="source-prepare-row"><label>${method==='local'?'Build label':'Version / revision'}<input id="source-tag" value="${esc(sourceRelease?.tag||(method==='local'?'local-build':method==='release'?'latest':'main'))}" placeholder="${method==='local'?'my-build':'v0.1.45'}"><small>${method==='release'?'A published tag or latest.':method==='local'?'Names the existing engine; it does not select another revision.':'A tag, commit, or branch name (such as main). latest is a release-only shortcut.'}</small></label>${method==='release'?'<button type="button" class="secondary-button" data-source-action="probe">'+icon('search')+' Check release</button>':''}</div>
  <div id="source-release-preview">${sourceReleasePreview()}</div><div class="source-settings-actions"><button type="submit" class="secondary-button" ${sourceBusy?'disabled':''}>${icon('check')} Save settings</button><button type="button" class="primary-button" data-source-action="prepare" ${busy()||sourceBusy?'disabled':''}>${icon('play')} Save & prepare version</button></div>
  <div class="insight-box">${icon('shield')}<span>Sources, binaries, and isolated Python environments stay inside this app’s versions folder. No drivers or system packages are installed. Prepared versions and saved benchmark settings keep their original identities.</span></div></form></section>`;
}
function sourceReleasePreview(){return sourceRelease?`<div class="release-preview"><strong>${esc(sourceRelease.tag)} · ${sourceRelease.assets.length} compatible portable ${sourceRelease.assets.length===1?'asset':'assets'}</strong>${sourceRelease.assets.length?sourceRelease.assets.map(a=>`<div><span>${esc(a.name)}</span><small>${(a.bytes/1024/1024).toFixed(1)} MB · ${a.digest?'SHA-256 published':'Check release checksum file'}</small></div>`).join(''):'<p>No portable engine matches this OS, architecture, and backend. Choose another backend/tag, use an existing build, or build from source.</p>'}</div>`:'';}
function sourceFeedback(message,error=false){const el=$('#source-feedback');if(el){el.textContent=message;el.classList.toggle('error',error);}}
async function saveSource(){await api('/api/strata-source',sourceDraft);await refresh();sourceFeedback('Settings saved. Prepared versions and saved runs keep their original settings.');}
document.addEventListener('input',event=>{const el=event.target,key=el.dataset.sourceField;if(!key)return;sourceDraft[key]=key==='cmake_args'?el.value.split('\n').map(s=>s.trim()).filter(Boolean):el.type==='checkbox'?el.checked:el.value;if(['repository','backend'].includes(key))sourceRelease=null;});
document.addEventListener('change',event=>{const el=event.target,key=el.dataset.sourceField;if(key)sourceDraft[key]=el.type==='checkbox'?el.checked:el.value;});
document.addEventListener('submit',async event=>{if(event.target.id!=='source-settings-form')return;event.preventDefault();try{await saveSource();toast('Strata source settings saved.');}catch(error){sourceFeedback(error.message,true);}});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.sourceMethod){sourceDraft.method=button.dataset.sourceMethod;sourceRelease=null;render();return;}
  const action=button.dataset.sourceAction;if(!action)return;
  button.disabled=true;
  try{
    if(action==='detect'){
      const data=await api('/api/strata-detect',{folder:sourceDraft.folder});
      if(!data.candidates.length){sourceFeedback('No complete build was found in the selected folder, PATH, STRATA_HOME, or adjacent Strata folders. Enter its folder explicitly.',true);return;}
      sourceDraft.folder=data.candidates[0].folder;if(!sourceDraft.config_folder)sourceDraft.config_folder=sourceDraft.folder;render();sourceFeedback('Found '+data.candidates[0].engine);return;
    }
    if(action==='probe'){
      const tag=$('#source-tag').value.trim();sourceFeedback('Checking the selected GitHub release…');
      sourceRelease=await api('/api/strata-release',{...sourceDraft,tag});render();sourceFeedback('Release checked. Nothing was downloaded or run.');return;
    }
    if(action==='prepare'){
      const tag=$('#source-tag').value.trim();if(!tag)throw Error('Enter a version tag or build label first.');
      await saveSource();await begin('/api/add-version',{tag,jobs:sourceDraft.build_jobs});
    }
  }catch(error){sourceFeedback(error.message,true);toast(error.message,true);}finally{button.disabled=false;}
});
