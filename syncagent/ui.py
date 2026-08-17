"""The dashboard page. One file, no build step, no CDN."""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SyncAgent</title>
<style>
  :root{
    --ground:#EDEFEA; --panel:#F6F7F3; --ink:#1B211E; --soft:#5C6660;
    --rule:#C7CDC3; --claude:#3B5E4A; --gemini:#2E5C8A; --codex:#7A6A2F;
    --antigravity:#6B4A7A;
    --alert:#A8392B; --live:#3B5E4A;
    --mono:"JetBrains Mono","Cascadia Code","SF Mono",ui-monospace,Menlo,
           "DejaVu Sans Mono",Consolas,monospace;
    --serif:"Iowan Old Style","Source Serif 4",Charter,Georgia,
            "Times New Roman",serif;
  }
  @media (prefers-color-scheme:dark){
    :root{--ground:#141815;--panel:#1C211D;--ink:#E4E8E2;--soft:#8D968F;
          --rule:#333A35;--claude:#7FB394;--gemini:#7CA9D6;--codex:#C4B26A;
          --antigravity:#B592C4;
          --alert:#E0705E;--live:#7FB394;}
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--mono);
       font-size:14.5px;line-height:1.6;padding:28px 24px 64px;
       -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
  h1{font-family:var(--serif);font-weight:400;font-size:38px;margin:0;letter-spacing:-.015em}
  h2{font-size:11.5px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
     color:var(--soft);margin:0 0 12px;border-bottom:1px solid var(--rule);padding-bottom:7px}
  .wrap{max-width:1240px;margin:0 auto}
  header{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;
         border-bottom:2px solid var(--ink);padding-bottom:13px;margin-bottom:22px}
  .sub{color:var(--soft);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
  .panel{background:var(--panel);border:1px solid var(--rule);padding:16px;margin-bottom:20px}
  .cols{display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start}
  @media(max-width:900px){.cols{grid-template-columns:1fr}}
  .none{color:var(--soft);font-style:italic}
  button{font-family:var(--mono);font-size:12.5px;padding:6px 12px;cursor:pointer;
         background:var(--ink);color:var(--ground);border:1px solid var(--ink)}
  button.ghost{background:transparent;color:var(--ink);border-color:var(--rule)}
  button:disabled{opacity:.35;cursor:not-allowed}
  input,select,textarea{font-family:var(--mono);font-size:13.5px;background:var(--ground);
    color:var(--ink);border:1px solid var(--rule);padding:7px 9px}
  textarea{width:100%;resize:vertical;min-height:74px;line-height:1.55}

  /* composer */
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
  .steps{margin-top:12px;border-top:1px solid var(--rule);padding-top:11px}
  .steprow{display:grid;grid-template-columns:112px 96px 1fr 30px;gap:7px;
           margin-bottom:7px;align-items:center}
  @media(max-width:640px){.steprow{grid-template-columns:1fr 1fr}}
  .hint{font-size:12px;color:var(--soft);margin-top:8px}

  /* seats */
  .seat{margin-bottom:15px;padding-bottom:13px;border-bottom:1px solid var(--rule)}
  .seat:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}
  .sname{font-weight:600;font-size:16px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
       background:var(--rule);margin-right:7px;vertical-align:middle}
  .s-live .dot{background:var(--live);animation:pulse 1.8s infinite}
  .s-idle .dot{background:var(--codex)}
  .s-missing .dot,.s-never .dot{background:transparent;border:1px solid var(--rule)}
  .s-blocked .dot{background:var(--alert)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(127,179,148,.55)}
    70%{box-shadow:0 0 0 6px rgba(127,179,148,0)}
    100%{box-shadow:0 0 0 0 rgba(127,179,148,0)}}
  .c-claude .sname{color:var(--claude)} .c-gemini .sname{color:var(--gemini)}
  .c-codex .sname{color:var(--codex)}
  .c-antigravity .sname{color:var(--antigravity)}
  .smeta{font-size:12.5px;color:var(--soft)}
  .warnbox{border-left:3px solid var(--alert);padding:7px 0 7px 10px;margin-top:8px;
           font-size:12.5px;color:var(--alert)}

  /* queue */
  .queue{display:flex;align-items:center;gap:12px;font-size:12.5px;
         border:1px solid var(--rule);background:var(--panel);padding:9px 13px;
         margin-bottom:20px}
  .queue b{font-weight:600}
  .spin{display:inline-block;width:9px;height:9px;border-radius:50%;
        background:var(--live);animation:pulse 1.4s infinite;margin-right:6px}

  /* topics */
  .topic{border:1px solid var(--rule);background:var(--panel);margin-bottom:16px}
  .thead{padding:13px 15px;display:flex;justify-content:space-between;gap:12px;
         align-items:baseline;cursor:pointer;flex-wrap:wrap}
  .thead:hover{background:var(--ground)}
  .tneed{font-family:var(--serif);font-size:20px;letter-spacing:-.01em}
  .tmeta{font-size:11.5px;color:var(--soft);letter-spacing:.08em;text-transform:uppercase}
  .tbody{padding:0 15px 15px;border-top:1px solid var(--rule)}
  .chain{margin:13px 0}
  .turn{border-left:2px solid var(--rule);padding:2px 0 2px 13px;margin-bottom:3px}
  .turn.done{border-left-color:var(--live)}
  .turn.running{border-left-color:var(--codex)}
  .turn.failed{border-left-color:var(--alert)}
  .turn.skipped{opacity:.5}
  .thead2{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
  .tag{display:inline-block;padding:1px 7px;font-size:10.5px;letter-spacing:.08em;
       text-transform:uppercase;border:1px solid currentColor}
  .g-claude{color:var(--claude)} .g-gemini{color:var(--gemini)} .g-codex{color:var(--codex)}
  .g-antigravity{color:var(--antigravity)}
  .job{flex:1;min-width:180px}
  .tiny{font-size:11.5px;color:var(--soft)}
  .arrow{color:var(--soft);font-size:12px;padding:3px 0 6px 13px}
  .arrow b{color:var(--ink);font-weight:600}
  .err{color:var(--alert);font-size:12.5px;padding:2px 0 4px 13px}
  .doc{background:var(--ground);border:1px solid var(--rule);padding:14px 16px;
       margin-top:9px;max-height:460px;overflow-y:auto}
  .doc h2,.doc h3{border:none;font-family:var(--serif);text-transform:none;
       letter-spacing:0;font-size:17px;color:var(--ink);margin:14px 0 6px;padding:0}
  .doc h2:first-child,.doc h3:first-child{margin-top:0}
  .doc ul{margin:6px 0;padding-left:20px}
  .doc li{margin:3px 0}
  .doc p{margin:7px 0}
  .doc code{background:var(--panel);padding:1px 4px;font-size:13px}
  .doc a{color:var(--gemini)}
  .answer{border-color:var(--live);border-left-width:3px}

  /* budget */
  .big{font-family:var(--serif);font-size:40px;line-height:1.1;letter-spacing:-.02em}
  .cap{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--soft)}
  .warn .big{color:var(--alert)}
  .meter{display:flex;gap:2px;margin-top:7px;height:12px}
  .seg{flex:1;background:var(--rule);opacity:.45}
  .seg.lit{opacity:1;background:var(--ink)}
  .warn .seg.lit{background:var(--alert)}
  .week{margin-top:12px;padding-left:13px;border-left:2px solid var(--rule)}
  .week .big{font-size:26px}
  .fine{font-size:11.5px;color:var(--soft);margin-top:13px;font-style:italic}
  .stamp{color:var(--soft);font-size:11px;letter-spacing:.1em;margin-top:22px;
         text-align:right;text-transform:uppercase}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>SyncAgent</h1>
    <span class="sub" id="where"></span>
  </header>

  <div class="panel">
    <h2>Put a need on the table</h2>
    <textarea id="need" placeholder="How is my resume for the posting in table/inputs/?"></textarea>
    <div class="row">
      <select id="lens"></select>
      <button id="send">Put it on the table</button>
      <button class="ghost" id="toggleplan">Divide it up</button>
      <span class="tiny" id="planhint"></span>
    </div>
    <div class="steps" id="planbox" style="display:none">
      <div id="planrows"></div>
      <div class="row">
        <button class="ghost" id="addstep">+ step</button>
        <span class="tiny">Runs top to bottom, one at a time. A seat can insert a detour by handing off.</span>
      </div>
    </div>
    <div class="hint" id="composerhint"></div>
  </div>

  <div class="queue" id="queue"></div>

  <div class="cols">
    <div>
      <div class="panel">
        <h2>Seats</h2>
        <div id="seats"></div>
        <div class="row"><button class="ghost" id="doctor">Check seats</button></div>
      </div>
    </div>

    <div>
      <div id="topics"></div>

      <div class="panel">
        <h2>Claude limits <span id="budgetflag" style="color:var(--alert)"></span></h2>
        <div id="budget"></div>
      </div>
    </div>
  </div>
  <div class="stamp" id="stamp"></div>
