'use strict';
const els = {
  slots: document.querySelector('#slots'), provider: document.querySelector('#provider-filter'),
  count: document.querySelector('#slot-count'), refresh: document.querySelector('#refresh'),
  notice: document.querySelector('#notice'), overlay: document.querySelector('#booking-overlay'),
  selected: document.querySelector('#selected-slot'), close: document.querySelector('#close-modal'),
  form: document.querySelector('#booking-form'), formError: document.querySelector('#form-error'),
  submit: document.querySelector('#submit-booking'), success: document.querySelector('#success-view'),
  formView: document.querySelector('#form-view'), confirmation: document.querySelector('#confirmation-detail'),
  done: document.querySelector('#done-button'), csrf: document.querySelector('#csrf-token')
};
let allSlots = [], selectedSlot = null, pendingKey = null, pendingSignature = null, previousFocus = null;
const displayDate = iso => new Intl.DateTimeFormat(undefined,{weekday:'short',month:'short',day:'numeric',year:'numeric'}).format(new Date(iso));
const displayTime = iso => new Intl.DateTimeFormat(undefined,{hour:'numeric',minute:'2-digit'}).format(new Date(iso));
const futureAvailable = slot => slot.available && new Date(slot.start).getTime() > Date.now();
function showNotice(message) { els.notice.textContent = message; els.notice.hidden = !message; }
function node(tag, cls, content) { const n = document.createElement(tag); if (cls) n.className = cls; if (content !== undefined) n.textContent = content; return n; }
async function api(url, options={}) {
  const response = await fetch(url,{credentials:'same-origin',cache:'no-store',...options});
  let data; try {data = await response.json();} catch {data = {};}
  if(!response.ok){let error = new Error(data.error || 'Something went wrong. Please try again.'); error.status = response.status; error.retryAfter=response.headers.get('Retry-After'); throw error;}
  return data;
}
async function loadSlots() {
  showNotice(''); els.slots.replaceChildren(node('div','empty-panel','Loading available appointments…'));
  try {
    const result = await api('/web/slots'); allSlots = Array.isArray(result.slots)?result.slots:[];
    const providers=[...new Set(allSlots.map(s=>s.provider).filter(Boolean))].sort();
    const current=els.provider.value; els.provider.replaceChildren(new Option('All providers',''));
    providers.forEach(p=>els.provider.add(new Option(p,p)));
    els.provider.value=providers.includes(current)?current:'';
    renderSlots();
  } catch(e){showNotice(e.message);els.slots.replaceChildren(node('div','empty-panel','Appointments are temporarily unavailable. Please try refreshing.'));els.count.textContent='Could not load appointments';}
}
function renderSlots(){
  const selected=els.provider.value;
  const slots=allSlots.filter(s=>futureAvailable(s)&&(!selected||s.provider===selected)).sort((a,b)=>new Date(a.start)-new Date(b.start));
  els.count.textContent=`${slots.length} available appointment${slots.length===1?'':'s'}`;
  els.slots.replaceChildren();
  if(!slots.length){els.slots.append(node('div','empty-panel','No upcoming appointments available for this selection. Try another provider or refresh later.'));return;}
  for(const slot of slots){
    const card=node('article','slot-card'); const top=node('div','slot-top');
    top.append(node('span','provider-icon','✳'),node('span','slot-badge','● Available'));
    const name=node('h3','',slot.provider), date=node('div','slot-date',displayDate(slot.start));
    const time=node('div','slot-time',`${displayTime(slot.start)} – ${displayTime(slot.end)}`);
    const button=node('button','book-button','Select appointment  →');button.type='button';button.addEventListener('click',()=>openBooking(slot));
    card.append(top,name,date,time,button);els.slots.append(card);
  }
}
function openBooking(slot){selectedSlot=slot;pendingKey=null;pendingSignature=null;previousFocus=document.activeElement;els.form.reset();els.formError.hidden=true;els.formView.hidden=false;els.success.hidden=true;
  els.selected.replaceChildren(node('strong','',slot.provider),node('span','',`${displayDate(slot.start)} · ${displayTime(slot.start)} – ${displayTime(slot.end)}`));
  els.overlay.hidden=false;document.body.style.overflow='hidden';document.querySelector('#patient-name').focus();
}
function closeBooking(){if(!els.submit.disabled){els.overlay.hidden=true;document.body.style.overflow='';selectedSlot=null;if(previousFocus?.isConnected)previousFocus.focus();}}
function showFormError(message){els.formError.textContent=message;els.formError.hidden=false;}
async function submitBooking(event){event.preventDefault();if(!selectedSlot||els.submit.disabled)return;const name=document.querySelector('#patient-name').value.trim();const email=document.querySelector('#patient-email').value.trim();
  if(!name||!email){showFormError('Please enter your name and email address.');return;}
  const body={slot_id:selectedSlot.id,name,email};const signature=JSON.stringify(body);if(signature!==pendingSignature){pendingKey=crypto.randomUUID();pendingSignature=signature;}
  els.submit.disabled=true;els.submit.textContent='Confirming your appointment…';els.formError.hidden=true;
  try{
    const booking=await api('/web/bookings',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':els.csrf.value,'Idempotency-Key':pendingKey},body:signature});
    els.formView.hidden=true;els.success.hidden=false;els.confirmation.replaceChildren();
    const entries=[['Patient',booking.name],['Provider',selectedSlot.provider],['Appointment',`${displayDate(selectedSlot.start)} · ${displayTime(selectedSlot.start)}`],['Email',booking.email],['Booking ID',booking.id]];
    for(const [label,value] of entries){const div=node('div');div.append(node('strong','',`${label}: `),node('span','',value));els.confirmation.append(div);}
    await loadSlots();
  }catch(e){
    let message=e.message;if(e.status===429)message=`Too many booking attempts. Please try again in ${e.retryAfter||'a few'} seconds.`;
    if(e.status===409){message='This appointment was just booked by someone else. Close this window and choose another time.';loadSlots();}
    if(e.status===403)message='Your form session has expired. Refresh the page and try again.';
    showFormError(message);
  }finally{els.submit.disabled=false;els.submit.replaceChildren(document.createTextNode('Confirm appointment '),node('span','','→'));}
}
els.provider.addEventListener('change',renderSlots);els.refresh.addEventListener('click',loadSlots);els.close.addEventListener('click',closeBooking);els.done.addEventListener('click',closeBooking);els.form.addEventListener('submit',submitBooking);
els.overlay.addEventListener('click',event=>{if(event.target===els.overlay)closeBooking();});document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!els.overlay.hidden)closeBooking();});
loadSlots();
