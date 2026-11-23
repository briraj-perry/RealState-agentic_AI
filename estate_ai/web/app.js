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
const modelProviders = {ollama:'Ollama', gemini:'Google Gemini', anthropic:'Anthropic Claude', openai:'OpenAI'};
const modelPresets = {
  gemini: ['gemini-3.8-flash', 'gemini-4-hydrogen', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro'],
  anthropic: ['claude-haiku-5-5', 'claude-sonnet-5-5', 'claude-opus-5-5'],
  openai: ['gpt-5.4-mini', 'gpt-5.6-terra', 'gpt-6-astra'],
};
const pages = {overview:'Overview', properties:'Properties', portal:'Test listing portal', conversations:'Conversations', test:'Test Your Agent', settings:'Settings'};
const state = {key:sessionStorage.getItem('estate-admin') || '', status:null, page:'overview', nonce:0,
  properties:[], templates:[], propertyFilter:'all', customers:[], selectedPhone:null, conversationTab:'messages', overviewSnapshot:null,
  testPhone:sessionStorage.getItem('estate-test-phone'), testSessions:[], pending:{}, timer:null};
let toastTimer;
const photoCache = new Map();
let draftPhotos=[], draftFiles=[], draftPropertyId=null;
let inventoryImport=null, importReview=null;
let templatePage=0, propertyPage=0, draftDetails=null;
const humanDrafts=new Map();
state.overviewScope=sessionStorage.getItem('estate-overview-scope')||'all';
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
const visitTime = value => value ? Date.parse(value) : NaN;
const visitDate = value => Number.isFinite(visitTime(value)) ? new Date(value).toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata'}) + ' IST' : 'Time not supplied';
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
    $('.workspace-avatar').textContent=state.status.business_name.trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();
    const renderer={overview:renderOverview,properties:renderProperties,portal:renderPortal,conversations:renderConversations,test:renderTest,settings:renderSettings}[state.page];
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
function openBuyerLinks() {
  document.querySelectorAll('[data-open-buyer]').forEach(link=>link.addEventListener('click',()=>{state.focusReply=true;state.selectedPhone=link.dataset.openBuyer;state.conversationTab='messages';}));
}
function buyerLink(phone,label='Open conversation ↗',kind='secondary') {
  return `<a href="#conversations" class="button ${kind}" data-open-buyer="${esc(phone)}">${esc(label)}</a>`;
}
function waitingSince(timestamp) {
  if(!timestamp)return 'No inbound message yet';
  const mins=Math.max(0,Math.floor((Date.now()/1000-timestamp)/60));
  return mins<60?mins+' min ago':mins<1440?Math.floor(mins/60)+' hr ago':Math.floor(mins/1440)+' days ago';
}
function itineraryCard(visit, now) {
  const start=visitTime(visit.details.start_time);
  const passed=start<now;
  const needsBuyer=visit.status==='pending_confirmation';
  const place=[visit.address,visit.location].filter(Boolean).join(', ');
  const directions=place&&!visit.test&&!visit.property_demo
    ? `<a class="button secondary" href="https://www.google.com/maps/dir/?api=1&destination=${esc(encodeURIComponent(place))}" target="_blank" rel="noopener noreferrer">${visit.address?'Directions':'Area map'} ↗</a>`
    : '';
  const next=passed?'Ask the buyer for a new time.':!Number.isFinite(start)?'Ask the buyer for a date and time.'
    :needsBuyer?'Confirm the proposed time with the buyer.':'Verify access, availability and the meeting point before confirming.';
  return `<article class="visit-work-item">
    <div class="visit-title"><strong>${esc(visit.property_title||visit.details.property_id||'Property to verify')}</strong>${visit.test?badge('Test'):''}</div>
    <p class="visit-time">${esc(visitDate(visit.details.start_time))}</p>
    <p>${esc(visit.buyer_name||visit.phone)}${visit.details.property_id?' · '+esc(visit.details.property_id):''}</p>
    <p>${esc(place||'Meeting point to verify')}</p>
    <div class="visit-status">${badge(passed?'Time passed':needsBuyer?'Awaiting buyer':'Awaiting dealer approval','amber')}${visit.property_available===false?badge('Marked unavailable','amber'):''}</div>
    <p>${esc(next)}</p>${visit.calendar_state==='saved'?'<p>Saved to Apple Calendar</p>':visit.calendar_state==='pending'?'<p>Waiting to save to Apple Calendar</p>':visit.calendar_state==='retrying'?'<p>Calendar sync failed. Retrying automatically.</p>':visit.calendar_state==='needs_new_time'?'<p>Ask the buyer for a time tomorrow to save this request to Apple Calendar.</p>':''}
    <div class="visit-actions">${buyerLink(visit.phone,'Open buyer chat ↗')}${directions}${state.status.calendar==='apple_calendar'&&visit.can_add_to_calendar?`<button class="button secondary" data-calendar-visit="${esc(visit.id)}">Add to Apple Calendar</button>`:''}</div>
  </article>`;
}
async function renderOverview(nonce) {
  const data=await api('/dashboard');if(nonce!==state.nonce)return;
  if ($('#calendar-visits')?.open) { scheduleOverview(nonce); return; }
  const now=Date.now();
  const snapshot=nonce+state.overviewScope+JSON.stringify(data)+data.visits.filter(v=>visitTime(v.details.start_time)<now).length;
  if(state.overviewSnapshot===snapshot){scheduleOverview(nonce);return;}state.overviewSnapshot=snapshot;
  const scope=state.overviewScope;
  const inScope=c=>scope==='all'||c.test===(scope==='test');
  const customers=data.customers.filter(inScope);
  const followups=customers.filter(c=>c.paused&&!c.opted_out).sort((a,b)=>Number(Boolean(b.reply_needed))-Number(Boolean(a.reply_needed))||a.last_inbound-b.last_inbound);
  const needsReply=followups.filter(c=>c.reply_needed);
  const visits=data.visits.filter(v=>inScope(v)&&['pending_confirmation','requested'].includes(v.status));
  const calendarVisits=visits.filter(v=>v.can_add_to_calendar);
  const upcoming=visits.filter(v=>visitTime(v.details.start_time)>=now)
    .sort((a,b)=>visitTime(a.details.start_time)-visitTime(b.details.start_time));
  const needsAttention=visits.filter(v=>!(visitTime(v.details.start_time)>=now));
  const dealerVisits=visits.filter(v=>v.status==='requested');
  const operations=data.operations||{};
  const issues=(operations.issues||[]).filter(i=>customers.some(c=>c.phone===i.phone));
  const active=customers.filter(c=>!c.paused&&!c.opted_out).length;
  const recent=[...customers].sort((a,b)=>b.last_message_at-a.last_message_at).slice(0,6);
  const buyerRows=customers.filter(c=>Object.keys(c.preferences).length||c.confirmed_budget||c.property_id).slice(0,6);
  const scopeName=scope==='all'?'All conversations':scope==='test'?'Test conversations':'Real buyers';
  $('#content').innerHTML=heading('Your work queue.','See who needs you, reply with context, and keep the next step moving.',`<div class="heading-actions">${linkButton('Open inbox','conversations','secondary')}${linkButton('Test your agent','test')}</div>`)+
    `<div class="overview-bar"><div><strong>${esc(data.business_name||state.status.business_name)}</strong><p>${state.status.whatsapp_mode==='live'?'WhatsApp live mode configured':'App simulation · test replies stay in Estate AI'}</p></div><div class="filter-tabs" role="group" aria-label="Overview conversations">${[['all','All activity'],['real','Real buyers'],['test','Test only']].map(([value,label])=>`<button data-overview-scope="${value}" class="${scope===value?'selected':''}">${label}</button>`).join('')}</div><small>Refreshes every 5 seconds</small></div>`+
    `<section class="metrics" aria-label="Workspace statistics">${[
      [needsReply.length,'Buyers waiting','Human reply needed','human'],
      [dealerVisits.length,'Visits to review','Buyer confirmed · approval needed','visit'],
      [active,'AI conversations','Automation enabled · '+scopeName.toLowerCase(),'conversations'],
      [operations.available_properties??data.counts.properties,'Available properties',(operations.demo_properties||0)+' fictional test listings in inventory','properties']
    ].map(([value,label,note,symbol])=>`<div class="metric"><span class="metric-title">${label}</span><span class="metric-icon">${icon(symbol)}</span><div class="metric-value">${value}</div><span class="metric-note">${esc(note)}</span></div>`).join('')}</section>`+
    `<div class="overview-work-grid"><div class="card-stack"><section class="card"><div class="card-head"><div><h2>Human follow-ups</h2><p>${needsReply.length} waiting for a reply · ${followups.filter(c=>c.followup_status==='awaiting_buyer').length} awaiting buyer</p></div>${badge(followups.length+' open',followups.length?'amber':'neutral')}</div>${followups.length?`<div class="followup-list">${followups.slice(0,10).map(c=>`<article class="followup-item"><div class="followup-heading">${avatar(c.name)}<div><h3>${esc(c.name)}</h3><small>${c.test?'Synthetic buyer':esc(c.phone)} · Last inbound ${esc(waitingSince(c.last_inbound))}</small></div>${badge(({reply_needed:'Reply needed',reply_queued:'Reply queued',delivery_review:'Review delivery',awaiting_buyer:'Awaiting buyer'})[c.followup_status]||'Review conversation',c.reply_needed||c.followup_status==='delivery_review'?'amber':'neutral')}</div>${c.property_id?`<p class="followup-property">${esc(c.property_title)} · ${esc(c.property_id)}</p>`:''}<p>${esc(alertSummary(data.alerts.find(a=>a.phone===c.phone)?.detail||'Conversation taken over for human support.'))}</p><blockquote>${esc(c.last_message.slice(0,220))}</blockquote><div class="followup-actions">${buyerLink(c.phone,c.reply_needed?'Reply to buyer ↗':'Continue conversation ↗','primary')}<small>AI stays paused until you resume it</small></div></article>`).join('')}</div>`:empty('human','No buyers waiting for you',scope==='real'?'Real buyer handoffs will appear here. Use Test only to review simulated leads.':'Handoffs appear here with the buyer’s property and conversation context.')}</section>
    <section class="card"><div class="card-head"><div><h2>Recent conversations</h2><p>${customers.length} conversations · ${scopeName.toLowerCase()}</p></div>${linkButton('View inbox','conversations','ghost')}</div>${recent.length?`<div class="card-body">${recent.map(c=>`<a href="#conversations" class="row" data-open-buyer="${esc(c.phone)}">${avatar(c.name)}<div class="row-main"><strong>${esc(c.name)}</strong><p>${esc(c.last_message.slice(0,110))}</p><small>${esc(waitingSince(c.last_message_at))}${c.test?' · Test':''}</small></div>${badge(c.opted_out?'Opted out':c.paused?'With team':'AI active',c.paused?'amber':'neutral')}</a>`).join('')}</div>`:empty('conversations','No activity in this view','New enquiries and replies appear here.')}</section></div>
    <div class="card-stack"><section class="card" aria-label="Visit itinerary"><div class="card-head"><div><h2>Visit itinerary</h2><p>${upcoming.length} upcoming · ${needsAttention.length} need a new time</p></div><button class="button secondary" id="open-calendar-visits">Add to Apple Calendar</button></div>
    <dialog id="calendar-visits"><h2>Add to Apple Calendar</h2><div class="settings-rows">${state.status.calendar!=='apple_calendar'?'Open the dashboard on a Mac with Apple Calendar.':calendarVisits.length?calendarVisits.map(v=>`<button type="button" class="button secondary" data-calendar-visit="${esc(v.id)}">${esc(v.property_title||v.details.property_id||'Site visit')} · ${esc(visitDate(v.details.start_time))}${v.test?' · Test':''}</button>`).join(''):'No unsaved visit requests for tomorrow.'}</div><button type="button" class="button secondary" id="close-calendar-visits">Close</button></dialog>${visits.length?`<div class="card-body visit-list">${upcoming.map(v=>itineraryCard(v,now)).join('')}${needsAttention.length?`<h3>Time to review</h3>${needsAttention.map(v=>itineraryCard(v,now)).join('')}`:''}</div>`:empty('visit','No pending visits','Requests will appear here when a buyer proposes a visit.')}<div class="panel-note">Visit requests require team approval before booking.</div></section>
    <section class="card"><div class="card-head"><div><h2>Delivery & agent issues</h2><p>Review before sending another reply</p></div>${badge(issues.length+' to review',issues.length?'amber':'green')}</div>${issues.length?`<div class="card-body">${issues.slice(0,6).map(i=>`<div class="issue-item"><strong>${esc(customers.find(c=>c.phone===i.phone)?.name||i.phone)}</strong><p>${i.kind==='delivery_unknown'?'Delivery is uncertain. Check WhatsApp history before resending.':'Agent processing failed. Review the conversation and take over.'}</p>${buyerLink(i.phone,'Review conversation ↗')}</div>`).join('')}</div>`:empty('test','No recorded delivery or job failures','This reflects saved job and delivery states, not an end-to-end integration check.')}</section>
    <section class="card"><div class="card-head"><h2>Buyer context at a glance</h2></div>${buyerRows.length?`<div class="card-body">${buyerRows.map(c=>`<div class="context-row"><strong>${esc(c.name)}${c.test?' · Test':''}</strong><p>${esc(c.property_title||[c.preferences.bedrooms?c.preferences.bedrooms+' BHK':'',c.preferences.location].filter(Boolean).join(' · ')||'General enquiry')}</p><p>Confirmed budget: ${money(c.confirmed_budget)}</p>${buyerLink(c.phone,'View details ↗','ghost')}</div>`).join('')}</div>`:empty('properties','Property context appears here','A selected listing or saved buyer requirements will give your team a starting point.')}</section></div></div>`;
  bind('#open-calendar-visits','click',()=>$('#calendar-visits').showModal());
  bind('#close-calendar-visits','click',()=>$('#calendar-visits').close());
  openBuyerLinks();
  document.querySelectorAll('[data-calendar-visit]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      const result = await api('/visits/'+encodeURIComponent(button.dataset.calendarVisit)+'/apple-calendar',{method:'POST'});
      if ($('#calendar-visits')?.open) $('#calendar-visits').close();
      toast(result.status==='already_added'?'Already in Apple Calendar.':'Added to Estate AI Visits in Apple Calendar.');
    } catch(error) { toast(error.message); }
    finally { button.disabled = false; }
  });
  document.querySelectorAll('[data-overview-scope]').forEach(b=>b.addEventListener('click',()=>{state.overviewScope=b.dataset.overviewScope;sessionStorage.setItem('estate-overview-scope',state.overviewScope);renderOverview(nonce).catch(e=>toast(e.message));}));
  scheduleOverview(nonce);
}
async function renderProperties(nonce) {
  state.properties=await api('/properties');if(nonce!==state.nonce)return;
  await preloadCovers(state.properties);if(nonce!==state.nonce)return;
  $('#content').innerHTML=heading('Good matches start with good inventory.','Keep property details current so your agent can recommend with confidence.',`<div class="heading-actions">${button('Import Excel','import-inventory','secondary','arrow')}${button('Browse templates','browse-templates','secondary','properties')}${button('Add property','add-property')}</div>`)+
    `<div class="template-banner"><div><strong>More scenarios. Better testing.</strong><p>Explore 800 detailed fictional Biba templates across Mohali, Chandigarh, Panchkula, Zirakpur and Dera Bassi.</p></div>${button('Add sample properties','seed-properties','secondary','plus')}</div>`+
    `<div class="toolbar"><label class="search-field">${icon('search')}<input id="property-search" placeholder="Search by title, city or property ID" aria-label="Search properties"></label><div class="filter-tabs" role="group" aria-label="Filter properties"><button data-filter="all" class="selected">All properties</button><button data-filter="available">Available</button><button data-filter="unavailable">Unavailable</button></div></div><div id="properties-results"></div>`;
  bind('#add-property','click',()=>openProperty());
  bind('#import-inventory','click',openInventoryImport);
  bind('#browse-templates','click',showTemplates);
  bind('#seed-properties','click',async()=>{if(!state.status.demo_inventory_allowed||state.status.whatsapp_mode==='live'){toast('Enable ALLOW_DEMO_DATA=true in simulation mode and restart the backend to use sample inventory.');return;}$('#seed-properties').disabled=true;try{const result=await api('/demo/seed',{method:'POST'});toast(result.created_count?`Added ${result.created_count} fictional sample properties.`:'The sample properties are already in your inventory.');await renderProperties(state.nonce);}catch(error){$('#seed-properties').disabled=false;throw error;}});
  bind('#property-search','input',()=>{propertyPage=0;paintProperties();});
  document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{state.propertyFilter=b.dataset.filter;propertyPage=0; document.querySelectorAll('[data-filter]').forEach(item=>item.classList.toggle('selected',item===b));paintProperties();}));
  state.propertyFilter='all';propertyPage=0;paintProperties();
}
function paintProperties() {
  const term=($('#property-search')?.value||'').toLowerCase();
  const matches=state.properties.filter(p=>(state.propertyFilter==='all'||p.available===(state.propertyFilter==='available'))&&[p.title,p.city,p.locality,p.id].join(' ').toLowerCase().includes(term));
  propertyPage=Math.min(propertyPage,Math.max(0,Math.ceil(matches.length/24)-1));
  const rows=matches.slice(propertyPage*24,propertyPage*24+24);
  $('#properties-results').innerHTML=rows.length?`<div class="property-grid">${rows.map(p=>`<article class="property-card"><div class="property-cover">${cover(p)}${badge(p.demo?'Fictional demo':p.available?'Available':'Unavailable',p.demo?'amber':p.available?'green':'neutral')}<span class="property-ref">${esc(p.id)}${p.photos?.length?' · '+p.photos.length+' photos':''}</span></div><div class="property-content"><h3>${esc(p.title)}</h3><p>${esc([p.locality,p.city].filter(Boolean).join(', '))} · ${p.bedrooms} BHK${!p.available?' · Unavailable':''}</p><div class="property-price">${price(p.asking_price_inr)}<small>asking price</small></div><p>${esc(p.description.slice(0,100)||'No description added.')}</p></div><div class="property-footer"><span>Updated ${esc(date(p.verified_at))}</span><button class="button secondary" data-edit="${esc(p.id)}">View / edit ↗</button><button class="button primary" data-test-property="${esc(p.id)}" ${!p.available?'disabled':''}>Test this property ↗</button></div></article>`).join('')}</div>`:
    `<div class="card">${empty('properties',term?'No properties match your search':'Your inventory starts here',term?'Try another location or clear the filters.':'Add a verified listing. Your agent will be able to find and recommend it immediately.','', 'full-empty')}</div>`;
  document.querySelectorAll('[data-edit]').forEach(b=>b.addEventListener('click',()=>openProperty(state.properties.find(p=>p.id===b.dataset.edit))));
  document.querySelectorAll('[data-test-property]').forEach(b=>b.addEventListener('click',()=>openLead(b.dataset.testProperty)));
  $('#properties-results').insertAdjacentHTML('beforeend',`<div class="catalog-paging"><span>${matches.length} properties · Page ${propertyPage+1} of ${Math.max(1,Math.ceil(matches.length/24))}</span><button class="button secondary" id="property-prev" ${propertyPage===0?'disabled':''}>Previous</button><button class="button secondary" id="property-next" ${(propertyPage+1)*24>=matches.length?'disabled':''}>Next</button></div>`);
  bind('#property-prev','click',()=>{propertyPage--;paintProperties();});bind('#property-next','click',()=>{propertyPage++;paintProperties();});
}
async function showTemplates() {
  $('#template-dialog .eyebrow').textContent=state.status.business_name+' · 800 fictional properties';
  state.templates=await api('/property-templates');templatePage=0;$('#template-search').value='';
  paintTemplates();$('#template-dialog').showModal();
}
function paintTemplates() {
  const term=$('#template-search').value.toLowerCase().trim();
  const rows=state.templates.filter(p=>[p.title,p.id,p.city,p.locality,p.bedrooms+' BHK',p.description,p.details?.housing_listing_id].join(' ').toLowerCase().includes(term));
  templatePage=Math.min(templatePage,Math.max(0,Math.ceil(rows.length/20)-1));
  $('#template-list').innerHTML=rows.slice(templatePage*20,templatePage*20+20).map(p=>`<article class="template-option"><div><h3>${esc(p.title)}</h3><p>${esc(p.id)} · ${esc(p.details?.housing_listing_id)}</p><p>${esc(p.locality)}, ${esc(p.city)} · ${p.bedrooms} BHK · ${price(p.asking_price)}</p><details class="import-source"><summary>View full property description & specifications</summary><p>${esc(p.description)}</p><dl>${Object.entries(p.details||{}).map(([k,v])=>`<dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(v)}</dd>`).join('')}</dl></details><div class="catalog-paging"><button class="button primary" data-template-test="${esc(p.id)}">Test this property ↗</button><button class="button secondary" data-template="${esc(p.id)}">Use template ↗</button></div></div></article>`).join('')||'<p>No matching fictional templates.</p>';
  $('#template-paging').innerHTML=`<span>${rows.length} templates · Page ${templatePage+1} of ${Math.max(1,Math.ceil(rows.length/20))}</span><button class="button secondary" id="template-prev" ${templatePage===0?'disabled':''}>Previous</button><button class="button secondary" id="template-next" ${(templatePage+1)*20>=rows.length?'disabled':''}>Next</button>`;
  bind('#template-prev','click',()=>{templatePage--;paintTemplates();});bind('#template-next','click',()=>{templatePage++;paintTemplates();});
  document.querySelectorAll('[data-template-test]').forEach(b=>b.addEventListener('click',()=>openLead(b.dataset.templateTest)));
  document.querySelectorAll('[data-template]').forEach(b=>b.addEventListener('click',()=>{if(!state.status.demo_inventory_allowed||state.status.whatsapp_mode==='live'){toast('Demo templates require ALLOW_DEMO_DATA=true and simulation mode.');return;}const p=state.templates.find(p=>p.id===b.dataset.template);$('#template-dialog').close();const details={...p.details};delete details.housing_listing_id;openProperty({...p,details,id:p.id+'-'+crypto.randomUUID().slice(0,5),asking_price_inr:p.asking_price},true);}));
}
async function renderPortal(nonce) {
  if(state.status.whatsapp_mode==='live'||!state.status.demo_inventory_allowed){
    $('#content').innerHTML=heading('Test listing portal','Enable demo inventory in simulation mode to try a buyer enquiry.');
    return;
  }
  const listings=await api('/property-templates');
  if(nonce!==state.nonce)return;
  $('#content').innerHTML=heading('Biba listings','Choose a fictional home to test a buyer enquiry.')+
    `<section class="card"><div class="card-body"><form class="form-grid" id="portal-form">
    <label>Buyer name<input name="buyer" required maxlength="80" autocomplete="off"></label>
    <label>Search listings<input name="search" type="search" placeholder="City, locality or listing ID"></label>
    <label class="full-width">Property<select name="listing" required></select></label>
    <p class="full-width" id="portal-details"></p><button class="button primary" type="submit">I’m interested</button>
    <p role="status" id="portal-status"></p></form></div></section>`;
  const form=$('#portal-form'), fields=form.elements;
  const preview=()=>{
    const home=listings.find(item=>item.id===fields.listing.value);
    $('#portal-details').textContent=home?home.description:'No matching listings.';
    form.querySelector('button').disabled=!home;
  };
  const filter=()=>{
    const query=fields.search.value.trim().toLowerCase();
    const matches=listings.filter(home=>[home.city,home.locality,home.title,home.id].join(' ').toLowerCase().includes(query));
    fields.listing.replaceChildren(...matches.map(home=>new Option(
      home.title+' · '+home.locality+', '+home.city+' · '+price(home.asking_price),home.id)));
    preview();
  };
  fields.search.addEventListener('input',filter);
  fields.listing.addEventListener('change',preview);
  filter();
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const buyer=fields.buyer.value.trim();
    if(!buyer){$('#portal-status').textContent='Enter a buyer name.';return;}
    form.querySelector('button').disabled=true;
    try {
      const session=await api('/test-sessions',{method:'POST',body:JSON.stringify({
        name:buyer+' · '+fields.listing.value,buyer_name:buyer,property_id:fields.listing.value,portal_interest:true
      })});
      state.testPhone=session.phone;
      sessionStorage.setItem('estate-test-phone',session.phone);
      location.hash='test';
    } catch(error){
      if(nonce===state.nonce){$('#portal-status').textContent=error.message;preview();}
    }
  });
}
async function openLead(propertyId='') {
  if(state.status.whatsapp_mode==='live'){toast('Switch to simulation mode to test a buyer enquiry.');return;}
  state.properties=await api('/properties');
  if(!state.templates.length)state.templates=await api('/property-templates');
  const choices=new Map(state.properties.filter(p=>p.available).map(p=>[p.id,p]));
  if(state.status.demo_inventory_allowed)for(const p of state.templates)if(!choices.has(p.id))choices.set(p.id,p);
  if(propertyId&&!choices.has(propertyId)){toast('Enable demo inventory in simulation mode to test fictional templates.');return;}
  $('#lead-form').reset();$('#lead-error').textContent='';
  $('#lead-property').innerHTML='<option value="">General enquiry · no property selected</option>'+[...choices.values()].map(p=>`<option value="${esc(p.id)}" ${p.id===propertyId?'selected':''}>${esc(p.id)} · ${esc(p.title)}</option>`).join('');
  $('#template-dialog').close();$('#property-dialog').close();$('#lead-dialog').showModal();
}
bind('#template-search','input',()=>{templatePage=0;paintTemplates();});
bind('#close-lead','click',()=>$('#lead-dialog').close());
bind('#lead-form','submit',async event=>{
  event.preventDefault();$('#create-lead').disabled=true;$('#lead-error').textContent='';
  try{
    const buyer=$('#lead-buyer').value.trim();const property_id=$('#lead-property').value;
    const session=await api('/test-sessions',{method:'POST',body:JSON.stringify({name:buyer+' · '+(property_id||'General enquiry'),buyer_name:buyer,property_id,listing_id:$('#lead-listing').value.trim()})});
    state.testPhone=session.phone;sessionStorage.setItem('estate-test-phone',session.phone);$('#lead-dialog').close();
    if(location.hash==='#test')await renderTest(state.nonce);else location.hash='test';
  }catch(error){$('#lead-error').textContent=error.message;}finally{$('#create-lead').disabled=false;}
});
async function openProperty(property=null,fromTemplate=false) {
  draftDetails=property?.details||null;
  const form=$('#property-form');form.reset();$('#property-error').textContent='';
  form.elements.address.value=draftDetails?.address||'';
  draftFiles.forEach(item=>URL.revokeObjectURL(item.url));draftFiles=[];draftPhotos=fromTemplate?[]:(property?.photos||[]);draftPropertyId=fromTemplate?null:property?.id;
  $('#photo-upload-status').textContent='';$('#photo-previews').innerHTML='';
  $('#property-extra-details').innerHTML=property?.details&&Object.keys(property.details).length?`<details class="import-source"><summary>Property specifications</summary><dl>${Object.entries(property.details).map(([key,value])=>`<dt>${esc(key.replaceAll('_',' '))}</dt><dd>${esc(value)}</dd>`).join('')}</dl><p class="text-small muted">These saved specifications are available to the agent. Edit the description above for additional notes.</p></details>`:'';
  if(property?.import_source)$('#property-extra-details').innerHTML+=`<details class="import-source"><summary>Original sheet details · internal only</summary><p class="text-small muted">${esc(property.import_source.filename)} · ${esc(property.import_source.sheet)} · row ${esc(property.import_source.row)}. These source columns are not sent to the buyer-facing agent.</p><dl>${Object.entries(property.import_source.source_values||{}).map(([key,value])=>`<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join('')}</dl></details>`;
  $('#property-listing-ref').value=fromTemplate?'':(property?.housing_listing_ids?.[0]||'');
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
  return `<div class="chat-property-grid">${properties.map(p=>`<article class="chat-property-card"><div class="property-cover">${cover(p)}${badge(p.demo?'Fictional demo':p.available?'Available':'Unavailable',p.demo?'amber':p.available?'green':'neutral')}</div><div class="property-content"><h3>${esc(p.title)}</h3><p>${esc(p.locality)}, ${esc(p.city)} · ${p.bedrooms} BHK</p><div class="property-price">${price(p.asking_price_inr)}<small>asking price</small></div><p>${esc(p.id)}</p>${p.match_note?`<p class="related-note">${esc(p.match_note)}</p>`:''}${state.page==='test'?`<button type="button" class="button ghost" data-ask-property="${esc(p.id)}">Ask about this property ↗</button>`:''}</div></article>`).join('')}</div>`;
}
function chatMessages(messages,recommendations=[],outbox=[]) {
  const format = content => esc(content).replace(/\*\*([^\n]+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/^\*\s+/gm,'• ');
  return messages.map(m=>{
    const seen=new Set();
    const groups=recommendations.filter(batch=>m.id===(batch.message_id||'reply:'+batch.source_message_id)).map(batch=>{
      const properties=batch.properties.filter(p=>{if(seen.has(p.id))return false;seen.add(p.id);return true;});
      if(!properties.length)return '';
      const label=batch.kind==='related'?'Related properties':batch.kind==='selected'?'Your selected property':'Properties found';
      return `<section class="recommendation-group"><h4>${label}</h4>${batch.kind==='related'?`<p>Alternatives to ${esc(batch.source_property_id)} · locality and asking prices may differ</p>`:''}${recommendationCards(properties)}</section>`;
    }).join('');
    return `<article class="chat-message ${m.role==='user'?'user':'assistant'}"><div class="chat-author">${m.role==='user'?'Buyer':esc(state.status.business_name)+(m.author==='human'?' · Human team':' · AI assistant')}</div><div class="chat-bubble">${m.role==='user'?esc(m.content):format(m.content)}</div><div class="chat-time">${esc(date(m.created))}${m.author==='human'?' · '+esc(deliveryLabel(outbox.find(o=>o.message_id===m.id)?.state||'pending')):''}</div></article>${groups}`;
  }).join('');
}
function insights(customer) {
  const p=customer?.preferences||{};
  const fields=[['Location',p.location||'Not shared yet'],['Bedrooms',p.bedrooms!=null?p.bedrooms+' BHK':'Not shared yet'],['Confirmed budget',money(customer?.confirmed_budget)],['Buying timeline',p.timeline||'Not shared yet'],['Purpose',p.purpose||'Not shared yet']];
  return `<div class="insight-grid">${fields.map(([label,value])=>`<div class="insight"><span>${label}</span><strong>${esc(value)}</strong></div>`).join('')}</div>`;
}
function proposalsView(proposals, confirm=false) {
  if(!proposals?.length)return '<p class="muted text-small">Budgets, offers and visit requests appear here after the agent records them.</p>';
  return proposals.map(p=>`<article class="proposal"><div class="proposal-top"><strong>${esc({budget:'Buyer budget',offer:'Property offer',visit:'Site-visit request'}[p.kind]||p.kind)}</strong>${badge(p.status==='buyer_confirmed'?'Buyer confirmed':p.status==='requested'?'Dealer review':'Needs confirmation',p.status==='buyer_confirmed'?'green':'amber')}</div><p>${p.kind==='visit'?esc(visitDate(p.details.start_time)):money(p.details.amount_inr)}${p.details.property_id?' · '+esc(p.details.property_id):''}</p><p>${p.kind==='offer'?'An offer from the buyer; not an agreed sale price.':p.kind==='visit'?'Availability and booking still need dealer approval.':'Budget is separate from any property asking price.'}</p>${confirm===('reply:'+p.source_message_id)&&p.status==='pending_confirmation'&&proposals.filter(other=>other.source_message_id===p.source_message_id).length===1?`<button class="button secondary" data-confirm="${esc(p.id)}">Confirm these details ↗</button>`:''}<p>Source: <code>${esc(p.source_message_id)}</code></p>${p.confirmation_message_id?`<p>Confirmed in: <code>${esc(p.confirmation_message_id)}</code></p>`:''}</article>`).join('');
}
function alertSummary(detail) {
  if(String(detail).startsWith('Confirmed visit:'))return 'Buyer confirmed a visit request. Review the time and arrange team approval.';
  try{const data=JSON.parse(detail);return data.reason||detail;}catch{return detail;}
}
function handoffView(detail) {
  let data;try{data=JSON.parse(detail);}catch{return `<p>${esc(detail)}</p>`;}
  if(!data.reason)return `<p>${esc(detail)}</p>`;
  return `<div class="lead-context"><p><strong>${esc(data.reason)}</strong></p><p>${esc(data.buyer_name)} · ${esc(data.property_id||'General enquiry')} ${esc(data.listing_id||'')}</p><p>${esc(data.delivery)}</p>${(data.preferences_with_evidence||[]).map(p=>`<p>Buyer requirements: ${esc(Object.entries(p.values||{}).map(([k,v])=>k+': '+v).join(' · '))}</p>`).join('')}${(data.proposals||[]).map(p=>`<p>${esc(p.kind)} · ${esc(p.status)} · ${esc(p.details?.amount_inr?money(p.details.amount_inr):p.details?.start_time||'')} ${esc(p.details?.property_id||'')}</p>`).join('')}<details><summary>Recent conversation for your team</summary>${(data.recent_messages||[]).map(m=>`<p><strong>${esc(m.role==='user'?'Buyer':'Assistant')}:</strong> ${esc(m.text)}</p>`).join('')}</details></div>`;
}
function activityView(rows) {
  const relevant=rows.filter(a=>!['preferences','property_search_results'].includes(a.action));
  return relevant.length?relevant.map(a=>`<div class="activity"><strong>${esc(a.action.replaceAll('_',' '))}</strong><p>${esc(date(a.created))}</p>${a.action==='dealer_alert'?handoffView(a.detail):['opt_out','human_takeover','automation_resumed'].includes(a.action)?`<p>${esc(a.detail)}</p>`:''}</div>`).join(''):'<p class="muted text-small">Tool calls and handoffs will appear here as the agent works.</p>';
}
function deliveryLabel(value) {
  return ({pending:'Queued',sending:'Sending',simulated:'Simulated · stays in app',accepted:'Accepted by WhatsApp',sent:'Sent',delivered:'Delivered',read:'Read',delivery_unknown:'Delivery uncertain · review before retrying',suppressed:'Not sent'})[value]||value;
}
async function paintConversation(nonce) {
  const customer=state.customers.find(c=>c.phone===state.selectedPhone);
  if(!customer){$('#conversation-detail').innerHTML=empty('conversations','The context lives here','Select a conversation to explore its messages and buyer details.','','full-empty');return;}
  const phone=customer.phone;
  const [conversation,activity,recommendations]=await Promise.all([api('/conversations/'+phone),api('/conversations/'+phone+'/activity'),api('/conversations/'+phone+'/recommendations')]);
  await preloadCovers(recommendations.batches.flatMap(batch=>batch.properties));
  if(nonce!==state.nonce||state.page!=='conversations'||state.selectedPhone!==phone)return;
  const focused=document.activeElement?.id==='human-reply-text';
  const selection=focused?[$('#human-reply-text').selectionStart,$('#human-reply-text').selectionEnd]:null;
  const draft=humanDrafts.get(phone)||{text:'',token:crypto.randomUUID()};humanDrafts.set(phone,draft);
  const unavailable=conversation.opted_out?'This buyer opted out. Replies are blocked.':!conversation.paused?'Take over to reply yourself.':Date.now()/1000-conversation.last_inbound>=86400?'The reply window has closed. Wait for a new buyer message.':'Live WhatsApp is not enabled for this buyer.';
  $('#conversation-detail').innerHTML=`<div class="detail-head">${avatar(customer.name)}<div><h2>${esc(customer.name)}</h2><p class="muted text-small">${customer.test?'Test session · ':''}${conversation.opted_out?'Opted out':conversation.paused?'With your team · AI paused':'AI replies enabled'}</p></div>${conversation.opted_out?badge('Opted out','red'):button(conversation.paused?'Resume AI':'Take over','toggle-pause','secondary','human')}</div>
    ${customer.property_id?`<div class="inbox-property"><strong>Interested property</strong> ${esc(customer.property_title)} · ${esc(customer.property_id)}</div>`:''}
    <div class="details-tabs">${[['messages','Messages'],['profile','Buyer details'],['activity','Activity & handoffs']].map(([key,label])=>`<button data-tab="${key}" class="${state.conversationTab===key?'selected':''}">${label}</button>`).join('')}</div>
    ${state.conversationTab==='messages'?`<div class="chat-history" id="conversation-history">${conversation.messages.length?chatMessages(conversation.messages,recommendations.batches,conversation.outbox):empty('conversations','Waiting for the first hello','No messages in this conversation yet.')}</div><div class="human-compose"><div class="human-compose-head"><strong>Reply as ${esc(state.status.business_name)}</strong>${badge(customer.test?'App simulation':'WhatsApp',customer.test?'amber':'green')}</div><p>${customer.test?'Your reply appears in this test chat. Nothing is sent to WhatsApp.':'Your reply will be sent to this buyer on WhatsApp.'} AI remains paused until you resume it.</p>${conversation.manual_reply_available?`<form id="human-reply-form"><label class="sr-only" for="human-reply-text">Reply to buyer</label><textarea id="human-reply-text" aria-label="Reply to buyer" rows="3" maxlength="4000" required placeholder="Write your reply to the buyer…">${esc(draft.text)}</textarea><div id="reply-preview" role="status" class="muted" style="white-space:pre-wrap"></div><div class="human-compose-actions"><button type="button" class="button secondary" id="suggest-reply" aria-label="Suggest a reply">🪄 Suggest reply</button><button type="button" class="button secondary" id="accept-reply" hidden>Accept suggestion (Tab)</button><button type="submit" class="button primary" id="send-human-reply">${customer.test?'Send test reply':'Send WhatsApp reply'} ↗</button></div></form>`:`<div class="notice">${esc(unavailable)}</div>`}<p class="error-text" id="human-reply-error" role="alert"></p></div>`:state.conversationTab==='profile'?`<div class="card-body">${insights(customer)}<h3 style="margin:22px 0 13px">Budgets, offers & visit requests</h3>${proposalsView(customer.proposals)}</div>`:`<div class="card-body">${activityView(activity)}</div>`}`;
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{state.conversationTab=b.dataset.tab;paintConversation(nonce).catch(e=>toast(e.message));}));
  bind('#toggle-pause','click',async()=>{await api('/conversations/'+phone+(conversation.paused?'/resume':'/takeover'),{method:'POST'});toast(conversation.paused?'AI resumed for future messages.':'Conversation taken over. You can now reply.');await renderConversations(nonce);});
  function showSuggestion() {
    const preview = $('#reply-preview');
    if (!preview || state.selectedPhone !== phone) return;
    const field = $('#human-reply-text');
    const inline = draft.suggestion && !field.value;
    field.placeholder = inline ? draft.suggestion : 'Write your reply to the buyer…';
    field.rows = inline ? Math.min(12, Math.max(3, Math.ceil(draft.suggestion.length / 50))) : 3;
    preview.textContent = draft.loading ? 'Writing a suggestion…' : (inline ? '' : draft.suggestion || '');
    $('#accept-reply').hidden = !draft.suggestion;
    $('#suggest-reply').disabled = Boolean(draft.loading);
  }
  function acceptSuggestion() {
    if (!draft.suggestion) return;
    const field = $('#human-reply-text');
    field.value = draft.suggestion;
    field.dispatchEvent(new Event('input'));
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  }
  showSuggestion();
  bind('#accept-reply','click',acceptSuggestion);
  bind('#human-reply-text','keydown',event=>{
    if (event.key === 'Tab' && !event.shiftKey && draft.suggestion) {
      event.preventDefault();
      acceptSuggestion();
    }
  });
  bind('#suggest-reply','click',async()=>{
    const token = draft.token;
    draft.loading = true;
    draft.suggestion = '';
    showSuggestion();
    $('#human-reply-text').focus();
    try {
      const result = await api('/conversations/'+phone+'/suggest-reply',{
        method:'POST',body:JSON.stringify({draft:draft.text})
      });
      if (draft.token === token) draft.suggestion = result.text;
    } finally {
      draft.loading = false;
      showSuggestion();
    }
  });
  bind('#human-reply-text','input',event=>{draft.suggestion="";draft.text=event.target.value;showSuggestion();draft.token=crypto.randomUUID();});
  bind('#human-reply-form','submit',async event=>{
    event.preventDefault();if(state.humanSending)return;state.humanSending=true;
    $('#send-human-reply').disabled=true;$('#human-reply-error').textContent='';
    try{const result=await api('/conversations/'+phone+'/reply',{method:'POST',body:JSON.stringify({text:draft.text,event_id:draft.token})});humanDrafts.delete(phone);toast(result.channel==='simulate'?'Test reply queued. It stays in the app.':'Your reply is queued for WhatsApp.');await paintConversation(nonce);}
    catch(error){if($('#human-reply-error'))$('#human-reply-error').textContent=error.message;}
    finally{state.humanSending=false;if($('#send-human-reply'))$('#send-human-reply').disabled=false;}
  });
  const history=$('#conversation-history');if(history)history.scrollTop=history.scrollHeight;
  if(state.focusReply){state.focusReply=false;$('#human-reply-text')?.focus();}
  if(focused&&$('#human-reply-text')){$('#human-reply-text').focus();$('#human-reply-text').setSelectionRange(...selection);}
  scheduleConversation(nonce,phone,JSON.stringify([conversation,activity]));
}
function scheduleConversation(nonce,phone,snapshot) {
  clearTimeout(state.timer);
  state.timer=setTimeout(async()=>{
    if(state.page!=='conversations'||nonce!==state.nonce||phone!==state.selectedPhone)return;
    try{
      if(state.humanSending){scheduleConversation(nonce,phone,snapshot);return;}
      const latest=await Promise.all([api('/conversations/'+phone),api('/conversations/'+phone+'/activity')]);
      if(JSON.stringify(latest)!==snapshot)await paintConversation(nonce);
      else scheduleConversation(nonce,phone,snapshot);
    }catch(error){if(state.page==='conversations'&&nonce===state.nonce)scheduleConversation(nonce,phone,snapshot);}
  },4000);
}
async function renderTest(nonce) {
  state.testSessions=await api('/test-sessions');if(nonce!==state.nonce)return;
  if(!state.testSessions.length&&state.status.whatsapp_mode!=='live') state.testSessions=[await api('/test-sessions',{method:'POST',body:JSON.stringify({name:'Test conversation 1'})})];
  if(nonce!==state.nonce)return;
  if(!state.testSessions.some(s=>s.phone===state.testPhone))state.testPhone=state.testSessions[0]?.phone;
  if(state.testPhone)sessionStorage.setItem('estate-test-phone',state.testPhone);
  $('#content').innerHTML=heading('A conversation is the best test.','Meet your real agent. Explore its answers, tools and understanding.',button('New conversation','new-test','secondary'))+
    `<div class="test-layout"><section class="card test-chat"><div class="card-head"><div><h2>${icon('test')} ${esc(state.status.business_name)} assistant</h2><p>${esc(state.status.model)} · ${esc(modelProviders[state.status.provider])}</p></div><select class="session-select" id="test-session-select" aria-label="Select test conversation">${state.testSessions.map(s=>`<option value="${s.phone}" ${s.phone===state.testPhone?'selected':''}>${esc(s.name)}</option>`).join('')}</select></div><div class="test-banner">${icon('test')}Real agent & tools · Test messages stay here. Nothing is sent to WhatsApp.</div><div id="test-history" class="chat-history"></div><div id="recommendation-controls" class="recommendation-controls"></div><div id="thinking" class="thinking" hidden>Agent is thinking and checking its tools…</div><div class="chat-compose"><form id="chat-form"><textarea id="chat-input" aria-label="Message your agent" rows="2" maxlength="4000" placeholder="Ask about a property, share a budget, or request a visit…" required></textarea><button class="button primary" id="send-message" type="submit" aria-label="Send message">${icon('send')}</button></form><small>Enter to send · Shift + Enter for a new line · Synthetic buyer session</small><p id="chat-error" class="error-text" role="alert"></p></div></section>
    <aside class="test-context card-stack"><section class="card"><div class="card-head"><div><h2>What your agent knows</h2><p>Saved buyer requirements</p></div>${icon('human')}</div><div class="card-body" id="test-insights"></div></section><section class="card"><div class="card-head"><h2>Confirmations & requests</h2></div><div class="card-body" id="test-proposals"></div></section><section class="card"><div class="card-head"><div><h2>Agent activity</h2><p>Actual tool calls and handoffs</p></div></div><div class="card-body" id="test-activity"></div></section></aside></div>`;
  bind('#new-test','click',()=>openLead());
  bind('#test-session-select','change',async event=>{state.testPhone=event.target.value;sessionStorage.setItem('estate-test-phone',state.testPhone);await loadTestData();if(state.pending[state.testPhone])pollTest();});
  bind('#chat-form','submit',async event=>{event.preventDefault();await sendTestMessage($('#chat-input').value.trim());});
  bind('#chat-input','keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#chat-form').requestSubmit();}});
  await loadTestData();if(state.pending[state.testPhone])pollTest();
}
async function loadTestData() {
  const phone=state.testPhone;
  if(!phone){$('#test-history').innerHTML=empty('test','Testing is unavailable','Switch WHATSAPP_MODE to simulate and restart the backend.');$('#send-message').disabled=true;return;}
  const [conversation,customers,activity,recommendations]=await Promise.all([api('/conversations/'+phone),api('/conversations?phone='+encodeURIComponent(phone)),api('/conversations/'+phone+'/activity'),api('/conversations/'+phone+'/recommendations')]);
  await preloadCovers(recommendations.batches.flatMap(batch=>batch.properties));
  if(state.page!=='test'||phone!==state.testPhone)return;
  const waiting = conversation.jobs?.find(job=>['pending','processing'].includes(job.state));
  if(waiting)state.pending[phone]=waiting.id;
  const customer=customers.find(c=>c.phone===phone);
  const history=$('#test-history');const nearBottom=history.scrollHeight-history.scrollTop-history.clientHeight<90;
  history.innerHTML=conversation.messages.length?chatMessages(conversation.messages,recommendations.batches,conversation.outbox):empty('test','Say hello to your agent','Start like a buyer would. Your agent can search inventory, remember requirements and prepare visit requests.',`<div class="suggestions"><button class="suggestion" data-prompt="Hi, I’m looking for a 3 BHK in Mohali.">Find a home in Mohali</button><button class="suggestion" data-prompt="My budget is 90 lakh.">Share a budget</button><button class="suggestion" data-prompt="What properties do you have available?">Explore available properties</button></div>`);
  if(!conversation.messages.length&&state.testSessions.find(s=>s.phone===phone)?.property_id){history.innerHTML=empty('test','Your property context is ready','Say Hi. Your company’s AI assistant already knows your test name and selected property.',`<button class="suggestion" data-prompt="Hi">Say Hi</button>`);}
  if(nearBottom||state.pending[phone])history.scrollTop=history.scrollHeight;
  const lead=state.testSessions.find(s=>s.phone===phone);
  $('#test-insights').innerHTML=(lead?.property_id?`<div class="lead-context"><strong>Buyer: ${esc(lead.buyer_name||customer?.name)}</strong><p>Interested in ${esc(lead.property?.title||lead.property_id)}</p><p>${esc(lead.property_id)} · ${esc(lead.listing_id||'Manual property selection')}</p><small>Simulated lead · ${esc(state.status.business_name)} AI assistant</small></div>`:'')+insights(customer);
  $('#test-proposals').innerHTML=proposalsView(customer?.proposals,conversation.messages.at(-1)?.id);
  $('#test-activity').innerHTML=activityView(activity);
  const paused=conversation.paused||conversation.opted_out;
  const blocked=Boolean(state.pending[phone])||paused||state.status.whatsapp_mode==='live';
  const relatedMode=recommendations.batches.at(-1)?.kind==='related';
  const hasRelated=recommendations.batches.some(b=>b.kind==='related');
  $('#recommendation-controls').innerHTML=`${lead?.property_id?`<button class="button secondary" id="related-properties" ${blocked||(relatedMode&&!recommendations.has_more)?'disabled':''}>${hasRelated?'More related properties':'Show related properties'} ↗</button>`:''}${recommendations.has_search&&!relatedMode?`<button class="button secondary" id="more-properties" ${blocked||!recommendations.has_more?'disabled':''}>Show more matches ↗</button>`:''}<button class="button ghost" id="browse-properties" ${blocked?'disabled':''}>Browse all inventory ↗</button>${recommendations.has_search&&!recommendations.has_more?`<small>${relatedMode?'No unseen related homes remain in the same city, BHK and price range. Ask to adjust the criteria.':'No unseen matches for the current search. Ask to adjust your criteria, or browse all inventory.'}</small>`:''}`;
  bind('#related-properties','click',()=>queuePropertyAction('related'));
  bind('#more-properties','click',()=>queuePropertyAction('more'));
  bind('#browse-properties','click',()=>queuePropertyAction('browse'));
  $('#send-message').disabled=Boolean(state.pending[phone])||conversation.opted_out||state.status.whatsapp_mode==='live';
  $('#thinking').hidden=!state.pending[phone];
  $('#thinking').textContent=paused?'Saving buyer message…':'Agent is thinking and checking its tools…';
  $('#chat-error').textContent=conversation.opted_out?'This test buyer opted out. Start a new conversation.':paused?'AI is paused. You can still send buyer messages here. Reply as the company from Conversations, or resume AI there.':'';
  document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{ $('#chat-input').value=b.dataset.prompt;$('#chat-input').focus();}));
  document.querySelectorAll('[data-confirm]').forEach(b=>b.addEventListener('click',()=>sendTestMessage('Yes').catch(e=>toast(e.message))));
  document.querySelectorAll('[data-ask-property]').forEach(b=>b.addEventListener('click',()=>{$('#chat-input').value='Tell me more about property '+b.dataset.askProperty;$('#chat-input').focus();}));
  if(conversation.paused&&!state.pending[phone]){clearTimeout(state.timer);state.timer=setTimeout(()=>{if(state.page==='test'&&state.testPhone===phone)loadTestData().catch(error=>toast(error.message));},4000);}
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
      if(state.page==='test'&&phone===state.testPhone){
        if(!terminal){pollTest();return;}
        await loadTestData();
        if(job.state==='failed')$('#chat-error').textContent='The model could not complete this message after retries. Check the active model in Settings, then start a new test.';
      }
    } catch(error){if(state.page==='test'){$('#chat-error').textContent=error.message;delete state.pending[phone];$('#thinking').hidden=true;$('#send-message').disabled=false;}}
  },500);
}
async function renderSettings(nonce) {
  if(nonce!==state.nonce)return;const s=state.status;
  const setting=(label,value)=>`<div class="setting-row"><span>${esc(label)}</span><code>${esc(value)}</code></div>`;
  $('#content').innerHTML=heading('The essentials behind your agent.','Model configuration and integration status. Everything in plain sight.',button('Soul','open-soul','secondary','settings'))+
    `<div class="settings-grid"><div class="card-stack"><section class="card"><div class="card-head"><div><h2>AI model</h2><p>Used for new agent replies</p></div>${badge(modelProviders[s.provider],'green')}</div><div class="card-body">
    <div class="settings-rows">${setting('Active model',s.model)}${setting('Background worker',s.worker_enabled?'Enabled':'Disabled')}</div>
    <form id="model-form" class="form-grid">
      <label class="full-width">Provider<select id="model-provider">${Object.entries(modelProviders).map(([id,name])=>`<option value="${id}" ${id===s.provider?'selected':''}>${esc(name)}</option>`).join('')}</select></label>
      <div id="hosted-model-fields" class="full-width form-grid">
        <label class="full-width">Model ID<select id="model-id"></select></label>
        <label class="full-width" id="custom-model-field" hidden>Custom model ID<input id="custom-model-id" maxlength="160" autocomplete="off" spellcheck="false"><small>Enter a tool-capable model ID available to your provider account.</small></label>
        <label class="full-width">API key<input id="model-api-key" type="password" maxlength="4096" autocomplete="new-password" spellcheck="false"><small id="model-key-hint"></small></label>
      </div>
      <div class="full-width"><button type="submit" class="button primary" id="save-model">Check and save</button></div>
      <p class="full-width text-small" id="model-result" role="status"></p>
    </form>
    ${s.provider==='ollama'?`<div class="settings-rows">${setting('Ollama endpoint',s.ollama_base_url)}${setting('Authentication',s.ollama_api_key_required?(s.ollama_api_key_configured?'API key configured':'API key missing'):'Local Ollama account')}</div>
    <div style="margin-top:20px">${button('Check Ollama connection','check-ollama','secondary','arrow')}</div><div id="connection-check" aria-live="polite"></div>`:''}
    </div></section>
    <section class="card"><div class="card-head"><h2>Workspace</h2></div><div class="card-body settings-rows">
    <dialog id="soul-panel" aria-labelledby="soul-title"><h2 id="soul-title">Soul of the agent</h2>
    <label>Import Markdown<input type="file" id="soul-file" accept=".md,.markdown,text/markdown"></label>
    <label>How should the agent respond?<textarea id="soul-text" rows="12" maxlength="12000" placeholder="Use a warm tone and ask one question at a time."></textarea></label>
    <button type="button" class="button secondary" id="generate-soul">🪄 Generate Soul</button>
    <button type="button" class="button secondary" id="download-soul">Download soul.md</button>
    <p id="soul-status" role="status"></p><button class="button primary" id="save-soul">Save soul</button> <button class="button secondary" id="close-soul">Cancel</button></dialog><form id="company-form"><label>Company name<input id="company-name" required maxlength="120" value="${esc(s.business_name)}"></label><p class="muted text-small">Used in new AI replies and handoff messages. Existing conversation history stays unchanged.</p><button type="submit" class="button secondary" id="save-company">Save company name ↗</button><p id="company-result" role="status"></p></form>${setting('Business timezone',s.timezone)}${setting('Database',s.database)}${setting('Demo inventory permission',s.demo_inventory_allowed?'Allowed in simulation':'Disabled')}</div></section></div>
    <div class="card-stack"><section class="card"><div class="card-head"><div><h2>Integrations</h2><p>Configured does not always mean connected</p></div></div><div class="card-body"><div class="integration"><span class="integration-icon">${icon('conversations')}</span><div><h3>WhatsApp</h3><p>${s.whatsapp_mode==='simulate'?'Test conversations only · no messages sent':s.whatsapp_credentials_configured?'Credentials configured · delivery not verified':'Credentials missing'}</p></div>${badge(s.whatsapp_mode==='simulate'?'Simulation':'Live mode',s.whatsapp_mode==='simulate'?'amber':'blue')}</div><div class="integration"><span class="integration-icon">${icon('visit')}</span><div><h3>Apple Calendar</h3><p>Buyer-confirmed requests for tomorrow in India time are added automatically for dealer review.</p></div>${s.calendar==='apple_calendar'?button('Check connection','check-calendar','secondary','visit'):badge('Requires macOS')}</div><div class="integration"><span class="integration-icon">${icon('properties')}</span><div><h3>99acres & Housing.com</h3><p>Lead-source adapters are planned</p></div>${badge('Not connected')}</div></div></section></div></div>`;
  const modelForm=$('#model-form'), provider=$('#model-provider'), model=$('#model-id'), key=$('#model-api-key');
  const saveModel=$('#save-model'), result=$('#model-result');
  const customModel=$('#custom-model-id');
  const paintCustomModel=()=>{
    const isCustom=model.value==='__custom__';
    $('#custom-model-field').hidden=!isCustom;
    customModel.required=isCustom;
    customModel.disabled=!isCustom;
  };
  const paintModelFields=()=>{
    const ollama=provider.value==='ollama', reuseKey=provider.value===s.provider&&s.model_key_configured;
    $('#hosted-model-fields').hidden=ollama;
    model.required=!ollama;
    key.required=!ollama&&!reuseKey;
    const savedModel=provider.value===s.provider&&!ollama?s.model:'';
    const choices=new Set([...(modelPresets[provider.value]||[]), ...(savedModel?[savedModel]:[])]);
    model.innerHTML='<option value="">Choose a model</option>'
      + [...choices].map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join('')
      + '<option value="__custom__">Enter a custom model ID</option>';
    model.value=savedModel;
    customModel.value='';
    paintCustomModel();
    key.value='';
    $('#model-key-hint').textContent=reuseKey?'Leave blank to keep the saved key.':'Paste the API key for this provider.';
    saveModel.disabled=ollama&&s.provider==='ollama';
    saveModel.textContent=ollama?'Use Ollama':'Check and save';
    result.textContent='';
    result.classList.remove('error-text');
  };
  paintModelFields();
  provider.addEventListener('change',paintModelFields);
  model.addEventListener('change',paintCustomModel);
  modelForm.addEventListener('submit',async event=>{
    event.preventDefault();
    const ollama=provider.value==='ollama';
    saveModel.disabled=true;
    provider.disabled=true;
    result.classList.remove('error-text');
    result.textContent=ollama?'Switching to Ollama…':'Checking the model…';
    try {
      const saved=await api('/settings/model',ollama?{method:'DELETE'}:{method:'PUT',
        body:JSON.stringify({provider:provider.value,
          model:model.value==='__custom__'?customModel.value.trim():model.value,api_key:key.value})});
      key.value='';
      if(nonce!==state.nonce)return;
      Object.assign(state.status,saved);
      await renderSettings(nonce);
      const modelResult=$('#model-result');
      if(modelResult)modelResult.textContent=`Saved. New replies use ${saved.model}.`;
    } catch(error) {
      key.value='';
      result.textContent=error.message;
      result.classList.add('error-text');
    } finally {
      saveModel.disabled=false;
      provider.disabled=false;
    }
  });
  bind('#check-calendar','click',async event=>{
    const button = event.currentTarget;
    await api('/integrations/apple-calendar/check',{method:'POST'});
    button.textContent = 'Connected';
  });
  const soulPanel = $('#soul-panel'), soulText = $('#soul-text');
  bind('#open-soul','click',async () => {
    const saved = await api('/settings/soul');
    soulText.value = saved.text;
    $('#soul-file').value = '';
    $('#soul-status').textContent = '';
    soulPanel.showModal();
  });
  const soulStatus = $('#soul-status');
  let generation = null;
  soulPanel.addEventListener('close', () => generation?.abort());
  bind('#generate-soul','click',async event => {
    const generate = event.currentTarget;
    const controls = [generate, soulText, $('#soul-file'), $('#save-soul'), $('#download-soul')];
    generation = new AbortController();
    controls.forEach(control => control.disabled = true);
    soulStatus.textContent = 'Writing your Soul…';
    try {
      const result = await api('/settings/soul/generate', {
        method:'POST', body:JSON.stringify({text:soulText.value}), signal:generation.signal
      });
      soulText.value = result.text;
      soulStatus.textContent = 'Draft ready. Edit it, then save to apply.';
    } catch (error) {
      if (error.name !== 'AbortError') soulStatus.textContent = error.message;
    } finally {
      generation = null;
      controls.forEach(control => control.disabled = false);
    }
  });
  bind('#download-soul','click',() => {
    if (!soulText.value.trim()) {
      soulStatus.textContent = 'Write or generate a Soul first.';
      return;
    }
    const url = URL.createObjectURL(new Blob([soulText.value], {type:'text/markdown;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'soul.md';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  bind('#close-soul','click',() => soulPanel.close());
  bind('#soul-file','change',async event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 48000) throw new Error('Soul instructions can contain up to 12,000 characters.');
    const content = await file.text();
    if (content.length > 12000) throw new Error('Soul instructions can contain up to 12,000 characters.');
    soulText.value = content;
  });
  bind('#save-soul','click',async event => {
    const save = event.currentTarget;
    save.disabled = true;
    try {
      await api('/settings/soul',{method:'PUT',body:JSON.stringify({text:soulText.value})});
      soulPanel.close();
      toast('Soul saved for future AI replies.');
    } finally { save.disabled = false; }
  });
  bind('#company-form','submit',async event=>{event.preventDefault();$('#save-company').disabled=true;try{const saved=await api('/settings/company',{method:'PUT',body:JSON.stringify({business_name:$('#company-name').value.trim()})});state.status.business_name=saved.business_name;$('.workspace-label strong').textContent=saved.business_name;$('.workspace-avatar').textContent=saved.business_name.trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();$('#company-result').textContent='Saved. New replies use '+saved.business_name+'.';}catch(error){$('#company-result').textContent=error.message;}finally{$('#save-company').disabled=false;}});
  bind('#check-ollama','click',async()=>{const b=$('#check-ollama');b.disabled=true;b.textContent='Checking connection…';try{const result=await api('/integrations/ollama/check',{method:'POST'});if(state.page!=='settings')return;$('#connection-check').className='connection-result'+(!result.reachable||!result.model_available?' bad':'');$('#connection-check').textContent=result.message;}finally{if(state.page==='settings'){b.disabled=false;b.innerHTML=icon('arrow')+'Check Ollama connection';}}});
}
bind('#property-form','submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const values=new FormData(form);
  const body={id:values.get('id').trim(),title:values.get('title').trim(),city:values.get('city').trim(),locality:values.get('locality').trim(),bedrooms:Number(values.get('bedrooms')),asking_price:Number(values.get('asking_price')),description:values.get('description').trim(),available:form.elements.available.checked,demo:form.elements.demo.checked};
  const address=values.get('address').trim();
  if(draftDetails||address){
    body.details={...draftDetails};
    if(address)body.details.address=address;
    else delete body.details.address;
  }
  $('#save-property').disabled=true;$('#property-error').textContent='';
  let propertySaved=false;
  try{const saved=await api('/properties/'+encodeURIComponent(body.id),{method:'PUT',body:JSON.stringify(body)});propertySaved=true;const listingRef=$('#property-listing-ref').value.trim();if(listingRef)await api('/housing-listings/'+encodeURIComponent(listingRef),{method:'PUT',body:JSON.stringify({property_id:body.id})});draftPropertyId=body.id;draftPhotos=saved.photos||[];form.elements.id.readOnly=true;form.elements.demo.disabled=true;
    while(draftFiles.length){const item=draftFiles[0];$('#photo-upload-status').textContent=`Uploading ${item.file.name}…`;const photo=await api('/properties/'+encodeURIComponent(body.id)+'/photos',{method:'POST',body:item.file,headers:{'Content-Type':item.file.type||'application/octet-stream'}});draftFiles.shift();URL.revokeObjectURL(item.url);if(!draftPhotos.some(p=>p.id===photo.id))draftPhotos.push(photo);await loadPhoto(photo);paintDraftPhotos();}
    $('#property-dialog').close();toast('Property and photos saved. Your agent can use the updated details.');if(state.page==='properties')await renderProperties(state.nonce);
  }catch(error){$('#property-error').textContent=(propertySaved?'Property saved, but a listing link or photo could not be saved: ':'')+error.message;$('#photo-upload-status').textContent='Saved property data and uploaded photos are retained. Correct the error and retry Save property.';}finally{$('#save-property').disabled=false;}
});
bind('#property-photo-input','change',event=>{
  for(const file of event.target.files){if(draftPhotos.length+draftFiles.length>=10){toast('A property can have up to 10 photos.');break;}if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024){toast('Choose JPEG, PNG or WebP photos no larger than 8 MB each.');continue;}draftFiles.push({file,url:URL.createObjectURL(file)});}
  event.target.value='';paintDraftPhotos();
});
bind('#close-property','click',()=>$('#property-dialog').close());bind('#cancel-property','click',()=>$('#property-dialog').close());
bind('#close-templates','click',()=>$('#template-dialog').close());
bind('#login-dialog','cancel',event=>event.preventDefault());
bind('#login-form','submit',async event=>{event.preventDefault();state.key=$('#admin-key').value.trim();$('#login-error').textContent='';try{await api('/status');sessionStorage.setItem('estate-admin',state.key);$('#admin-key').value='';$('#login-dialog').close();await navigate();}catch(error){$('#login-error').textContent=error.message;}});
function lockWorkspace(){clearTimeout(state.timer);state.key='';sessionStorage.removeItem('estate-admin');navigate();}
bind('#lock-workspace','click',lockWorkspace);
bind('#mobile-lock-workspace','click',lockWorkspace);
bind('#refresh','click',()=>navigate());
window.addEventListener('hashchange',navigate);
navigate();