</div>

<script>
const SEGS = 24;
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const clock = ts => ts ? new Date(ts).toLocaleTimeString([],
  {hour:'2-digit',minute:'2-digit'}) : '';
let STATE = null, OPEN = {}, DOCS = {}, PLAN = null, BUSY = false, WEEKS = false;

function ago(s){
  if (s == null) return 'never';
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.round(s/60) + 'm ago';
  if (s < 86400) return Math.round(s/3600) + 'h ago';
  return Math.round(s/86400) + 'd ago';
}
function meter(percent){
  const lit = Math.round(Math.min(Math.max(percent,0),100)/100*SEGS);
  let out = '';
  for (let i = 0; i < SEGS; i++) out += '<div class="seg' + (i<lit?' lit':'') + '"></div>';
  return out;
}

/* Just enough markdown for the turn files. Not a parser - a renderer for the
   four things a turn actually contains. */
function md(src){
  const lines = String(src||'').split('\n');
  let out = '', inList = false;
  const inline = t => esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g,
             '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  for (let raw of lines){
    const line = raw.replace(/\s+$/,'');
    if (/^<!--/.test(line)) continue;
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li){ if(!inList){out += '<ul>'; inList = true;} out += '<li>' + inline(li[1]) + '</li>'; continue; }
    if (inList){ out += '</ul>'; inList = false; }
    if (h){ out += '<h3>' + inline(h[2]) + '</h3>'; continue; }
    if (!line.trim()) continue;
    out += '<p>' + inline(line) + '</p>';
  }
  if (inList) out += '</ul>';
  return out || '<p class="none">empty</p>';
}

