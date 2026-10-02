"""The app window: targets, captures, the live screen, and frames. Vanilla HTML/CSS/JS, no build step."""

from . import theme
from .views import FONT_CSS

CSS = """
body{height:100vh;overflow:hidden;display:flex;flex-direction:column}
header.bar img{width:26px;height:26px;filter:drop-shadow(0 0 8px color-mix(in srgb,var(--sun-mid) 60%,transparent))}
.pill{font:700 12px 'JetBrains Mono',monospace;letter-spacing:.12em;text-transform:uppercase;padding:4px 10px;border-radius:99px;
  border:1px solid var(--edge);color:var(--dim)}
.pill.live{color:#fff;border-color:transparent;background:linear-gradient(90deg,var(--sun-mid),var(--sun-low));
  box-shadow:0 0 18px color-mix(in srgb,var(--sun-mid) 55%,transparent);animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{box-shadow:0 0 4px color-mix(in srgb,var(--sun-mid) 30%,transparent)}}
#app{flex:1;display:grid;grid-template-columns:360px 1fr;min-height:0}
aside{border-right:1px solid color-mix(in srgb,var(--edge) 80%,transparent);padding:14px 14px 40px;overflow:auto;
  background:color-mix(in srgb,var(--bg) 55%,transparent);backdrop-filter:blur(8px)}
.sec{display:flex;align-items:center;justify-content:space-between;margin:10px 4px 8px}
h3{margin:0;font:800 12px Inter,sans-serif;letter-spacing:.24em;text-transform:uppercase;color:var(--dim)}
button.mini{padding:3px 8px;font-size:12px}
.host,.cap{border:1px solid var(--edge);border-radius:14px;padding:12px 13px;margin-bottom:9px;cursor:pointer;
  background:color-mix(in srgb,var(--panel) 82%,transparent);transition:border-color .15s,box-shadow .15s,transform .15s}
.host:hover,.cap:hover{transform:translateY(-1px)}
.host.sel,.cap.sel{border-color:var(--glow1);box-shadow:0 0 0 1px var(--glow1),0 0 26px color-mix(in srgb,var(--glow1) 25%,transparent)}
.hn{display:flex;align-items:center;gap:8px}.hn b{font-size:17px;letter-spacing:.02em}.hn kbd{margin:0}
.badge{margin-left:auto;font:800 10.5px 'JetBrains Mono',monospace;letter-spacing:.14em;padding:2px 8px;border-radius:99px}
.badge.ready{color:var(--mem);border:1px solid var(--mem);box-shadow:0 0 12px color-mix(in srgb,var(--mem) 35%,transparent)}
.badge.busy{color:var(--cpu);border:1px solid var(--cpu)}
.badge.down{color:var(--sync);border:1px solid var(--sync)}
.badge.live{color:#fff;background:linear-gradient(90deg,var(--sun-mid),var(--sun-low));box-shadow:0 0 14px color-mix(in srgb,var(--sun-mid) 60%,transparent)}
.hm{color:var(--text);opacity:.85;font-size:13px;margin-top:6px}
.hx{color:var(--dim);font:12px 'JetBrains Mono',monospace;margin-top:4px}
.hb{display:flex;gap:7px;margin-top:10px}.hb button{flex:1;font-size:13px;padding:6px 8px}
.why{color:var(--cpu);font-size:12px;margin-top:6px}
.cap .cn{font:700 12.5px 'JetBrains Mono',monospace;word-break:break-all}
.cap .cm{color:var(--dim);font-size:12px;margin-top:3px}
.tag{display:inline-block;font:700 10px 'JetBrains Mono',monospace;letter-spacing:.08em;padding:1px 6px;margin:5px 4px 0 0;
  border-radius:6px;border:1px solid var(--edge);color:var(--dim)}
#stage{overflow:auto;padding:22px 26px 60px;min-width:0}
.stagebar{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.stagebar .t{font:800 22px Inter,sans-serif;letter-spacing:.01em}
.screen{width:100%;aspect-ratio:16/9;border:0;border-radius:16px;display:block;background:var(--bg);
  box-shadow:0 0 0 1px var(--edge),0 30px 80px #000b,0 0 70px color-mix(in srgb,var(--sun-mid) 22%,transparent)}
.log{margin:14px 0 0;padding:12px 14px;border-radius:12px;background:color-mix(in srgb,var(--panel) 85%,transparent);
  border:1px solid var(--edge);font:12.5px/1.6 'JetBrains Mono',monospace;color:var(--dim);white-space:pre-wrap;max-height:180px;overflow:auto}
h2{margin:0 0 4px;font:800 28px Inter,sans-serif;letter-spacing:.01em;word-break:break-all}
.sub{color:var(--dim);margin-bottom:16px}
.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
label{color:var(--dim);font-size:13px;display:flex;gap:6px;align-items:center}
table{width:100%;border-collapse:collapse;font:13px 'JetBrains Mono',monospace;margin-bottom:22px;border-radius:12px;overflow:hidden;
  background:color-mix(in srgb,var(--panel) 82%,transparent)}
td,th{padding:7px 10px;border-bottom:1px solid var(--edge);text-align:right}td:first-child,th:first-child{text-align:left}
th{color:var(--dim);font-weight:600}td.hot{color:var(--sun-top);text-shadow:0 0 10px color-mix(in srgb,var(--sun-mid) 50%,transparent)}
.tw{overflow-x:auto;margin-bottom:22px}.tw table{margin:0;white-space:nowrap}
.results{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin:0 0 22px}
.res{background:color-mix(in srgb,var(--panel) 82%,transparent);border:1px solid var(--edge);border-radius:12px;padding:12px 16px}
.res b{display:block;font-size:28px;font-weight:800;color:var(--gpu);text-shadow:0 0 14px color-mix(in srgb,var(--gpu) 45%,transparent)}
.res span{color:var(--dim);font-size:12px}.res.warn b{color:var(--sun-top)}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}
.gallery a{display:block;border-radius:12px;overflow:hidden;box-shadow:0 0 0 1px var(--edge);transition:transform .15s,box-shadow .15s}
.gallery a:hover{transform:translateY(-2px);box-shadow:0 0 0 1px var(--glow1),0 0 30px color-mix(in srgb,var(--glow1) 30%,transparent)}
.gallery img{width:100%;display:block}
.welcome{height:100%;display:grid;place-items:center;text-align:center}
.sun{width:240px;height:240px;margin:0 auto 26px;border-radius:50%;
  background:linear-gradient(var(--sun-top),var(--sun-mid) 55%,var(--sun-low));
  -webkit-mask:linear-gradient(#000 52%,transparent 52% 56%,#000 56% 63%,transparent 63% 68%,#000 68% 75%,transparent 75% 82%,#000 82% 87%,transparent 87%);
  mask:linear-gradient(#000 52%,transparent 52% 56%,#000 56% 63%,transparent 63% 68%,#000 68% 75%,transparent 75% 82%,#000 82% 87%,transparent 87%);
  filter:drop-shadow(0 0 40px color-mix(in srgb,var(--sun-mid) 70%,transparent))}
.welcome .mark{font-size:44px}
.welcome p{color:var(--dim);font-size:17px;max-width:560px;margin:14px auto 0}
#splash{position:fixed;inset:0;z-index:50;display:grid;place-items:center;background:var(--bg);transition:opacity .5s}
#splash .sun{animation:rise 1.2s cubic-bezier(.2,.7,.2,1) both}
#splash .mark{font-size:52px;animation:fadein .9s .35s both}
@keyframes rise{from{transform:translateY(120px);opacity:0}to{transform:none;opacity:1}}
@keyframes fadein{from{opacity:0;letter-spacing:.9em}to{opacity:1}}
#splash.gone{opacity:0;pointer-events:none}
#help{position:fixed;inset:0;z-index:40;display:grid;place-items:center;background:color-mix(in srgb,var(--bg) 70%,transparent);backdrop-filter:blur(6px)}
#help[hidden]{display:none}
#help .card{min-width:460px;padding:24px 28px;border-radius:18px;background:var(--panel);border:1px solid var(--glow1);
  box-shadow:0 0 50px color-mix(in srgb,var(--glow1) 30%,transparent)}
#help dl{display:grid;grid-template-columns:auto 1fr;gap:9px 18px;margin:14px 0 0}#help dt{text-align:right}#help dd{margin:0;color:var(--dim)}
#toast{position:fixed;right:22px;bottom:22px;z-index:60;max-width:520px;padding:12px 16px;border-radius:12px;background:var(--panel);
  border:1px solid var(--sync);color:var(--text);box-shadow:0 0 30px color-mix(in srgb,var(--sync) 35%,transparent);display:none}
@media (prefers-reduced-motion:reduce){#splash{display:none}.pill.live{animation:none}}
"""

