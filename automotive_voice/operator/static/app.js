/* M08 vanilla JS, local-only. No external assets, microphone, PII or real audio. */
'use strict';
let csrf = null;
let snapshot = null;
let selectedSession = null;
let activeView = 'overview';
let pending = false;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const el = id => document.getElementById(id);
const labels = {overview:'Genel bakış',sessions:'Oturumlar',pronunciation:'Telaffuz inceleme',audit:'Olay günlüğü',scenarios:'M09 Senaryolar',readiness:'M10 Hazırlık'};
function toast(message,error=false) { const e=el('toast'); e.textContent=message; e.classList.toggle('error',error); e.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>e.classList.add('hidden'),4200); }
async function getJSON(url) { const r=await fetch(url,{cache:'no-store'}); const d=await r.json(); if(!r.ok)throw new Error(d.error||'request_failed');return d; }
async function action(name,extra={}) { if(pending)return;pending=true;try {
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Console-CSRF':csrf},body:JSON.stringify({action:name,...extra})});
  const d=await r.json();if(!r.ok)throw new Error(d.error||'action_failed');
  if(name==='open')selectedSession=d.result.session_id;
  toast(name==='fake_ack'?'Yalnızca sahte taşıma ACK doğrulandı.':name==='run_scenario'?`${d.result.scenario} · ${d.result.passed?'PASS':'FAIL'}`:`${name} • ${d.result.reason||'uygulandı'}`);
  await refresh();
} catch(e){toast(e.message,true);}finally{pending=false;}}
function showView(name){activeView=name;document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!=='view-'+name));document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===name));el('view-crumb').textContent=labels[name];}
function statusCls(state){return ['READY','CLOSED','LISTENING'].includes(state)?'': ['SPEAKING'].includes(state)?'speaking': ['INTERRUPTING','DEGRADED','OPEN'].includes(state)?'interrupt': ['ENDED','FAILED'].includes(state)?'terminal':'';}
function healthRow(a){const ok=a.state==='ready'&&a.circuit==='closed';return `<div class="adapter-row"><div class="service-icon">${esc(({tts:'TS',stt:'ST',llm:'LM',telephony:'PB'})[a.kind]||'AD')}</div><div class="service-info"><div class="service-name">${esc(a.kind.toUpperCase())} <span class="service-meta">· synthetic</span></div><div class="service-meta">Devre: ${esc(a.circuit)} · Bekleyen: ${a.queued} · Aktif: ${a.in_flight} · Tamamlanan: ${a.completed}</div></div><span class="status ${ok?'':'warning'}">${esc(a.state)}</span></div>`;}
function activityRow(e){const good=e.decision==='applied'||e.decision==='accepted'||e.decision==='ok';const warn=e.decision==='rejected'||e.decision==='ignored';return `<div class="event-row"><span class="event-bullet ${good?'success':warn?'warning':''}"></span><div class="event-text"><strong>${esc(e.kind)}</strong><small>${esc(e.session)} · ${esc(e.decision)} · ${esc(e.reason)}</small></div><span class="event-time">${e.clock_ms} ms</span></div>`;}
function empty(title,detail){return `<div class="empty"><div class="empty-symbol">◌</div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;}
function renderOverview(d){
 const c=d.counts; el('metrics').innerHTML=`
  <div class="stat"><div class="stat-label">Toplam oturum</div><div class="stat-value">${c.sessions}</div><div class="stat-footer">Sentetik oturum sayısı</div></div>
  <div class="stat"><div class="stat-label">Aktif oturum</div><div class="stat-value good">${c.active}</div><div class="stat-footer">Terminal olmayan durumlar</div></div>
  <div class="stat"><div class="stat-label">Flush onayı bekleyen</div><div class="stat-value ${c.waiting_flush?'warn':''}">${c.waiting_flush}</div><div class="stat-footer">Yalnızca sahte ACK kabul edilir</div></div>
  <div class="stat"><div class="stat-label">Sanal zaman</div><div class="stat-value">${d.simulation_time_ms}<small style="font-size:13px;color:#94a4b0"> ms</small></div><div class="stat-footer">Gerçek gecikme ölçümü değildir</div></div>`;
 el('adapter-list').innerHTML=d.adapters.map(healthRow).join('');
 el('recent-events').innerHTML=d.timeline.length?'<div class="event-list">'+d.timeline.slice(0,6).map(activityRow).join('')+'</div>':empty('Henüz olay bulunmuyor','Yeni bir sentetik oturum başlatın.');
 el('overview-sessions').innerHTML=d.sessions.length?d.sessions.slice(0,8).map(s=>`<div class="session-list-row"><div class="session-detail"><span class="session-id">${esc(s.session_id)}</span><span class="state-chip ${statusCls(s.state)}">${esc(s.state)}</span><span class="muted">Tur ${s.turn_id} · Nesil ${s.generation_id}</span></div><button data-open-session="${esc(s.session_id)}">Yönet</button></div>`).join(''):empty('Aktif simülasyon yok','Oturum oluşturarak VAD, STT ve LLM durumlarını inceleyebilirsiniz.');
}
function renderSessions(d){el('session-count').textContent=d.sessions.length;
 if(selectedSession && !d.sessions.some(s=>s.session_id===selectedSession))selectedSession=null;
 if(!selectedSession && d.sessions.length)selectedSession=d.sessions[0].session_id;
 el('session-list').innerHTML=d.sessions.length?d.sessions.map(s=>`<button class="session-choice ${s.session_id===selectedSession?'selected':''}" data-select-session="${esc(s.session_id)}"><span class="session-id">${esc(s.session_id)}</span><span class="sub"><span>${esc(s.state)}</span><span>T${s.turn_id} · G${s.generation_id}</span></span></button>`).join(''):empty('Oturum yok','Yeni oturum düğmesini kullanın.');
 const s=d.sessions.find(s=>s.session_id===selectedSession);
 el('selected-session-description').textContent=s?s.session_id:'Bir oturum seçin';
 el('state-badge').textContent=s?s.state:'—';el('state-badge').className='state-chip '+(s?statusCls(s.state):'');
 el('session-detail').innerHTML=s?`<div class="detail-grid"><div class="detail-box"><span>TurnId</span><strong>${s.turn_id}</strong></div><div class="detail-box"><span>GenerationId</span><strong>${s.generation_id}</strong></div><div class="detail-box"><span>M01 olay kuyruğu</span><strong>${s.pending_events}</strong></div><div class="detail-box"><span>M02 audit kayıtları</span><strong>${s.audit_count}</strong></div></div>`:empty('Oturum seçin','İşlemler yalnızca oluşturduğunuz sentetik oturumlarda çalışır.');
 el('action-controls').querySelectorAll('button').forEach(b=>{b.disabled=!s || ['ENDED','FAILED'].includes(s.state) ||(b.dataset.action==='fake_ack'&&!s.pending_flush_id);});
 const m=s?[
 ['Flush bariyeri',s.pending_flush_id?'FAKE ACK bekleniyor':'Bekleyen yok'],
 ['Medya kuyruğu',s.queued_chunks+' parça · '+s.queued_ms+' ms'],
 ['Transport',s.transport_paused?'XOFF / kilitli':'XON / uygun'],
 ['Taşıma kuyruğu',s.transport_queued+' metadata']]:[['Flush bariyeri','—'],['Medya kuyruğu','—'],['Transport','—'],['Taşıma kuyruğu','—']];
 el('media-summary').innerHTML='<div class="media-grid">'+m.map(x=>`<div class="media-card"><span>${esc(x[0])}</span><strong>${esc(x[1])}</strong></div>`).join('')+'</div>';
}
function renderPronunciation(d){el('sources').innerHTML=d.sources.length?d.sources.map(s=>`<div class="source-row"><h3>${esc(s.title)}</h3><div class="meta">${esc(s.creator)} · ${esc(s.id)}</div><div class="source-foot"><span class="pill warn">${esc(s.permission_claim_status)}</span><span class="pill">${esc(s.rights_basis)}</span></div></div>`).join(''):empty('Kaynak bulunamadı','A01-YT veritabanına erişilemiyor.');
 const total=d.annotations.length;const approved=d.annotations.filter(a=>a.review?.decision==='approved').length;
 el('pronunciation-summary').innerHTML=`<div class="pronun-summary"><div class="big">${approved}<span style="font-size:16px;color:#9eacb8;font-weight:500"> / ${total}</span></div><strong>Yerel operatör tarafından onaylanan kayıt</strong><p>Kaynakta ses/transkript kanıtı olmadan onay verilemez. Aktif M04 telaffuz sözlüğü bu ekranla değişmez.</p><div class="progress-track"><div class="progress-bar" style="width:${total?100*approved/total:0}%"></div></div></div>`;
 el('annotation-count').textContent=total+' kayıt';
 el('annotations').innerHTML=total?'<div class="table-wrap"><table><thead><tr><th>Kaynak</th><th>Terim / okunuş</th><th>Aralık</th><th>Kanıt</th><th>Karar</th></tr></thead><tbody>'+d.annotations.map(a=>`<tr><td>${esc(a.source_id)}</td><td>${esc(a.canonical)}<br><span class="muted">${esc(a.spoken_tr)}</span></td><td>${esc(a.start_sec)}–${esc(a.end_sec)} sn</td><td>${a.has_clip_reference&&a.transcript_checked?'Kontrol edilebilir':'Eksik'}</td><td>${esc(a.review?.decision||'bekliyor')}<div style="margin-top:6px;display:flex;gap:5px"><button class="btn small" data-approve="${esc(a.id)}">Onayla*</button><button class="btn small" data-reject="${esc(a.id)}">Reddet</button></div></td></tr>`).join('')+'</tbody></table></div>':empty('İnceleme kuyruğu boş','Henüz gerçek sesle ilişkilendirilmiş anotasyon bulunmuyor. Ses veya kanıt uydurulmadı.');
}

function renderGolden(d){
 const summary=d.golden_summary||{}, cases=d.golden_cases||[];
 el('golden-stats').innerHTML=`<div class="golden-summary"><span><strong>${summary.input_count||0}</strong> kaynak cümle</span><span><strong>${summary.changed_texts||0}</strong> değişen</span><span><strong>${summary.review_required||0}</strong> inceleme</span><span><strong>${summary.unsupported_char_cases||0}</strong> karakter uyumsuzluğu</span></div>`;
 const filter=el('golden-filter').value;
 const subset=cases.filter(c=>filter==='all'||filter==='review'&&c.review_required==='1'||filter==='changed'&&c.changed==='1');
 el('golden-rows').innerHTML=subset.map(c=>`<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.category)}</td><td>${esc(c.original)}</td><td>${esc(c.prepared)}</td><td><span class="pill ${c.review_required==='1'?'warn':'ok'}">${c.review_required==='1'?'İnceleme':'Hazır'}</span></td></tr>`).join('')||'<tr><td colspan="5">Bu filtreyle eşleşen vaka yok.</td></tr>';
}
function renderScenarios(d){
 el('scenario-count').textContent=d.scenario_catalog.length+' senaryo';
 el('scenario-catalog').innerHTML=d.scenario_catalog.map(n=>`<button class="btn outline scenario-run" data-scenario="${esc(n)}" ${pending?'disabled':''}><span>${esc(n.replaceAll('_',' '))}</span><small>Çalıştır</small></button>`).join('');
 el('scenario-reports').innerHTML=(d.scenario_reports||[]).length?d.scenario_reports.map(r=>`<section class="scenario-report"><div class="scenario-report-head"><strong>${esc(r.scenario)}</strong><span class="pill ${r.passed?'ok':'warn'}">${r.passed?'PASS':'FAIL'}</span></div><div class="scenario-checks">${Object.entries(r.checks).map(([k,v])=>`<span class="pill ${v?'ok':'warn'}">${v?'✓':'✕'} ${esc(k)}</span>`).join('')}</div><div class="muted" style="padding:10px 0">Oturumlar: ${r.sessions.map(s=>esc(s.id)+' · '+esc(s.state)+' · T'+s.turn).join(' | ')}</div><details><summary>Olay izleri (${r.trace.length})</summary><div class="table-wrap"><table><thead><tr><th>ms</th><th>Olay</th><th>Karar</th><th>Oturum</th></tr></thead><tbody>${r.trace.map(t=>`<tr><td>${t.ms}</td><td>${esc(t.step)}</td><td>${esc(t.outcome)}</td><td>${esc(t.session)}</td></tr>`).join('')}</tbody></table></div></details></section>`).join(''):empty('Henüz senaryo çalıştırılmadı','Yukarıdan bir sentetik test seçin.');
}
function renderReadiness(d){
 const r=d.m10_readiness;
 el('m10-readiness').innerHTML=r? r.adapters.map(a=>`<div class="adapter-row"><div class="service-icon">${esc(a.adapter.substring(0,2).toUpperCase())}</div><div class="service-info"><div class="service-name">${esc(a.adapter.toUpperCase())} · DRY RUN</div><div class="service-meta">${a.findings.length?a.findings.map(esc).join(' · '):'Yapılandırma tutarlı; gerçek bağlantı doğrulanmadı'}</div></div><span class="status warning">HOLD</span></div>`).join('') : empty('Denetim alınamadı','M10 sözleşme sonuçları bulunmuyor.');
}
function renderAudit(d){el('audit-rows').innerHTML=d.timeline.length?d.timeline.map(e=>`<tr><td class="mono">${e.clock_ms} ms</td><td>${esc(e.kind)}</td><td><code>${esc(e.session)}</code></td><td>${esc(e.decision)}</td><td>${esc(e.reason)}</td></tr>`).join(''):'<tr><td colspan="5">Henüz olay kaydı yok.</td></tr>';}
async function refresh(){try{snapshot=await getJSON('/api/snapshot');renderOverview(snapshot);renderSessions(snapshot);renderPronunciation(snapshot);renderGolden(snapshot);renderScenarios(snapshot);renderReadiness(snapshot);renderAudit(snapshot);}catch(e){toast('Durum verileri alınamadı: '+e.message,true);}}
document.addEventListener('click',e=>{
 const view=e.target.closest('[data-view]');if(view){showView(view.dataset.view);return;}
 const go=e.target.closest('[data-goto]');if(go){showView(go.dataset.goto);return;}
 const select=e.target.closest('[data-select-session]');if(select){selectedSession=select.dataset.selectSession;renderSessions(snapshot);return;}
 const open=e.target.closest('[data-open-session]');if(open){selectedSession=open.dataset.openSession;showView('sessions');renderSessions(snapshot);return;}
 const button=e.target.closest('[data-action]');if(button){if(selectedSession)action(button.dataset.action,{session_id:selectedSession});return;}
 const scenario=e.target.closest('[data-scenario]');if(scenario){action('run_scenario',{scenario:scenario.dataset.scenario});return;}
 const tick=e.target.closest('[data-tick]');if(tick){action('tick',{delta_ms:Number(tick.dataset.tick)});return;}
 const approve=e.target.closest('[data-approve]');if(approve){action('review',{annotation_id:approve.dataset.approve,decision:'approved',reviewer:'operator_01',reason_code:'verified_evidence'});return;}
 const reject=e.target.closest('[data-reject]');if(reject){action('review',{annotation_id:reject.dataset.reject,decision:'rejected',reviewer:'operator_01',reason_code:'insufficient_evidence'});return;}
});
async function boot(){try{const start=await getJSON('/api/bootstrap');csrf=start.csrf;await refresh();document.querySelectorAll('#create-overview,#create-sessions').forEach(b=>b.addEventListener('click',()=>action('open')));el('refresh-log').addEventListener('click',refresh);el('golden-filter').addEventListener('change',()=>{if(snapshot)renderGolden(snapshot)});setInterval(()=>{if(!document.hidden&&!pending)refresh();},4000);}catch(e){toast('Konsol başlatılamadı: '+e.message,true);}}
boot();