async function post(path, body){
  BUSY = true;
  try {
    const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify(body||{})});
    const d = await r.json();
    if (!d.ok) alert(d.error || 'failed');
    return d;
  } catch(e){ alert('request failed: ' + e); return {ok:false}; }
  finally { BUSY = false; tick(); }
}

/* ---------------------------------------------------------------- composer */

function defaultPlan(){
  return (STATE ? STATE.relay : []).map(n => ({
    seat: n, depth: (STATE.seats[n]||{}).depth || 'light',
    job: (STATE.seats[n]||{}).role || ''
  }));
}
function renderPlan(){
  if (!PLAN) PLAN = defaultPlan();
  const names = Object.keys(STATE.seats);
  document.getElementById('planrows').innerHTML = PLAN.map((s,i) => `
    <div class="steprow">
      <select data-i="${i}" data-k="seat">${names.map(n =>
        `<option value="${esc(n)}"${n===s.seat?' selected':''}>${esc(n)}</option>`).join('')}</select>
      <select data-i="${i}" data-k="depth">${STATE.depths.map(d =>
        `<option value="${esc(d)}"${d===s.depth?' selected':''}>${esc(d)}</option>`).join('')}</select>
      <input data-i="${i}" data-k="job" value="${esc(s.job)}" placeholder="what this seat should do">
      <button class="ghost" data-del="${i}">&times;</button>
    </div>`).join('');
  document.querySelectorAll('#planrows [data-k]').forEach(el => {
    el.onchange = el.oninput = () => { PLAN[+el.dataset.i][el.dataset.k] = el.value; };
  });
  document.querySelectorAll('#planrows [data-del]').forEach(el => {
    el.onclick = () => { PLAN.splice(+el.dataset.del,1); renderPlan(); };
  });
}
document.getElementById('toggleplan').onclick = () => {
  const box = document.getElementById('planbox');
  const show = box.style.display === 'none';
  box.style.display = show ? '' : 'none';
  document.getElementById('toggleplan').textContent = show ? 'Use the default relay' : 'Divide it up';
  if (show){ PLAN = PLAN || defaultPlan(); renderPlan(); } else { PLAN = null; }
};
document.getElementById('addstep').onclick = () => {
  const n = STATE.relay[0] || Object.keys(STATE.seats)[0];
  PLAN.push({seat:n, depth:(STATE.seats[n]||{}).depth||'light', job:''});
  renderPlan();
};
document.getElementById('send').onclick = async () => {
  const need = document.getElementById('need').value.trim();
  if (!need) return;
  const btn = document.getElementById('send');
  btn.disabled = true; btn.textContent = 'placing...';
  const d = await post('/api/topic', {need, lens: document.getElementById('lens').value,
                                      steps: PLAN});
  btn.disabled = false; btn.textContent = 'Put it on the table';
  if (d.ok){ document.getElementById('need').value = ''; OPEN[d.topic] = true; }
};
document.getElementById('doctor').onclick = async () => {
  const b = document.getElementById('doctor');
  b.disabled = true; b.textContent = 'checking...';
  await post('/api/doctor', {});
  b.disabled = false; b.textContent = 'Check seats';
};