BODY = """
<header class="bar"><img src="/icon.svg" alt=""><span class="mark">Coreglass</span><span id="status" class="pill">idle</span>
<span class="sp"></span><button id="themeBtn" onclick="toggleTheme()">theme<kbd>t</kbd></button>
<button onclick="toggleHelp()">Keys<kbd>?</kbd></button></header>
<div id="app"><aside>
<div class="sec"><h3>Targets</h3><button class="mini" onclick="loadHosts()">refresh<kbd>h</kbd></button></div><div id="hosts"><div class="hx">checking targets…</div></div>
<div class="sec"><h3>Captures</h3><span class="hint">↑ ↓</span></div><div id="caps"></div>
</aside><section id="stage"></section></div>
<div id="splash"><div><div class="sun"></div><div class="mark">Coreglass</div></div></div>
<div id="help" hidden onclick="toggleHelp()"><div class="card"><span class="mark">Keys</span><dl>
<dt><kbd>1</kbd>–<kbd>9</kbd></dt><dd>pick a target</dd><dt><kbd>l</kbd></dt><dd>watch the target live</dd>
<dt><kbd>r</kbd></dt><dd>run the probe: P cores, E cores, GPU matmul, LLM, ANE</dd><dt><kbd>esc</kbd></dt><dd>stop</dd>
<dt><kbd>m</kbd></dt><dd>drop a mark on the timeline</dd><dt><kbd>f</kbd></dt><dd>full-screen the live screen</dd>
<dt><kbd>↑</kbd> <kbd>↓</kbd></dt><dd>pick a capture</dd><dt><kbd>enter</kbd></dt><dd>replay it</dd>
<dt><kbd>b</kbd></dt><dd>build shareable frames</dd><dt><kbd>t</kbd></dt><dd>synthwave ⇄ your Omarchy theme</dd>
<dt><kbd>h</kbd></dt><dd>re-check targets</dd><dt><kbd>?</kbd></dt><dd>this card</dd></dl></div></div>
<div id="toast"></div>
"""

