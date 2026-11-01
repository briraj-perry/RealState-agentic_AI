/* Local, dependency-free dashboard. All business data comes from the FastAPI backend. */
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icons = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  properties:'<path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7M6 10h2m8 0h2"/>',
  conversations:'<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z"/><path d="M7 9h10M7 13h6"/>',
  test:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="m20 2 .5 1.5L22 4l-1.5.5L20 6l-.5-1.5L18 4l1.5-.5Z"/>',
  settings:'<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  visit:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2"/>',
  human:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  arrow:'<path d="M5 19 19 5M5 5h14v14"/>',
  send:'<path d="m3 3 18 9-18 9 3-9Zm3 9h15"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.test}</svg>`;
const pages = {overview:'Overview', properties:'Properties', conversations:'Conversations', test:'Test Your Agent', settings:'Settings'};
const state = {key:sessionStorage.getItem('estate-admin') || '', status:null, page:'overview', nonce:0,
  properties:[], templates:[], propertyFilter:'all', customers:[], selectedPhone:null, conversationTab:'messages', overviewSnapshot:null,
  testPhone:sessionStorage.getItem('estate-test-phone'), testSessions:[], pending:{}, timer:null};
let toastTimer;
const photoCache = new Map();
let draftPhotos=[], draftFiles=[], draftPropertyId=null;
let inventoryImport=null, importReview=null;
async function loadPhoto(photo) {
  if(photoCache.has(photo.id))return photoCache.get(photo.id);
  const response=await fetch('/api/property-photos/'+encodeURIComponent(photo.id),{headers:{'X-API-Key':state.key}});
  if(!response.ok)throw new Error('Could not load a property photo.');
  const url=URL.createObjectURL(await response.blob());photoCache.set(photo.id,url);return url;
}
async function preloadCovers(properties) {
  await Promise.all(properties.map(p=>p.photos?.[0]?loadPhoto(p.photos[0]).catch(()=>null):null));
}
function cover(p) {
  const photo=p.photos?.[0];const url=photo&&photoCache.get(photo.id);
  return url?`<img class="property-cover-photo" src="${esc(url)}" alt="Photo of ${esc(p.title)}" loading="lazy">`:icon('properties');
}
const money = value => value == null ? 'Not confirmed' : new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',maximumFractionDigits:0}).format(value);
const price = value => value >= 10000000 ? `₹${(value/10000000).toLocaleString('en-IN',{maximumFractionDigits:2})} Cr` : `₹${(value/100000).toLocaleString('en-IN',{maximumFractionDigits:2})} L`;
const date = stamp => stamp ? new Date(stamp*1000).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata'}) : 'No activity yet';
const visitDate = value => value ? new Date(value).toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata'}) + ' IST' : 'Time not supplied';
const badge = (label, kind='neutral') => `<span class="badge ${kind}"><span class="tiny-dot"></span>${esc(label)}</span>`;
const avatar = (name='Buyer') => `<span class="avatar">${esc(name.split(/\s+/).map(part => part[0]).slice(0,2).join('').toUpperCase())}</span>`;
const heading = (title, subtitle, action='') => `<div class="page-heading"><div><span class="eyebrow">YOUR AGENT WORKSPACE</span><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${action}</div>`;
const empty = (symbol, title, text, action='', extra='') => `<div class="empty ${extra}"><div class="empty-icon">${icon(symbol)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
const button = (text, id, kind='primary', symbol='plus') => `<button class="button ${kind}" id="${id}">${icon(symbol)}${esc(text)}</button>`;
const linkButton = (text, page, kind='primary') => `<a class="button ${kind}" href="#${page}">${esc(text)} ${icon('arrow')}</a>`;
function toast(text) { $('#toast').textContent=text; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4500); }
function bind(selector,event,handler) { const element=$(selector); if(element) element.addEventListener(event, (...args)=>Promise.resolve(handler(...args)).catch(error=>toast(error.message))); }
async function api(path, options={}) {
  const response = await fetch('/api'+path,{...options, headers:{'X-API-Key':state.key,'Content-Type':'application/json',...options.headers}});
  if(response.status===204)return null;
  const data = await response.json().catch(()=>({detail:'Unexpected response from the backend.'}));
  if(!response.ok) {
    if(response.status===401) { state.key=''; sessionStorage.removeItem('estate-admin'); showLogin(); }
    const detail=Array.isArray(data.detail) ? data.detail.map(item=>`${item.loc?.at(-1)}: ${item.msg}`).join('; ') : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}
function showLogin() { if(!$('#login-dialog').open) $('#login-dialog').showModal(); }
function pageName() { return Object.hasOwn(pages,location.hash.slice(1)) ? location.hash.slice(1) : 'overview'; }
async function navigate() {
  clearTimeout(state.timer);
  state.page=pageName(); const nonce=++state.nonce;
  window.scrollTo(0,0);
  $('#breadcrumb').textContent=pages[state.page];
  $('#navigation').innerHTML=Object.entries(pages).map(([key,label])=>`<a href="#${key}" class="${key===state.page?'active':''}" ${key===state.page?'aria-current="page"':''}>${icon(key)}${label}${key==='test'?'<span class="nav-new">TRY IT</span>':''}</a>`).join('');
  if(!state.key) { $('#content').innerHTML=heading('Your workspace, ready when you are.','Connect to manage your inventory and try your agent.');showLogin();return; }
  $('#content').innerHTML='<div class="loading">Loading your workspace…</div>';
  try {
    state.status=await api('/status');
    $('.workspace-label strong').textContent=state.status.business_name;
    const renderer={overview:renderOverview,properties:renderProperties,conversations:renderConversations,test:renderTest,settings:renderSettings}[state.page];
    await renderer(nonce);
  } catch(error) {
    if(nonce!==state.nonce) return;
    $('#content').innerHTML=`<div class="page-error"><h2>We couldn’t load this page.</h2><p>${esc(error.message)}</p>${button('Try again','retry','primary','arrow')}</div>`;
    bind('#retry','click',navigate);
  }
}
function scheduleOverview(nonce) {
  clearTimeout(state.timer);
  state.timer=setTimeout(async()=>{if(state.page!=='overview'||nonce!==state.nonce||!state.key)return;try{await renderOverview(nonce);}catch(error){toast('Overview could not refresh: '+error.message);if(state.key&&nonce===state.nonce)scheduleOverview(nonce);}},5000);
}
async function renderOverview(nonce) {
  const data=await api('/dashboard'); if(nonce!==state.nonce)return;
  const snapshot=nonce+JSON.stringify(data);
  if(state.overviewSnapshot===snapshot){scheduleOverview(nonce);return;}
  state.overviewSnapshot=snapshot;
  const metrics=[['conversations','Conversations','Including your test sessions','conversations'],['properties','Properties','Real and labelled demo inventory','properties'],['visit_requests','Visit requests','Awaiting buyer or dealer · live updates','visit'],['human_followups','Human follow-ups','Paused conversations · excluding opt-outs','human']];
  const buyers=data.customers.filter(c=>Object.keys(c.preferences).length || c.confirmed_budget);
  const followups=data.customers.filter(c=>c.paused&&!c.opted_out);
  $('#content').innerHTML=heading('A clear view of your next move.','Your conversations, buyer requirements and next steps, all in one place.',linkButton('Test your agent','test'))+
    `<section class="hero"><div><span class="eyebrow">MEET YOUR NEW FIRST RESPONDER</span><h2>Every enquiry is the start<br>of a new possibility.</h2><p>Your agent is here to listen, find the right properties and help buyers take the next step. Try a conversation to see it in action.</p></div><div class="hero-visual" aria-hidden="true"></div></section>`+
    `<section class="metrics" aria-label="Workspace statistics">${metrics.map(([key,title,note,symbol])=>`<div class="metric"><span class="metric-title">${title}</span><span class="metric-icon">${icon(symbol)}</span><div class="metric-value">${data.counts[key]}</div><span class="metric-note">${note}</span></div>`).join('')}</section>`+
    `<div class="dashboard-grid"><div class="card-stack"><section class="card"><div class="card-head"><div><h2>Buyer requirements</h2><p>What your buyers have shared so far</p></div><a class="button ghost" href="#conversations">View all ↗</a></div>${buyers.length?`<div class="table-wrap"><table class="requirements-table"><thead><tr><th>BUYER</th><th>LOOKING FOR</th><th>CONFIRMED BUDGET</th></tr></thead><tbody>${buyers.slice(0,6).map(c=>`<tr><td><div class="buyer-cell">${avatar(c.name)}<div><strong>${esc(c.name)}</strong><small>${c.test?'Test conversation':esc(c.phone)}</small></div></div></td><td>${esc([c.preferences.bedrooms!=null?c.preferences.bedrooms+' BHK':null,c.preferences.location].filter(Boolean).join(' · ')||'Still learning')}</td><td>${money(c.confirmed_budget)}</td></tr>`).join('')}</tbody></table></div>`:empty('conversations','Get to know your next buyer','Requirements will appear here when the agent saves preferences or the buyer confirms a budget.',linkButton('Start a test conversation','test','secondary'))}<div class="panel-note">Based on saved conversation data. Test conversations are included.</div></section>
    <section class="card"><div class="card-head"><div><h2>Recent conversations</h2><p>A little context before your next hello</p></div>${badge(data.customers.length+' shown')}</div>${data.customers.length?`<div class="card-body">${data.customers.slice(0,4).map(c=>`<a href="#conversations" class="row">${avatar(c.name)}<div class="row-main"><strong>${esc(c.name)}</strong><p>${esc(c.last_message.slice(0,100))}</p></div>${badge(c.opted_out?'Opted out':c.paused?'Human follow-up':c.test?'Test':'AI enabled',c.paused?'amber':'neutral')}</a>`).join('')}</div>`:empty('conversations','A fresh start','Your first conversation will appear here.')}</section></div>
    <div class="card-stack"><section class="card" aria-label="Visit requests"><div class="card-head"><div><h2>Visit requests</h2><p>${data.counts.visits_awaiting_buyer} awaiting buyer · ${data.counts.visits_awaiting_dealer} awaiting dealer</p></div>${icon('visit')}</div>${data.visits.length?`<div class="card-body visit-list">${data.visits.map(v=>`<div class="row"><span class="integration-icon">${icon('visit')}</span><div class="row-main"><strong>${esc(v.property_title||v.details.property_id)}</strong><p>${esc(v.details.property_id)}${v.location?' · '+esc(v.location):''}</p><p>${esc(visitDate(v.details.start_time))}</p><p>${esc(v.buyer_name||v.phone)}${v.test?' · Test conversation':''}</p>${badge(v.status==='requested'?'Awaiting dealer':v.status==='pending_confirmation'?'Awaiting buyer':v.status,'amber')}<p><a href="#conversations" class="button ghost" data-visit-conversation="${esc(v.phone)}">Open conversation ↗</a></p></div></div>`).join('')}</div>`:empty('visit','No visits requested yet','When your agent creates a site-visit request, it appears here—even before the buyer confirms.')}<div class="panel-note">Updates every 5 seconds. Requests are not calendar bookings.</div></section>
    <section class="card"><div class="card-head"><div><h2>Needs your attention</h2><p>Conversations that could use a human touch</p></div>${badge(followups.length+' pending',followups.length?'amber':'neutral')}</div>${followups.length?`<div class="card-body">${followups.slice(0,5).map(c=>`<div class="row">${avatar(c.name)}<div class="row-main"><strong>${esc(c.name)}</strong><p>${esc(data.alerts.find(a=>a.phone===c.phone)?.detail||'Conversation paused for human follow-up.')}</p><a href="#conversations" class="button ghost">Open conversations ↗</a></div></div>`).join('')}</div>`:empty('human','You’re all caught up','Human handoffs and paused conversations will show up here.')}</section></div></div>`;
  document.querySelectorAll('[data-visit-conversation]').forEach(link=>link.addEventListener('click',()=>{state.selectedPhone=link.dataset.visitConversation;state.conversationTab='messages';}));
  scheduleOverview(nonce);
}
async function renderProperties(nonce) {
  state.properties=await api('/properties');if(nonce!==state.nonce)return;
  await preloadCovers(state.properties);if(nonce!==state.nonce)return;
  $('#content').innerHTML=heading('Good matches start with good inventory.','Keep property details current so your agent can recommend with confidence.',`<div class="heading-actions">${button('Import Excel','import-inventory','secondary','arrow')}${button('Browse templates','browse-templates','secondary','properties')}${button('Add property','add-property')}</div>`)+
    `<div class="template-banner"><div><strong>More scenarios. Better testing.</strong><p>Try 8 fictional templates across Mohali, Chandigarh, Panchkula, Zirakpur and Dera Bassi.</p></div>${button('Add sample properties','seed-properties','secondary','plus')}</div>`+
    `<div class="toolbar"><label class="search-field">${icon('search')}<input id="property-search" placeholder="Search by title, city or property ID" aria-label="Search properties"></label><div class="filter-tabs" role="group" aria-label="Filter properties"><button data-filter="all" class="selected">All properties</button><button data-filter="available">Available</button><button data-filter="unavailable">Unavailable</button></div></div><div id="properties-results"></div>`;
  bind('#add-property','click',()=>openProperty());
  bind('#import-inventory','click',openInventoryImport);
  bind('#browse-templates','click',showTemplates);
  bind('#seed-properties','click',async()=>{if(!state.status.demo_inventory_allowed||state.status.whatsapp_mode==='live'){toast('Enable ALLOW_DEMO_DATA=true in simulation mode and restart the backend to use sample inventory.');return;}$('#seed-properties').disabled=true;try{const result=await api('/demo/seed',{method:'POST'});toast(result.created_count?`Added ${result.created_count} fictional sample properties.`:'The sample properties are already in your inventory.');await renderProperties(state.nonce);}catch(error){$('#seed-properties').disabled=false;throw error;}});
  bind('#property-search','input',paintProperties);
  document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{state.propertyFilter=b.dataset.filter; document.querySelectorAll('[data-filter]').forEach(item=>item.classList.toggle('selected',item===b));paintProperties();}));
  state.propertyFilter='all';paintProperties();
}
function paintProperties() {
  const term=($('#property-search')?.value||'').toLowerCase();
  const rows=state.properties.filter(p=>(state.propertyFilter==='all'||p.available===(state.propertyFilter==='available'))&&[p.title,p.city,p.locality,p.id].join(' ').toLowerCase().includes(term));
  $('#properties-results').innerHTML=rows.length?`<div class="property-grid">${rows.map(p=>`<article class="property-card"><div class="property-cover">${cover(p)}${badge(p.demo?'Fictional demo':p.available?'Available':'Unavailable',p.demo?'amber':p.available?'green':'neutral')}<span class="property-ref">${esc(p.id)}${p.photos?.length?' · '+p.photos.length+' photos':''}</span></div><div class="property-content"><h3>${esc(p.title)}</h3><p>${esc([p.locality,p.city].filter(Boolean).join(', '))} · ${p.bedrooms} BHK${!p.available?' · Unavailable':''}</p><div class="property-price">${price(p.asking_price_inr)}<small>asking price</small></div><p>${esc(p.description.slice(0,100)||'No description added.')}</p></div><div class="property-footer"><span>Updated ${esc(date(p.verified_at))}</span><button class="button secondary" data-edit="${esc(p.id)}">Edit details ↗</button></div></article>`).join('')}</div>`:
    `<div class="card">${empty('properties',term?'No properties match your search':'Your inventory starts here',term?'Try another location or clear the filters.':'Add a verified listing. Your agent will be able to find and recommend it immediately.','', 'full-empty')}</div>`;
  document.querySelectorAll('[data-edit]').forEach(b=>b.addEventListener('click',()=>openProperty(state.properties.find(p=>p.id===b.dataset.edit))));
}
async function showTemplates() {
  state.templates=await api('/property-templates');
  $('#template-list').innerHTML=state.templates.map((p,index)=>`<article class="template-option"><div><h3>${esc(p.title)}</h3><p>${esc(p.locality)}, ${esc(p.city)} · ${p.bedrooms} BHK · ${price(p.asking_price)}</p><p>${esc(p.description)}</p></div><button class="button secondary" data-template="${index}">Use template ↗</button></article>`).join('');
  document.querySelectorAll('[data-template]').forEach(b=>b.addEventListener('click',()=>{if(!state.status.demo_inventory_allowed||state.status.whatsapp_mode==='live'){toast('Demo templates require ALLOW_DEMO_DATA=true and simulation mode.');return;}const p=state.templates[Number(b.dataset.template)];$('#template-dialog').close();openProperty({...p,id:p.id+'-'+crypto.randomUUID().slice(0,5),asking_price_inr:p.asking_price},true);}));
  $('#template-dialog').showModal();
}
async function openProperty(property=null,fromTemplate=false) {
  const form=$('#property-form');form.reset();$('#property-error').textContent='';
  draftFiles.forEach(item=>URL.revokeObjectURL(item.url));draftFiles=[];draftPhotos=fromTemplate?[]:(property?.photos||[]);draftPropertyId=fromTemplate?null:property?.id;
  $('#photo-upload-status').textContent='';$('#photo-previews').innerHTML='';
  $('#property-extra-details').innerHTML=property?.details&&Object.keys(property.details).length?`<details class="import-source"><summary>Imported property details</summary><dl>${Object.entries(property.details).map(([key,value])=>`<dt>${esc(key.replaceAll('_',' '))}</dt><dd>${esc(value)}</dd>`).join('')}</dl><p class="text-small muted">Update these fields by re-importing the spreadsheet with the same property ID.</p></details>`:'';
  if(property?.import_source)$('#property-extra-details').innerHTML+=`<details class="import-source"><summary>Original sheet details · internal only</summary><p class="text-small muted">${esc(property.import_source.filename)} · ${esc(property.import_source.sheet)} · row ${esc(property.import_source.row)}. These source columns are not sent to the buyer-facing agent.</p><dl>${Object.entries(property.import_source.source_values||{}).map(([key,value])=>`<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join('')}</dl></details>`;
  $('#property-form-title').textContent=fromTemplate?'Create from template':property?'Edit property':'Add a property';
  form.elements.id.readOnly=Boolean(property)&&!fromTemplate;
  form.elements.demo.checked=Boolean(property?.demo);form.elements.demo.disabled=Boolean(property);
  if(property) for(const key of ['id','title','city','locality','bedrooms','description']) form.elements[key].value=property[key];
  if(property) {form.elements.asking_price.value=property.asking_price_inr; form.elements.available.checked=property.available;}
  $('#property-dialog').showModal();
  await Promise.all(draftPhotos.map(photo=>loadPhoto(photo).catch(()=>null)));paintDraftPhotos();
}
function paintDraftPhotos() {
  $('#photo-previews').innerHTML=draftPhotos.map(photo=>`<div class="photo-tile"><img src="${esc(photoCache.get(photo.id)||'')}" alt="Saved property photo"><button type="button" class="photo-remove" data-remove-photo="${photo.id}" aria-label="Remove saved photo">×</button><small>Saved</small></div>`).join('')+draftFiles.map((item,index)=>`<div class="photo-tile"><img src="${esc(item.url)}" alt="Selected photo ${esc(item.file.name)}"><button type="button" class="photo-remove" data-remove-draft="${index}" aria-label="Remove selected photo">×</button><small>Ready to upload</small></div>`).join('');
  document.querySelectorAll('[data-remove-draft]').forEach(b=>b.addEventListener('click',()=>{const [item]=draftFiles.splice(Number(b.dataset.removeDraft),1);URL.revokeObjectURL(item.url);paintDraftPhotos();}));
  document.querySelectorAll('[data-remove-photo]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Remove this photo from the property?'))return;try{await api('/properties/'+encodeURIComponent(draftPropertyId)+'/photos/'+b.dataset.removePhoto,{method:'DELETE'});const url=photoCache.get(b.dataset.removePhoto);if(url)URL.revokeObjectURL(url);photoCache.delete(b.dataset.removePhoto);draftPhotos=draftPhotos.filter(p=>p.id!==b.dataset.removePhoto);paintDraftPhotos();}catch(error){toast(error.message);}}));
}
function openInventoryImport() {
  inventoryImport=null;importReview=null;$('#inventory-sheet-upload').value='';
  $('#import-mapping').innerHTML='';$('#import-preview').innerHTML='';$('#import-status').textContent='';$('#import-error').textContent='';
  $('#commit-import').disabled=true;$('#skip-invalid-label').hidden=true;$('#skip-invalid-import').checked=false;
  $('#import-dialog').showModal();
}
function importSheet() {
  return inventoryImport.sheets.find(sheet=>sheet.name===($('#import-sheet')?.value||inventoryImport.sheets[0].name));
}
function markImportDirty() {
  importReview=null;$('#commit-import').disabled=true;$('#skip-invalid-label').hidden=true;
  $('#import-preview').innerHTML='<p class="notice">Column mapping changed. Validate the rows again before importing.</p>';
}
function renderImportMapping(selected=null) {
  const sheet=selected||inventoryImport.sheets[0];
  $('#import-mapping').innerHTML=`<div class="import-config"><label>Worksheet<select id="import-sheet">${inventoryImport.sheets.map(s=>`<option value="${esc(s.name)}" ${s.name===sheet.name?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label><label>Header row<input id="import-header-row" type="number" min="1" max="20" value="${sheet.header_row}"></label><label>Numeric price unit<select id="import-price-unit">${['INR','lakh','crore'].map(unit=>`<option ${unit===sheet.price_unit?'selected':''}>${unit}</option>`).join('')}</select></label></div><p class="text-small muted">Match your sheet’s columns below. City, Bedrooms/BHK and Asking price are required. Unmapped columns are retained as internal source details.</p><div id="column-mapping" class="mapping-grid"></div><div class="import-switches"><label class="check-label"><input id="import-update-existing" type="checkbox">Update existing property IDs</label><label class="check-label"><input id="import-default-available" type="checkbox" checked>Mark new rows available if availability is not supplied</label><label class="check-label"><input id="import-as-demo" type="checkbox" ${state.status.demo_inventory_allowed&&state.status.whatsapp_mode!=='live'?'':'disabled'}>Import as fictional demo inventory</label></div><div class="notice">Use stable property IDs when updating BIBA’s inventory. If no ID column is mapped, IDs are generated for this exact file and row. Blank titles are derived from the supplied BHK and location. Text such as “85 lakh” is converted to rupees; plain numbers use the selected unit.</div>${button('Validate & preview rows','validate-import','secondary','arrow')}`;
  renderColumnMapping(sheet.headers,sheet.suggested_mapping);
  bind('#import-sheet','change',()=>{const next=importSheet();renderImportMapping(next);markImportDirty();});
  bind('#import-header-row','change',()=>{const candidate=importSheet().header_candidates.find(item=>item.row===Number($('#import-header-row').value));if(candidate)renderColumnMapping(candidate.headers,{});markImportDirty();});
  for(const id of ['#import-price-unit','#import-update-existing','#import-default-available','#import-as-demo'])bind(id,'change',markImportDirty);
  bind('#validate-import','click',validateInventoryImport);
}
function renderColumnMapping(headers,suggested) {
  $('#column-mapping').innerHTML=inventoryImport.fields.map(field=>`<label>${esc(field.label)}${['city','bedrooms','asking_price'].includes(field.key)?' *':''}<select data-import-field="${esc(field.key)}"><option value="">Not mapped</option>${headers.map((header,index)=>`<option value="${index}" ${suggested[field.key]===index?'selected':''}>${index+1}. ${esc(header)}</option>`).join('')}</select></label>`).join('');
  document.querySelectorAll('[data-import-field]').forEach(select=>select.addEventListener('change',markImportDirty));
}
async function validateInventoryImport() {
  if(!inventoryImport)return;
  const button=$('#validate-import');button.disabled=true;$('#import-error').textContent='';
  const mapping={};document.querySelectorAll('[data-import-field]').forEach(select=>mapping[select.dataset.importField]=select.value===''?null:Number(select.value));
  try{importReview=await api('/inventory-import/'+inventoryImport.id+'/validate',{method:'POST',body:JSON.stringify({sheet:$('#import-sheet').value,header_row:Number($('#import-header-row').value),mapping,price_unit:$('#import-price-unit').value,update_existing:$('#import-update-existing').checked,default_available:$('#import-default-available').checked,demo:$('#import-as-demo').checked})});renderImportReview();}
  catch(error){markImportDirty();$('#import-error').textContent=error.message;}finally{button.disabled=false;}
}
function renderImportReview() {
  const review=importReview;if(!review)return;const summary=review.summary;
  $('#import-preview').innerHTML=`<div class="import-summary">${badge(summary.total+' rows')}${badge(summary.create+' new','green')}${badge(summary.update+' updates','blue')}${badge(summary.invalid+' errors',summary.invalid?'red':'neutral')}</div><p class="text-small muted">Previewing ${Math.min(review.rows.length,100)} of ${summary.total} rows. Prices below are in INR. Review availability before importing.</p><div class="table-wrap import-table"><table class="requirements-table"><thead><tr><th>ROW</th><th>PROPERTY ID</th><th>PROPERTY</th><th>CITY / BHK</th><th>ASKING PRICE</th><th>AVAILABLE</th><th>RESULT</th></tr></thead><tbody>${review.rows.map(row=>`<tr><td>${row.row_number}</td><td>${esc(row.property?.id||'—')}</td><td>${esc(row.property?.title||'Invalid row')}</td><td>${esc(row.property?.city||'—')}${row.property?' · '+row.property.bedrooms+' BHK':''}</td><td>${row.property?money(row.property.asking_price):'—'}</td><td>${row.property?badge(row.property.available?'Yes':'No',row.property.available?'green':'neutral'):'—'}</td><td>${row.errors.length?`<span class="error-text">${esc(row.errors.join('; '))}</span>`:badge(row.action==='update'?'Update':'Create',row.action==='update'?'blue':'green')}</td></tr>`).join('')}</tbody></table></div>${summary.invalid?`<div class="import-errors"><h3>Rows needing attention</h3>${review.errors.map(row=>`<p>Row ${row.row_number}: ${esc(row.errors.join('; '))}</p>`).join('')}</div>`:''}<p class="settings-note">Mapped property details become available to the agent after import. Other source columns remain internal. Embedded images and formulas are not imported; attach photos in the property editor.</p>`;
  $('#skip-invalid-label').hidden=!summary.invalid;updateImportButton();
}
function updateImportButton() {
  const summary=importReview?.summary;
  $('#commit-import').disabled=!summary||!summary.valid||(summary.invalid>0&&!$('#skip-invalid-import').checked);
  $('#commit-import').textContent=summary?'Import '+summary.valid+' reviewed rows ↗':'Import reviewed rows ↗';
}
bind('#inventory-sheet-upload','change',async event=>{
  const file=event.target.files?.[0];if(!file)return;
  inventoryImport=null;importReview=null;$('#commit-import').disabled=true;$('#import-mapping').innerHTML='';$('#import-preview').innerHTML='';$('#import-error').textContent='';$('#skip-invalid-label').hidden=true;
  if(!/\.(xlsx|csv)$/i.test(file.name)||file.size>8*1024*1024){$('#import-error').textContent='Choose an .xlsx or .csv file no larger than 8 MB.';return;}
  $('#import-status').textContent='Reading '+file.name+'…';event.target.disabled=true;
  try{inventoryImport=await api('/inventory-import/preview',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file});$('#import-status').textContent=file.name+' · '+inventoryImport.sheets.length+' worksheet(s) · nothing imported yet';renderImportMapping();await validateInventoryImport();}
  catch(error){$('#import-error').textContent=error.message;$('#import-status').textContent='The sheet could not be prepared.';}finally{event.target.disabled=false;}
});
bind('#skip-invalid-import','change',updateImportButton);
bind('#commit-import','click',async()=>{
  if(!inventoryImport||!importReview)return;$('#commit-import').disabled=true;$('#import-error').textContent='';
  try{const result=await api('/inventory-import/'+inventoryImport.id+'/commit',{method:'POST',body:JSON.stringify({skip_invalid:$('#skip-invalid-import').checked})});$('#import-dialog').close();toast(`Inventory imported: ${result.created} added, ${result.updated} updated, ${result.skipped} skipped.`);if(state.page==='properties')await renderProperties(state.nonce);}
  catch(error){$('#import-error').textContent=error.message;updateImportButton();}
});
bind('#close-import','click',()=>$('#import-dialog').close());
bind('#download-import-template','click',async()=>{
  const response=await fetch('/api/inventory-import/template.csv',{headers:{'X-API-Key':state.key}});if(!response.ok)throw new Error('Could not download the inventory template.');const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='estate-inventory-template.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function renderConversations(nonce) {
  state.customers=await api('/conversations');if(nonce!==state.nonce)return;
  if(!state.customers.some(c=>c.phone===state.selectedPhone)) state.selectedPhone=state.customers[0]?.phone;
  $('#content').innerHTML=heading('Every conversation has a story.','Read the context, see confirmed details and know when to step in.')+
    `<section class="card split-view"><aside class="conversation-list"><div class="conversation-list-head"><strong>Conversations</strong><span class="muted text-small"> · ${state.customers.length}</span></div>${state.customers.map(c=>`<button class="conversation-item ${c.phone===state.selectedPhone?'selected':''}" data-conversation="${esc(c.phone)}">${avatar(c.name)}<span><strong>${esc(c.name)}</strong><p>${esc(c.last_message)}</p><small>${c.test?'Test session · ':''}${c.opted_out?'Opted out':c.paused?'Human follow-up':'AI enabled'}</small></span></button>`).join('')||empty('conversations','No conversations yet','Try your agent to start one.')}</aside><div class="conversation-detail" id="conversation-detail"></div></section>`;
  document.querySelectorAll('[data-conversation]').forEach(b=>b.addEventListener('click',async()=>{state.selectedPhone=b.dataset.conversation;state.conversationTab='messages';await renderConversations(state.nonce);}));
  await paintConversation(nonce);
}
function recommendationCards(properties) {
  return `<div class="chat-property-grid">${properties.map(p=>`<article class="chat-property-card"><div class="property-cover">${cover(p)}${badge(p.demo?'Fictional demo':p.available?'Available':'Unavailable',p.demo?'amber':p.available?'green':'neutral')}</div><div class="property-content"><h3>${esc(p.title)}</h3><p>${esc(p.locality)}, ${esc(p.city)} · ${p.bedrooms} BHK</p><div class="property-price">${price(p.asking_price_inr)}<small>asking price</small></div><p>${esc(p.id)}</p><button type="button" class="button ghost" data-ask-property="${esc(p.id)}">Ask about this property ↗</button></div></article>`).join('')}</div>`;
}
function chatMessages(messages,recommendations=[]) {
  const format = content => esc(content).replace(/\*\*([^\n]+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/^\*\s+/gm,'• ');
  return messages.map(m=>{const rows=recommendations.filter(batch=>m.id==='reply:'+batch.source_message_id).flatMap(batch=>batch.properties);const unique=[...new Map(rows.map(p=>[p.id,p])).values()];return `<article class="chat-message ${m.role==='user'?'user':'assistant'}"><div class="chat-author">${m.role==='user'?'Buyer':'Estate AI · AI assistant'}</div><div class="chat-bubble">${m.role==='user'?esc(m.content):format(m.content)}</div><div class="chat-time">${esc(date(m.created))}</div></article>${unique.length?recommendationCards(unique):''}`;}).join('');
}
function insights(customer) {
  const p=customer?.preferences||{};
  const fields=[['Location',p.location||'Not shared yet'],['Bedrooms',p.bedrooms!=null?p.bedrooms+' BHK':'Not shared yet'],['Confirmed budget',money(customer?.confirmed_budget)],['Buying timeline',p.timeline||'Not shared yet'],['Purpose',p.purpose||'Not shared yet']];
  return `<div class="insight-grid">${fields.map(([label,value])=>`<div class="insight"><span>${label}</span><strong>${esc(value)}</strong></div>`).join('')}</div>`;
}
function proposalsView(proposals, confirm=false) {
  if(!proposals?.length)return '<p class="muted text-small">Budgets, offers and visit requests appear here after the agent records them.</p>';
  return proposals.map(p=>`<article class="proposal"><div class="proposal-top"><strong>${esc({budget:'Buyer budget',offer:'Property offer',visit:'Site-visit request'}[p.kind]||p.kind)}</strong>${badge(p.status==='buyer_confirmed'?'Buyer confirmed':p.status==='requested'?'Dealer review':'Needs confirmation',p.status==='buyer_confirmed'?'green':'amber')}</div><p>${p.kind==='visit'?esc(visitDate(p.details.start_time)):money(p.details.amount_inr)}${p.details.property_id?' · '+esc(p.details.property_id):''}</p><p>${p.kind==='offer'?'An offer from the buyer; not an agreed sale price.':p.kind==='visit'?'Availability and booking still need dealer approval.':'Budget is separate from any property asking price.'}</p>${confirm&&p.status==='pending_confirmation'?`<button class="button secondary" data-confirm="${esc(p.id)}">Confirm these details ↗</button>`:''}<p>Source: <code>${esc(p.source_message_id)}</code></p>${p.confirmation_message_id?`<p>Confirmed in: <code>${esc(p.confirmation_message_id)}</code></p>`:''}</article>`).join('');
}
function activityView(rows) {
  const relevant=rows.filter(a=>!['preferences','property_search_results'].includes(a.action));
  return relevant.length?relevant.map(a=>`<div class="activity"><strong>${esc(a.action.replaceAll('_',' '))}</strong><p>${esc(date(a.created))}</p>${['dealer_alert','opt_out','human_takeover','automation_resumed'].includes(a.action)?`<p>${esc(a.detail)}</p>`:''}</div>`).join(''):'<p class="muted text-small">Tool calls and handoffs will appear here as the agent works.</p>';
}
async function paintConversation(nonce) {
  const customer=state.customers.find(c=>c.phone===state.selectedPhone);
  if(!customer){$('#conversation-detail').innerHTML=empty('conversations','The context lives here','Select a conversation to explore its messages and buyer details.','','full-empty');return;}
  const [conversation,activity]=await Promise.all([api('/conversations/'+customer.phone),api('/conversations/'+customer.phone+'/activity')]);
  if(nonce!==state.nonce||state.page!=='conversations')return;
  $('#conversation-detail').innerHTML=`<div class="detail-head">${avatar(customer.name)}<div><h2>${esc(customer.name)}</h2><p class="muted text-small">${customer.test?'Test session · ':''}${customer.opted_out?'Opted out':conversation.paused?'Automation paused':'AI replies enabled'}</p></div>${customer.opted_out?badge('Opted out','red'):button(conversation.paused?'Resume AI':'Take over','toggle-pause','secondary','human')}</div>
    <div class="details-tabs">${[['messages','Messages'],['profile','Buyer details'],['activity','Activity & handoffs']].map(([key,label])=>`<button data-tab="${key}" class="${state.conversationTab===key?'selected':''}">${label}</button>`).join('')}</div>
    ${state.conversationTab==='messages'?`<div class="chat-history">${conversation.messages.length?chatMessages(conversation.messages):empty('conversations','Waiting for the first hello','No messages in this conversation yet.')}</div>`:state.conversationTab==='profile'?`<div class="card-body">${insights(customer)}<h3 style="margin:22px 0 13px">Budgets, offers & visit requests</h3>${proposalsView(customer.proposals)}</div>`:`<div class="card-body">${activityView(activity)}</div>`}`;
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{state.conversationTab=b.dataset.tab;paintConversation(state.nonce).catch(e=>toast(e.message));}));
  bind('#toggle-pause','click',async()=>{await api('/conversations/'+customer.phone+(conversation.paused?'/resume':'/takeover'),{method:'POST'});toast(conversation.paused?'AI resumed for future messages.':'Conversation paused for human follow-up.');await renderConversations(state.nonce);});
}
async function renderTest(nonce) {
  state.testSessions=await api('/test-sessions');if(nonce!==state.nonce)return;
  if(!state.testSessions.length&&state.status.whatsapp_mode!=='live') state.testSessions=[await api('/test-sessions',{method:'POST',body:JSON.stringify({name:'Test conversation 1'})})];
  if(nonce!==state.nonce)return;
  if(!state.testSessions.some(s=>s.phone===state.testPhone))state.testPhone=state.testSessions[0]?.phone;
  if(state.testPhone)sessionStorage.setItem('estate-test-phone',state.testPhone);
  $('#content').innerHTML=heading('A conversation is the best test.','Meet your real agent. Explore its answers, tools and understanding.',button('New conversation','new-test','secondary'))+
    `<div class="test-layout"><section class="card test-chat"><div class="card-head"><div><h2>${icon('test')} Estate AI assistant</h2><p>${esc(state.status.model)} · via Ollama</p></div><select class="session-select" id="test-session-select" aria-label="Select test conversation">${state.testSessions.map(s=>`<option value="${s.phone}" ${s.phone===state.testPhone?'selected':''}>${esc(s.name)}</option>`).join('')}</select></div><div class="test-banner">${icon('test')}Real agent & tools · Test messages stay here. Nothing is sent to WhatsApp.</div><div id="test-history" class="chat-history"></div><div id="recommendation-controls" class="recommendation-controls"></div><div id="thinking" class="thinking" hidden>Agent is thinking and checking its tools…</div><div class="chat-compose"><form id="chat-form"><textarea id="chat-input" aria-label="Message your agent" rows="2" maxlength="4000" placeholder="Ask about a property, share a budget, or request a visit…" required></textarea><button class="button primary" id="send-message" type="submit" aria-label="Send message">${icon('send')}</button></form><small>Enter to send · Shift + Enter for a new line · Synthetic buyer session</small><p id="chat-error" class="error-text" role="alert"></p></div></section>
    <aside class="test-context card-stack"><section class="card"><div class="card-head"><div><h2>What your agent knows</h2><p>Saved buyer requirements</p></div>${icon('human')}</div><div class="card-body" id="test-insights"></div></section><section class="card"><div class="card-head"><h2>Confirmations & requests</h2></div><div class="card-body" id="test-proposals"></div></section><section class="card"><div class="card-head"><div><h2>Agent activity</h2><p>Actual tool calls and handoffs</p></div></div><div class="card-body" id="test-activity"></div></section></aside></div>`;
  bind('#new-test','click',async()=>{const s=await api('/test-sessions',{method:'POST',body:JSON.stringify({name:'Test conversation '+(state.testSessions.length+1)})});state.testPhone=s.phone;sessionStorage.setItem('estate-test-phone',s.phone);await renderTest(state.nonce);});
  bind('#test-session-select','change',async event=>{state.testPhone=event.target.value;sessionStorage.setItem('estate-test-phone',state.testPhone);await loadTestData();if(state.pending[state.testPhone])pollTest();});
  bind('#chat-form','submit',async event=>{event.preventDefault();await sendTestMessage($('#chat-input').value.trim());});
  bind('#chat-input','keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#chat-form').requestSubmit();}});
  await loadTestData();if(state.pending[state.testPhone])pollTest();
}
async function loadTestData() {
  const phone=state.testPhone;
  if(!phone){$('#test-history').innerHTML=empty('test','Testing is unavailable','Switch WHATSAPP_MODE to simulate and restart the backend.');$('#send-message').disabled=true;return;}
  const [conversation,customers,activity,recommendations]=await Promise.all([api('/conversations/'+phone),api('/conversations'),api('/conversations/'+phone+'/activity'),api('/conversations/'+phone+'/recommendations')]);
  await preloadCovers(recommendations.batches.flatMap(batch=>batch.properties));
  if(state.page!=='test'||phone!==state.testPhone)return;
  const waiting = conversation.jobs?.find(job=>['pending','processing'].includes(job.state));
  if(waiting)state.pending[phone]=waiting.id;
  const customer=customers.find(c=>c.phone===phone);
  const history=$('#test-history');const nearBottom=history.scrollHeight-history.scrollTop-history.clientHeight<90;
  history.innerHTML=conversation.messages.length?chatMessages(conversation.messages,recommendations.batches):empty('test','Say hello to your agent','Start like a buyer would. Your agent can search inventory, remember requirements and prepare visit requests.',`<div class="suggestions"><button class="suggestion" data-prompt="Hi, I’m looking for a 3 BHK in Mohali.">Find a home in Mohali</button><button class="suggestion" data-prompt="My budget is 90 lakh.">Share a budget</button><button class="suggestion" data-prompt="What properties do you have available?">Explore available properties</button></div>`);
  if(nearBottom||state.pending[phone])history.scrollTop=history.scrollHeight;
  $('#test-insights').innerHTML=insights(customer);
  $('#test-proposals').innerHTML=proposalsView(customer?.proposals,true);
  $('#test-activity').innerHTML=activityView(activity);
  const paused=conversation.paused||conversation.opted_out;
  const blocked=Boolean(state.pending[phone])||paused||state.status.whatsapp_mode==='live';
  $('#recommendation-controls').innerHTML=`${recommendations.has_search?`<button class="button secondary" id="more-properties" ${blocked||!recommendations.has_more?'disabled':''}>Show more matches ↗</button>`:''}<button class="button ghost" id="browse-properties" ${blocked?'disabled':''}>Browse all inventory ↗</button>${recommendations.has_search&&!recommendations.has_more?'<small>No unseen matches for the current search. Ask to adjust your criteria, or browse all inventory.</small>':''}`;
  bind('#more-properties','click',()=>queuePropertyAction('more'));
  bind('#browse-properties','click',()=>queuePropertyAction('browse'));
  $('#send-message').disabled=Boolean(state.pending[phone])||paused||state.status.whatsapp_mode==='live';
  $('#thinking').hidden=!state.pending[phone];
  $('#chat-error').textContent=conversation.opted_out?'This test buyer opted out. Start a new conversation.':paused?'AI is paused after a handoff. Resume it in Conversations or start a new test.':'';
  document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{ $('#chat-input').value=b.dataset.prompt;$('#chat-input').focus();}));
  document.querySelectorAll('[data-confirm]').forEach(b=>b.addEventListener('click',()=>sendTestMessage('CONFIRM '+b.dataset.confirm).catch(e=>toast(e.message))));
  document.querySelectorAll('[data-ask-property]').forEach(b=>b.addEventListener('click',()=>{$('#chat-input').value='Tell me more about property '+b.dataset.askProperty;$('#chat-input').focus();}));
}
async function queuePropertyAction(action) {
  const phone=state.testPhone;if(!phone||state.pending[phone])return;
  document.querySelectorAll('#recommendation-controls button').forEach(b=>b.disabled=true);
  try{const job=await api('/test-sessions/'+phone+'/'+action+'-properties',{method:'POST'});state.pending[phone]=job.event_id;await loadTestData();pollTest();}
  catch(error){toast(error.message);await loadTestData();}
}
async function sendTestMessage(text) {
  if(!text||!state.testPhone||state.pending[state.testPhone])return;
  const phone=state.testPhone;$('#chat-error').textContent='';$('#send-message').disabled=true;
  try {
    const queued=await api('/simulator/messages',{method:'POST',body:JSON.stringify({phone,text,event_id:'dash-'+crypto.randomUUID()})});
    state.pending[phone]=queued.event_id;$('#chat-input').value='';await loadTestData();pollTest();
  } catch(error) {$('#send-message').disabled=false;$('#chat-error').textContent=error.message;}
}
function pollTest() {
  clearTimeout(state.timer);
  const phone=state.testPhone;const eventId=state.pending[phone];if(!eventId||state.page!=='test')return;
  state.timer=setTimeout(async()=>{
    try {
      const job=await api('/jobs/'+encodeURIComponent(eventId));
      const terminal=['done','failed','suppressed'].includes(job.state);
      if(terminal)delete state.pending[phone];
      if(state.page==='test'&&phone===state.testPhone){await loadTestData();
        if(job.state==='failed')$('#chat-error').textContent='The model could not complete this message after retries. Check Settings → Check connection, then start a new test.';
        if(!terminal)pollTest();}
    } catch(error){if(state.page==='test'){$('#chat-error').textContent=error.message;delete state.pending[phone];$('#thinking').hidden=true;$('#send-message').disabled=false;}}
  },1300);
}
async function renderSettings(nonce) {
  if(nonce!==state.nonce)return;const s=state.status;
  const setting=(label,value)=>`<div class="setting-row"><span>${esc(label)}</span><code>${esc(value)}</code></div>`;
  $('#content').innerHTML=heading('The essentials behind your agent.','Model configuration and integration status. Everything in plain sight.',badge('Configuration · read only'))+
    `<div class="settings-grid"><div class="card-stack"><section class="card"><div class="card-head"><div><h2>AI model</h2><p>The engine behind every conversation</p></div>${badge('Ollama','green')}</div><div class="card-body"><div class="settings-rows">${setting('Model',s.model)}${setting('API endpoint',s.ollama_base_url)}${setting('Authentication',s.ollama_api_key_required?(s.ollama_api_key_configured?'API key configured':'API key missing'):'Local Ollama · signed-in account')}${setting('Separate API key',s.ollama_api_key_required?'Required':'Not required for localhost')}${setting('Background worker',s.worker_enabled?'Enabled':'Disabled')}</div><div style="margin-top:20px">${button('Check connection','check-ollama','secondary','arrow')}</div><div id="connection-check" aria-live="polite"></div><p class="settings-note">Connection checks reach the configured endpoint and look for this model. They do not verify inference or cloud sign-in. Test Your Agent exercises the real model.</p></div></section>
    <section class="card"><div class="card-head"><h2>Workspace</h2></div><div class="card-body settings-rows">${setting('Business name',s.business_name)}${setting('Business timezone',s.timezone)}${setting('Database',s.database)}${setting('Demo inventory permission',s.demo_inventory_allowed?'Allowed in simulation':'Disabled')}</div></section></div>
    <div class="card-stack"><section class="card"><div class="card-head"><div><h2>Integrations</h2><p>Configured does not always mean connected</p></div></div><div class="card-body"><div class="integration"><span class="integration-icon">${icon('test')}</span><div><h3>Ollama</h3><p id="ollama-integration-note">${s.ollama_configured?'Configured · connection not checked':'Configuration incomplete'}</p></div><span id="ollama-integration-badge">${badge('Not checked')}</span></div><div class="integration"><span class="integration-icon">${icon('conversations')}</span><div><h3>WhatsApp</h3><p>${s.whatsapp_mode==='simulate'?'Test conversations only · no messages sent':s.whatsapp_credentials_configured?'Credentials configured · delivery not verified':'Credentials missing'}</p></div>${badge(s.whatsapp_mode==='simulate'?'Simulation':'Live mode',s.whatsapp_mode==='simulate'?'amber':'blue')}</div><div class="integration"><span class="integration-icon">${icon('visit')}</span><div><h3>Google Calendar</h3><p>Visits are requests pending dealer approval</p></div>${badge('Not connected')}</div><div class="integration"><span class="integration-icon">${icon('properties')}</span><div><h3>99acres & Housing.com</h3><p>Lead-source adapters are planned</p></div>${badge('Not connected')}</div></div></section>
    <section class="card"><div class="card-head"><h2>Change your configuration</h2></div><div class="card-body"><p class="muted text-small">Edit your local <code>.env</code> file and restart the backend to change the model, endpoint or integration settings. Credentials are never displayed on this page.</p><div class="notice" style="margin:18px 0 0">Your current agent uses a configurable model connection. When you’re ready to deploy, you can switch the endpoint and model, or add another provider adapter.</div></div></section></div></div>`;
  bind('#check-ollama','click',async()=>{const b=$('#check-ollama');b.disabled=true;b.textContent='Checking connection…';try{const result=await api('/integrations/ollama/check',{method:'POST'});if(state.page!=='settings')return;$('#connection-check').className='connection-result'+(!result.reachable||!result.model_available?' bad':'');$('#connection-check').textContent=result.message;$('#ollama-integration-badge').innerHTML=badge(result.reachable?(result.model_available?'Reachable':'Model not listed'):'Unreachable',result.reachable&&result.model_available?'green':'amber');$('#ollama-integration-note').textContent=result.reachable?'Endpoint checked just now':'Start Ollama and try again';}finally{if(state.page==='settings'){b.disabled=false;b.innerHTML=icon('arrow')+'Check connection';}}});
}
bind('#property-form','submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const values=new FormData(form);
  const body={id:values.get('id').trim(),title:values.get('title').trim(),city:values.get('city').trim(),locality:values.get('locality').trim(),bedrooms:Number(values.get('bedrooms')),asking_price:Number(values.get('asking_price')),description:values.get('description').trim(),available:form.elements.available.checked,demo:form.elements.demo.checked};
  $('#save-property').disabled=true;$('#property-error').textContent='';
  let propertySaved=false;
  try{const saved=await api('/properties/'+encodeURIComponent(body.id),{method:'PUT',body:JSON.stringify(body)});propertySaved=true;draftPropertyId=body.id;draftPhotos=saved.photos||[];form.elements.id.readOnly=true;form.elements.demo.disabled=true;
    while(draftFiles.length){const item=draftFiles[0];$('#photo-upload-status').textContent=`Uploading ${item.file.name}…`;const photo=await api('/properties/'+encodeURIComponent(body.id)+'/photos',{method:'POST',body:item.file,headers:{'Content-Type':item.file.type||'application/octet-stream'}});draftFiles.shift();URL.revokeObjectURL(item.url);if(!draftPhotos.some(p=>p.id===photo.id))draftPhotos.push(photo);await loadPhoto(photo);paintDraftPhotos();}
    $('#property-dialog').close();toast('Property and photos saved. Your agent can use the updated details.');if(state.page==='properties')await renderProperties(state.nonce);
  }catch(error){$('#property-error').textContent=(propertySaved?'Property saved, but a photo could not be uploaded: ':'')+error.message;$('#photo-upload-status').textContent='Uploaded photos are retained. Retry Save property to upload the remaining photos.';}finally{$('#save-property').disabled=false;}
});
bind('#property-photo-input','change',event=>{
  for(const file of event.target.files){if(draftPhotos.length+draftFiles.length>=10){toast('A property can have up to 10 photos.');break;}if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024){toast('Choose JPEG, PNG or WebP photos no larger than 8 MB each.');continue;}draftFiles.push({file,url:URL.createObjectURL(file)});}
  event.target.value='';paintDraftPhotos();
});
bind('#close-property','click',()=>$('#property-dialog').close());bind('#cancel-property','click',()=>$('#property-dialog').close());
bind('#close-templates','click',()=>$('#template-dialog').close());
bind('#login-dialog','cancel',event=>event.preventDefault());
bind('#login-form','submit',async event=>{event.preventDefault();state.key=$('#admin-key').value.trim();$('#login-error').textContent='';try{await api('/status');sessionStorage.setItem('estate-admin',state.key);$('#admin-key').value='';$('#login-dialog').close();await navigate();}catch(error){$('#login-error').textContent=error.message;}});
bind('#lock-workspace','click',()=>{clearTimeout(state.timer);state.key='';sessionStorage.removeItem('estate-admin');navigate();});
bind('#refresh','click',()=>navigate());
window.addEventListener('hashchange',navigate);
navigate();