/* ------------------------------------------------------------------ render */

function renderSeats(d){
  const LABEL = {live:'live', idle:'idle', cold:'not running', missing:'not installed',
                 never:'never used', blocked:'blocked'};
  document.getElementById('seats').innerHTML = Object.entries(d.seats).map(([n,s]) => `
    <div class="seat c-${esc(n)} s-${esc(s.state)}">
      <div class="thead2">
        <span class="sname"><span class="dot"></span>${esc(n)}</span>
        <span class="tiny">${LABEL[s.state]||s.state}${
          s.state==='idle'||s.state==='cold' ? ' &middot; '+ago(s.idle_seconds) : ''}</span>
      </div>
      <div class="smeta">${esc(s.role)}</div>
      <div class="smeta">depth ${esc(s.depth)}${s.scribe?' &middot; scribe (writes files)':' &middot; advises only'}
        &middot; ${s.turns} turns</div>
      ${s.problem ? '<div class="warnbox">'+esc(s.problem)+'</div>' : ''}
    </div>`).join('');
}

function renderQueue(d){
  const r = d.runner.running;
  document.getElementById('queue').innerHTML = r
    ? `<span><span class="spin"></span><b>${esc(r.seat)}</b> is working on
        ${esc(r.topic)} &mdash; step ${esc(r.step)}</span>
       <span class="tiny">${d.runner.waiting} waiting &middot; one seat runs at a time</span>`
    : `<span class="tiny">Nothing running.${d.runner.waiting ? ' '+d.runner.waiting+' queued.' : ''}
        One seat runs at a time &mdash; never two.</span>`;
}

function turnRow(t, s){
  const key = t.id + '/' + s.n;
  const open = DOCS[key];
  let html = `<div class="turn ${esc(s.status)}">
    <div class="thead2">
      <span class="tag g-${esc(s.seat)}">${esc(s.seat)}</span>
      <span class="job">${esc(s.job)}</span>
      <span class="tiny">${esc(s.depth)} ${clock(s.finished)}</span>
      ${s.file ? `<button class="ghost" data-doc="${esc(key)}" data-file="${esc(s.file)}"
         data-topic="${esc(t.id)}">${open?'hide':'read'} ${esc(s.file)}</button>` : ''}
      ${s.status==='queued'||s.status==='skipped'||s.status==='failed'
        ? `<button class="ghost" data-run="${esc(t.id)}" data-step="${s.n}">run</button>` : ''}
    </div>`;
  if (s.error) html += `<div class="err">${esc(s.error)}</div>`;
  if (open) html += `<div class="doc">${md(open)}</div>`;
  html += '</div>';
  if (s.handoff){
    const h = s.handoff;
    const to = h.to === 'none' ? 'closed the topic'
             : h.to === 'user' ? 'needs <b>you</b>' : 'handed to <b>'+esc(h.to)+'</b>';
    html += `<div class="arrow">&#8627; ${to}${h.job?': '+esc(h.job):''}${
      h.why?' <span class="tiny">('+esc(h.why)+')</span>':''}${
      h.unknown_seat?' <span class="tiny">&mdash; named "'+esc(h.unknown_seat)+'", which is not a seat here</span>':''}</div>`;
  }
  return html;
}