JS = r"""
const $=s=>document.querySelector(s), api=(p,o)=>fetch(p,o).then(r=>r.json());
let hosts=[], caps=[], hi=0, ci=-1, st={mode:'idle'}, screenKey='', built={};
function badge(h){if(st.mode!=='idle'&&st.target===h.name)return['live',st.mode==='live'?'LIVE':'RUNNING'];
  if(!h.preflight.reachable)return['down','OFFLINE'];return h.blockers.length?['busy','BUSY']:['ready','READY']}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(msg){const t=$('#toast');t.textContent=msg;t.style.display='block';clearTimeout(t._h);t._h=setTimeout(()=>t.style.display='none',6000)}
async function post(p){const r=await fetch(p,{method:'POST'});const j=await r.json().catch(()=>({}));if(j.error)toast(j.error);return j}
async function loadHosts(){const d=await api('/api/hosts');hosts=d.hosts;
  if(!hosts.length)$('#hosts').innerHTML=`<div class="hx">No targets yet. Copy hosts.example.toml to<br>${esc(d.file)}</div>`;renderHosts()}
function renderHosts(){$('#hosts').innerHTML=hosts.map((h,i)=>{const p=h.preflight,[cls,txt]=badge(h);
  const busy=h.blockers.length>0;return `<div class="host ${i===hi?'sel':''}" onclick="hi=${i};renderHosts()">
  <div class="hn"><kbd>${i+1}</kbd><b>${esc(h.name)}</b><span class="badge ${cls}">${txt}</span></div>
  <div class="hm">${esc(p.reachable?p.model.replace(/^Apple /,''):h.ssh)}</div>
  ${p.reachable?`<div class="hx">${esc(p.arch)} · load ${p.load1.toFixed(2)} · GPU ${p.stats.includes('agx_stats')?'stats':'irq'} · MLX ${p.mlx_python?'✓':'–'}</div>
  <div class="hx">ANE ${p.stats.includes('ane_stats')?'stats ✓':(p.accel||[]).some(d=>d.startsWith('ane'))?'driver, no stats':'–'} · ANE probe ${h.ane?'✓':'–'}</div>`:''}
  ${busy?`<div class="why">${esc(h.blockers[0])}</div>`:''}
  <div class="hb"><button onclick="event.stopPropagation();hi=${i};live()" ${p.reachable?'':'disabled'}>Live<kbd>l</kbd></button>
  <button class="primary" onclick="event.stopPropagation();hi=${i};run()" ${busy||!p.reachable?'disabled':''}>Run probe<kbd>r</kbd></button></div></div>`}).join('')}
async function loadCaps(){caps=await api('/api/captures');renderCaps()}
function renderCaps(){$('#caps').innerHTML=caps.length?caps.map((c,i)=>`<div class="cap ${i===ci?'sel':''}" onclick="pickCap(${i})">
  <div class="cn">${esc(c.name.replace(/\.jsonl$/,''))}</div><div class="cm">${esc(c.when)} · ${esc(c.host)}${c.seconds?` · ${c.seconds}s`:''}</div>
  <div>${c.kind==='run'?c.steps.map(s=>`<span class="tag">${esc(s)}</span>`).join(''):'<span class="tag">LIVE</span>'}${c.built?'<span class="tag">FRAMES</span>':''}</div></div>`).join('')
  :'<div class="hx">Captures land here. Press <kbd>r</kbd> to make one.</div>'}
function pickCap(i){ci=Math.max(0,Math.min(caps.length-1,i));renderCaps();if(st.mode==='idle')showCap()}
function live(){const h=hosts[hi];if(h)post('/api/live?host='+encodeURIComponent(h.name)).then(poll)}
function run(){const h=hosts[hi];if(!h)return;if(h.blockers.length)return toast(`${h.name}: ${h.blockers.join('; ')}`);post('/api/run?host='+encodeURIComponent(h.name)).then(poll)}
function stop(){post('/api/stop').then(()=>{poll();loadCaps()})}
function replay(){const c=caps[ci];if(c)post('/api/replay?name='+encodeURIComponent(c.name)).then(poll)}
let markN=0;
function mark(){if(st.mode==='idle')return;const l='mark '+(++markN);fetch('/mark?label='+encodeURIComponent(l),{method:'POST'});toast(l)}
async function buildFrames(){const c=caps[ci];if(!c)return;const ref=$('#ref')?.checked!==false?1:0,anon=$('#anon')?.checked?1:0;
  $('#gallery').innerHTML='<div class="hx">rendering frames…</div>';
  const r=await post(`/api/build?name=${encodeURIComponent(c.name)}&reference=${ref}&anonymize=${anon}`);if(r.error)return;
  built[c.name]=r;c.built=true;renderCaps();showCap()}
async function showCap(){const c=caps[ci],s=$('#stage');screenKey='';if(!c)return welcome();
  const ph=await api('/api/phases?name='+encodeURIComponent(c.name)).catch(()=>null);
  const keys=ph?Object.keys(ph.phases[0]).filter(k=>!['phase','n'].includes(k)&&ph.phases.some(p=>p[k]!==null)):[];
  const stem=c.name.replace(/\.jsonl$/,''),r=built[c.name]||(c.built?{frames:['hero','time','bandwidth','util','flow','gaps','capture']}:null);
  s.innerHTML=`<h2>${esc(stem)}</h2><div class="sub">${esc(c.model||c.host)} · ${c.seconds||'?'} s · ${c.kind}</div>
  <div class="actions"><button class="primary" onclick="replay()">Replay<kbd>enter</kbd></button><button onclick="buildFrames()">Build frames<kbd>b</kbd></button>
  <label><input type="checkbox" id="ref" checked>add reference measurements</label><label><input type="checkbox" id="anon">anonymize for posting</label>
  ${r?`<button onclick="window.open('/out/${encodeURIComponent(stem)}/index.html')">Open report</button>`:''}</div>
  ${ph?`<div class="tw"><table><tr><th>phase</th><th>n</th>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr>${ph.phases.map(p=>`<tr><td>${esc(p.phase)}</td><td>${p.n}</td>${keys.map(k=>{const v=p[k];
    const hot=(k.endsWith('busy')&&v>=0.9)||(k==='gpu_fw_irq_s'&&v>=3*(ph.phases[0][k]||1));return `<td class="${hot?'hot':''}">${v===null?'–':v}</td>`}).join('')}</tr>`).join('')}</table></div>`:''}
  ${ph?ph.results.map(resultCards).join(''):''}
  <div class="gallery" id="gallery">${r?r.frames.map(f=>`<a href="/out/${encodeURIComponent(stem)}/index.html#${f}" target="_blank"><img loading="lazy" src="/out/${encodeURIComponent(stem)}/frames/${f}.svg?${Date.now()}"></a>`).join(''):'<div class="hx">Press <kbd>b</kbd> to render shareable 1600×900 frames.</div>'}</div>`}
const RESULT_CARDS=[['decode_tok_s','decode tok/s'],['ttft_ms','time to first token, ms'],['prefill_tok_s','prefill tok/s'],
  ['j_per_token','J per token'],['host_cpu_ms_per_token','host CPU ms per token'],['weights_gb_s_modeled','weight reads GB/s (modeled)'],
  ['token_gap_ms_p50_p99','token gap ms p50 / p99'],['peak_mem_gb','peak MLX memory GB'],['load_s','model load s'],['kernel_warnings','kernel warnings']];
function resultCards(r){return `<div class="hx">${esc(r.label)} · ${esc(r.model)} · ${r.prompt_tokens} prompt + ${r.gen_tokens} generated tokens</div>
  <div class="results">${RESULT_CARDS.filter(([k])=>r[k]!==null&&r[k]!==undefined).map(([k,l])=>`<div class="res ${k==='kernel_warnings'&&r[k]?'warn':''}">
  <b>${esc(Array.isArray(r[k])?r[k].join(' / '):r[k])}</b><span>${esc(l)}</span></div>`).join('')}</div>`}
function welcome(){screenKey='';$('#stage').innerHTML=`<div class="welcome"><div><div class="sun"></div><div class="mark">Coreglass</div>
  <p>See where local inference loses speed on Apple Silicon under Linux.<br>Pick a target with <kbd>1</kbd>–<kbd>9</kbd>, then <kbd>l</kbd> to watch it live or <kbd>r</kbd> to run the probe.</p></div></div>`}
function stage(){const s=$('#stage'),key=st.mode+'|'+st.target;
  if(st.mode==='idle'){if(screenKey.includes('|')){screenKey='';loadCaps().then(()=>{ci=caps.findIndex(c=>c.name===st.capture);if(ci<0)ci=0;renderCaps();showCap()})}
    else if(!s.innerHTML)welcome();return}
  if(key!==screenKey){screenKey=key;s.innerHTML=`<div class="stagebar"><span class="t">${esc({live:'Live',run:'Probe',replay:'Replay'}[st.mode])} · ${esc(st.target)}</span>
    <span class="sp"></span><button onclick="mark()">Mark<kbd>m</kbd></button><button onclick="$('.screen').requestFullscreen()">Full screen<kbd>f</kbd></button>
    <button class="primary" onclick="stop()">Stop<kbd>esc</kbd></button></div><iframe class="screen" src="/live?embed=1&k=${Date.now()}"></iframe><pre class="log"></pre>`}
  const lg=s.querySelector('.log');if(lg)lg.textContent=(st.log||[]).join('\n')}
let lastPal='';
async function poll(){st=await api('/api/state');const pill=$('#status');
  pill.className='pill'+(st.mode==='idle'?'':' live');pill.textContent=st.mode==='idle'?'idle':`${st.mode} · ${st.target}`;
  $('#themeBtn').firstChild.textContent=st.theme==='omarchy'?(st.omarchy?st.palette.replace('omarchy:','')+' ':'omarchy (none) '):'synthwave ';
  if(lastPal&&st.palette!==lastPal)return location.reload();lastPal=st.palette;
  const mk=st.mode+'|'+st.target;if(mk!==poll._mk){poll._mk=mk;renderHosts()}
  if(st.error&&st.error!==poll._err){poll._err=st.error;toast(st.error)}stage()}
function toggleTheme(){post('/api/theme?name='+(st.theme==='omarchy'?'synthwave':'omarchy')).then(()=>location.reload())}
function toggleHelp(){$('#help').hidden=!$('#help').hidden}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.ctrlKey||e.metaKey||e.altKey)return;const k=e.key;
  if($('#splash')&&!$('#splash').classList.contains('gone'))return $('#splash').classList.add('gone');
  if(k==='?')return toggleHelp();if(k==='Escape'){if(!$('#help').hidden)return toggleHelp();return st.mode!=='idle'&&stop()}
  if(/^[1-9]$/.test(k)&&hosts[+k-1]){hi=+k-1;renderHosts()}
  else if(k==='l')live();else if(k==='r')run();else if(k==='m')mark();else if(k==='t')toggleTheme();else if(k==='h')loadHosts();
  else if(k==='f')$('.screen')?.requestFullscreen();else if(k==='b')buildFrames();else if(k==='Enter')replay();
  else if(k==='ArrowDown'){e.preventDefault();pickCap(ci+1)}else if(k==='ArrowUp'){e.preventDefault();pickCap(ci-1)}});
if(sessionStorage.cgSplash||matchMedia('(prefers-reduced-motion: reduce)').matches)$('#splash').classList.add('gone');
else{sessionStorage.cgSplash=1;setTimeout(()=>$('#splash').classList.add('gone'),1700)}
welcome();loadHosts();loadCaps();poll();setInterval(poll,1000);
"""


def render(palette):
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Coreglass</title>"
            f"<link rel=\"icon\" href=\"/icon.svg\"><style>{FONT_CSS}{theme.chrome_css(palette)}{CSS}</style></head>"
            f"<body>{BODY}<script>{JS}</script></body></html>")