function renderTopics(d){
  if (!d.topics.length){
    document.getElementById('topics').innerHTML =
      '<div class="panel"><span class="none">Nothing on the table yet.</span></div>';
    return;
  }
  document.getElementById('topics').innerHTML = d.topics.map(t => {
    const open = OPEN[t.id];
    const done = t.steps.filter(s => s.status === 'done').length;
    let body = '';
    if (open){
      body = `<div class="tbody"><div class="chain">${
        t.steps.map(s => turnRow(t,s)).join('')}</div>
        <div class="row">
          <button class="ghost" data-next="${esc(t.id)}">run next step</button>
          <button class="ghost" data-answer="${esc(t.id)}">write ANSWER.md</button>
          <span class="tiny">${esc(t.dir)}</span>
        </div>
        ${t.answer_error ? '<div class="err">'+esc(t.answer_error)+'</div>' : ''}
        ${t.answer ? '<div class="doc answer">'+md(t.answer)+'</div>' : ''}
      </div>`;
    }
    return `<div class="topic">
      <div class="thead" data-open="${esc(t.id)}">
        <span class="tneed">${esc(t.need)}</span>
        <span class="tmeta">${esc(t.status)} &middot; ${esc(t.lens)} &middot; ${done}/${
          t.steps.length} turns${
          t.answer && t.status !== 'answered' ? ' &middot; answered' : ''}</span>
      </div>${body}</div>`;
  }).join('');

  document.querySelectorAll('[data-open]').forEach(el => {
    el.onclick = () => { const id = el.dataset.open; OPEN[id] = !OPEN[id]; render(); };
  });
  document.querySelectorAll('[data-run]').forEach(el => {
    el.onclick = e => { e.stopPropagation();
      post('/api/topic/' + encodeURIComponent(el.dataset.run) + '/run',
           {step: +el.dataset.step}); };
  });
  document.querySelectorAll('[data-next]').forEach(el => {
    el.onclick = () => post('/api/topic/' + encodeURIComponent(el.dataset.next) + '/next', {});
  });
  document.querySelectorAll('[data-answer]').forEach(el => {
    el.onclick = () => post('/api/topic/' + encodeURIComponent(el.dataset.answer) + '/answer', {});
  });
  document.querySelectorAll('[data-doc]').forEach(el => {
    el.onclick = async e => {
      e.stopPropagation();
      const key = el.dataset.doc;
      if (DOCS[key]){ delete DOCS[key]; render(); return; }
      const r = await fetch('/api/turn?topic=' + encodeURIComponent(el.dataset.topic)
                            + '&file=' + encodeURIComponent(el.dataset.file));
      const d = await r.json();
      DOCS[key] = d.text || '(empty)';
      render();
    };
  });
}

/* One gauge per limit Claude reports. Percentages, not token counts: the
   percentage is the number the subscription is actually enforcing, and it is
   the one Claude hands us. */
function gauge(b, label, cls){
  return `<div class="${cls||''}${b.percent>=80?' warn':''}">
    <div class="cap">${esc(label)}</div>
    <div class="big">${b.percent.toFixed(0)}% used</div>
    <div class="meter">${meter(b.percent)}</div>
    ${b.resets ? '<div class="tiny" style="margin-top:6px">resets '+esc(b.resets)+'</div>' : ''}
  </div>`;
}

function renderBudget(d){
  const u = d.usage || {};
  const flag = document.getElementById('budgetflag');
  const box = document.getElementById('budget');
  if (!u.available){
    flag.textContent = '';
    box.innerHTML = '<div class="none">' + esc(u.reason || 'Asking Claude...') + '</div>';
    return;
  }
  const w = u.window, weeks = u.weeks || [];
  const worstWeek = weeks.reduce((a,k) => Math.max(a,k.percent), 0);
  flag.textContent = Math.max(w ? w.percent : 0, worstWeek) >= 80 ? 'running low' : '';

  box.innerHTML =
    (w ? gauge(w, '5h window')
       : '<div class="none">Claude reported no session window.</div>') +
    (weeks.length ? `<div class="row">
        <button class="ghost" id="weektoggle">${WEEKS ? '&#9662;' : '&#9656;'}
          Weekly limit &middot; ${worstWeek.toFixed(0)}%</button>
      </div>` + (WEEKS ? weeks.map(k => gauge(k, k.label, 'week')).join('') : '') : '') +
    `<div class="fine">Asked of Claude itself once a minute &mdash;
      last at ${clock(u.asked)}.</div>`;

  const toggle = document.getElementById('weektoggle');
  if (toggle) toggle.onclick = () => { WEEKS = !WEEKS; render(); };
}

function render(){
  const d = STATE;
  if (!d) return;
  document.getElementById('where').textContent = d.root;
  renderSeats(d); renderQueue(d); renderTopics(d); renderBudget(d);
  const lens = document.getElementById('lens');
  if (!lens.options.length){
    lens.innerHTML = d.lenses.map(l =>
      `<option value="${esc(l.key)}">${esc(l.label)}</option>`).join('');
  }
  document.getElementById('planhint').textContent =
    'default: ' + (d.relay.join(' → ') || 'no seats enabled');
  const blocked = Object.entries(d.seats).filter(([,s]) => s.problem).map(([n]) => n);
  document.getElementById('composerhint').innerHTML = blocked.length
    ? '<span style="color:var(--alert)">' + esc(blocked.join(', ')) +
      ' cannot run right now &mdash; see Seats.</span>'
    : '';
  document.getElementById('stamp').textContent = 'refreshed ' + new Date().toLocaleTimeString();
}

async function tick(){
  try { STATE = await (await fetch('/api/state')).json(); }
  catch { document.getElementById('stamp').textContent = 'connection lost'; return; }
  render();
}
tick(); setInterval(() => { if (!BUSY) tick(); }, 2500);
</script>
</body>
</html>
"""
