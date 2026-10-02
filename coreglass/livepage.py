"""Live dashboard: one 1600x900 canvas, redrawn on every sample, so any moment is a shareable frame."""

import json

from .views import CMAP, FONT_CSS, esc

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coreglass live · __TITLE__</title>
<style>__FONTS__
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#020306;color:#eef2f8;font:15px/1.5 Inter,'Helvetica Neue','Liberation Sans',Arial,sans-serif}
header{display:flex;gap:10px;align-items:center;padding:12px 24px;border-bottom:1px solid #1c2433;background:#05070b}
.mark{font-weight:800;letter-spacing:6px;margin-right:18px}.mark b{color:#2de2ff}
button{background:#0c1017;color:#eef2f8;border:1px solid #1c2433;border-radius:8px;padding:7px 13px;font:inherit;cursor:pointer}
button:hover{border-color:#2de2ff}.sp{flex:1}.hint{color:#8590a3;font-size:13px}
main{display:grid;place-items:center;padding:18px}
canvas{width:min(100%,calc((100vh - 100px)*16/9));aspect-ratio:16/9;border-radius:14px;box-shadow:0 30px 80px #000c}
</style></head><body>
<header><span class="mark">CORE<b>GLASS</b></span><span class="hint">live · __TITLE__</span><span class="sp"></span>
<span class="hint">m mark · p png · space pause</span>
<button onclick="mark()">Mark</button><button onclick="snap()">PNG 2×</button><button id="pz" onclick="pause()">Pause</button></header>
<main><canvas id="c" width="3200" height="1800"></canvas></main>
<script>
const CMAP=__CMAP__, W=1600, H=900, WINDOW=60;
const C={bg:'#05070b',panel:'#0c1017',edge:'#1c2433',text:'#eef2f8',dim:'#8590a3',
  gpu:'#2de2ff',ane:'#ff4fd8',cpu:'#ffb02e',e:'#ffd27a',mem:'#59f0a8',sync:'#ff5b6e',queue:'#9b87ff'};
const SANS="Inter,'SF Pro Display','Helvetica Neue','Liberation Sans',Arial,sans-serif";
const MONO="'JetBrains Mono','SF Mono','DejaVu Sans Mono',monospace";
const cv=document.getElementById('c'), g=cv.getContext('2d'); g.scale(2,2);
for(const f of ["800 52px Inter","400 16px Inter","700 16px 'JetBrains Mono'"])document.fonts.load(f);
let meta=null, S=[], marks=[], paused=false, irqMax={};
const lut=[...Array(256)].map((_,i)=>{const v=i/255;for(let k=1;k<CMAP.length;k++){const [a,ca]=CMAP[k-1],[b,cb]=CMAP[k];
  if(v<=b){const f=(v-a)/(b-a);return `rgb(${ca.map((p,j)=>Math.round(p+(cb[j]-p)*f)).join(',')})`}}return 'rgb(252,255,164)'});
const col=v=>lut[Math.max(0,Math.min(255,Math.round(v*255)))];
function font(w,s,m){g.font=`${w} ${s}px ${m?MONO:SANS}`}
function txt(s,x,y,s2,c,w=400,a='left',m=false){font(w,s2,m);g.fillStyle=c;g.textAlign=a;g.fillText(s,x,y)}
function rr(x,y,w,h,r,fill,stroke){g.beginPath();g.roundRect(x,y,w,h,r);if(fill){g.fillStyle=fill;g.fill()}if(stroke){g.strokeStyle=stroke;g.lineWidth=1;g.stroke()}}
const bgc=document.createElement('canvas');bgc.width=W;bgc.height=H;
(()=>{const b=bgc.getContext('2d');b.fillStyle=C.bg;b.fillRect(0,0,W,H);
  let r=b.createRadialGradient(190,0,0,190,0,1100);r.addColorStop(0,'rgba(31,184,255,.20)');r.addColorStop(1,'rgba(31,184,255,0)');b.fillStyle=r;b.fillRect(0,0,W,H);
  r=b.createRadialGradient(1520,900,0,1520,900,1100);r.addColorStop(0,'rgba(255,63,208,.16)');r.addColorStop(1,'rgba(255,63,208,0)');b.fillStyle=r;b.fillRect(0,0,W,H);
  b.strokeStyle='rgba(255,255,255,.035)';for(let x=0;x<W;x+=40){b.beginPath();b.moveTo(x+.5,0);b.lineTo(x+.5,H);b.stroke()}
  for(let y=0;y<H;y+=40){b.beginPath();b.moveTo(0,y+.5);b.lineTo(W,y+.5);b.stroke()}})();
function rows(){if(!meta)return[];const out=[];
  const cl=[...meta.clusters].sort((a,b)=>b.max_khz-a.max_khz);
  for(const c of cl)for(const cpu of c.cpus)out.push({label:`${c.label}·${cpu}`,group:c.label,color:c.label==='E'?C.e:C.cpu,get:s=>s.cpu[cpu]??0});
  const eng=meta.engines||[];
  for(const e of eng)out.push({label:`${e.toUpperCase()} busy`,group:`eng-${e}`,color:e==='gpu'?C.gpu:C.ane,get:s=>s.eng?.[e]?.busy??0});
  for(const n of meta.irq){if(n==='gpu_fw'&&eng.includes('gpu'))continue;
    out.push({label:n==='gpu_fw'?'GPU fw':n.replace(/\.?[0-9a-f]{6,}\.?/,'').slice(0,8)||'ANE',group:n,
    color:n==='gpu_fw'?C.gpu:C.ane,get:s=>(s.sirq[n]??0)/Math.max(irqMax[n]||0,30)})}
  return out}
function pickRail(pref){if(!meta||!meta.rails.length)return null;for(const p of pref){const r=meta.rails.find(x=>x.toLowerCase().includes(p));if(r)return r}return null}
function avg(a){return a.length?a.reduce((x,y)=>x+y,0)/a.length:0}
function clusterBusy(s,label){const cs=meta.clusters.filter(c=>label==='E'?c.label==='E':c.label!=='E').flatMap(c=>c.cpus);return avg(cs.map(i=>s.cpu[i]??0))}
function spark(x,y,w,h,vals,color,max){if(vals.length<2)return;const m=max||Math.max(...vals,1e-9);g.beginPath();
  vals.forEach((v,i)=>{const px=x+i/(vals.length-1)*w,py=y+h-Math.min(v/m,1)*h;i?g.lineTo(px,py):g.moveTo(px,py)});
  g.strokeStyle=color;g.lineWidth=2;g.stroke();g.lineTo(x+w,y+h);g.lineTo(x,y+h);g.closePath();g.globalAlpha=.12;g.fillStyle=color;g.fill();g.globalAlpha=1}
function chip(x,y,label,color){font(700,13);const w=g.measureText(label).width+40;rr(x,y,w,26,6,color+'1f',color);txt(label,x+w/2,y+18,13,color,700,'center');return w}
function draw(){
  g.drawImage(bgc,0,0);
  g.letterSpacing='8px';txt('CORE',60,62,20,C.text,800);const cw0=g.measureText('CORE').width;txt('GLASS',60+cw0,62,20,C.gpu,800);g.letterSpacing='0px';
  const live=!paused&&S.length&&(Date.now()-lastRecv<2000);
  g.globalAlpha=live?.55+.45*Math.sin(Date.now()/250):1;g.fillStyle=live?C.sync:C.dim;g.beginPath();g.arc(270,55,7,0,7);g.fill();g.globalAlpha=1;
  txt(paused?'PAUSED':meta&&meta.replay?'REPLAY':live?'LIVE':'WAITING',284,62,16,live?C.sync:C.dim,800);
  if(meta)txt([meta.host,meta.model,meta.kernel].filter(Boolean).join(' · '),W-60,62,17,C.dim,500,'right',true);
  const last=S[S.length-1];
  txt(meta?`${meta.replay?'Replay':'Live'} · ${meta.host}`:'Waiting for sampler…',60,124,52,C.text,800);
  if(meta)txt(`Per-core CPU, GPU firmware events, power · ${meta.hz} Hz · ${last?last.t.toFixed(1):'0.0'} s · ${S.length} samples in view`,60,162,22,C.dim);
  if(!meta){requestAnimationFrame(draw);return}
  const recent=S.slice(-Math.max(1,Math.round(meta.hz)));
  const sys=pickRail(['total system','system']), soc=pickRail(['heatpipe','package','soc','cpu']);
  const hasE=meta.clusters.some(c=>c.label==='E'), hasP=meta.clusters.some(c=>c.label!=='E');
  const tiles=[
    ['P cores busy',v=>(100*v).toFixed(0)+'%',s=>clusterBusy(s,'P'),C.cpu,1,hasP],
    ['E cores busy',v=>(100*v).toFixed(0)+'%',s=>clusterBusy(s,'E'),C.e,1,hasE],
    ...((meta.engines||[]).includes('gpu')
      ?[['GPU busy (driver)',v=>(100*v).toFixed(0)+'%',s=>s.eng?.gpu?.busy??0,C.gpu,1,true]]
      :[['GPU firmware events',v=>v.toFixed(0)+'/s',s=>s.irq.gpu_fw||0,C.gpu,0,meta.irq.includes('gpu_fw')]]),
    [soc||'SoC power rail',v=>v.toFixed(1)+' W',s=>soc?s.w[soc]||0:0,C.mem,0,!!soc],
    [sys||'System power rail',v=>v.toFixed(1)+' W',s=>sys?s.w[sys]||0:0,C.mem,0,!!sys],
    ['Hottest sensor',v=>v.toFixed(1)+'°C',s=>Math.max(...Object.values(s.c),0),C.sync,0,meta.temps.length>0]];
  tiles.forEach(([label,fmt,get,c,unit,ok],i)=>{const x=60+i*250,y=188,w=232,h=142;rr(x,y,w,h,14,C.panel,C.edge);g.fillStyle=ok?c:C.edge;g.fillRect(x+14,y,w-28,3);
    txt(label.length>24?label.slice(0,23)+'…':label,x+18,y+30,15,C.dim,600);
    if(!ok){txt('n/a',x+18,y+84,46,C.edge,800);txt('no source on this host',x+18,y+118,13,C.dim);return}
    const v=avg(recent.map(get));g.shadowColor=c;g.shadowBlur=18;txt(last?fmt(v):'–',x+18,y+84,46,c,800);g.shadowBlur=0;
    spark(x+18,y+96,w-36,34,S.map(get),c,unit?1:0)});
  const R=rows(), hx=170, hy=372, hw=1370, hh=268, top=hy+40;
  rr(60,350,1480,350,16,C.panel,C.edge);
  txt('Per-core occupancy · last 60 s (measured)',84,380,18,C.dim,600);
  const n=Math.round(WINDOW*meta.hz), cw=hw/n, rh=Math.min(28,hh/Math.max(R.length,1));
  const view=S.slice(-n), x0=hx+hw-view.length*cw;
  for(const k of meta.irq){const v=view.map(s=>s.sirq[k]||0).sort((a,b)=>a-b);irqMax[k]=v.length?v[Math.floor(.95*(v.length-1))]:0}
  let lastLab=-99;
  R.forEach((r,i)=>{const y=top+i*rh;
    if((i===0||R[i-1].group!==r.group)&&y-lastLab>=15){lastLab=y;txt(r.group==='gpu_fw'?'GPU':r.label.split('·')[0],hx-16,y+Math.max(rh*.75,11),15,r.color,800,'right')}
    view.forEach((s,j)=>{g.fillStyle=col(r.get(s));g.fillRect(x0+j*cw,y,cw+.6,rh-1.5)})});
  const t1=last?last.t:0;
  for(let k=0;k<=WINDOW;k+=10){const x=hx+hw-k/WINDOW*hw;g.fillStyle='rgba(255,255,255,.12)';g.fillRect(x,top-6,1,R.length*rh+10);
    txt(k?`-${k}s`:'now',x,top+R.length*rh+20,13,C.dim,500,'center',true)}
  for(const m of marks){if(m.t<t1-WINDOW)continue;const x=hx+hw-(t1-m.t)/WINDOW*hw;g.fillStyle=C.text;g.fillRect(x-1,hy+14,2,top-hy-14+R.length*rh);
    rr(x+4,hy+10,Math.min(220,9*m.mark.length+18),22,5,'rgba(5,7,11,.9)',C.text);txt(m.mark,x+12,hy+26,13,C.text,700,'left',true)}
  for(let i=0;i<40;i++){g.fillStyle=col(i/39);g.fillRect(560+i*4.5,370,4.8,10)}
  txt('0',552,380,12,C.dim,500,'right',true);txt('1',748,380,12,C.dim,500,'left',true);txt('busy · relative rate (1 s avg)',766,380,12,C.dim,500);
  rr(60,712,730,128,16,C.panel,C.edge);rr(810,712,730,128,16,C.panel,C.edge);
  txt('Power rails (W)',84,740,16,C.dim,600);txt('Cluster clocks (GHz)',834,740,16,C.dim,600);
  const pal=[C.mem,C.gpu,C.cpu,C.ane,C.queue];
  const railsShown=meta.rails.filter(r=>view.some(s=>(s.w[r]||0)>0)).slice(0,4), wmax=Math.max(1,...view.flatMap(s=>railsShown.map(r=>s.w[r]||0)));
  railsShown.forEach((r,i)=>{spark(84,752,540,74,view.map(s=>s.w[r]||0),pal[i],wmax);
    txt(`${r.replace(/ Power$/,'').slice(0,14)} ${last?(last.w[r]||0).toFixed(1):''}`,770,770+i*18,12,pal[i],700,'right',true)});
  const cls=[...meta.clusters].sort((a,b)=>b.max_khz-a.max_khz).slice(0,4), fmax=Math.max(...meta.clusters.map(c=>c.max_khz))/1e6;
  cls.forEach((c,i)=>{spark(834,752,560,74,view.map(s=>(s.khz[c.label]||0)/1e6),c.label==='E'?C.e:pal[i+1],fmax);
    txt(`${c.label} ${last?((last.khz[c.label]||0)/1e6).toFixed(2):''}`,1520,770+i*18,12,c.label==='E'?C.e:pal[i+1],700,'right',true)});
  g.fillStyle=C.edge;g.fillRect(60,848,1480,1);
  chip(60,858,'MEASURED','#3ddc97');
  txt('read-only procfs/sysfs sampler · GPU row = firmware mailbox IRQ rate (activity proxy, not busy time)',214,876,13,C.dim);
  txt(`coreglass live · ${new Date().toISOString().slice(0,19)}Z`,W-60,876,13,C.dim,400,'right',true);
  requestAnimationFrame(draw)}
let lastRecv=0;
const es=new EventSource('/events');
es.onmessage=e=>{if(paused)return;const m=JSON.parse(e.data);lastRecv=Date.now();
  if(m.meta){meta=m.meta;S=[];marks=[]}else if(m.mark!==undefined)marks.push(m);else{
    const k=Math.max(1,Math.round(meta.hz)), tail=S.slice(-(k-1));m.sirq={};
    for(const n in m.irq)m.sirq[n]=avg([...tail.map(s=>s.irq[n]||0),m.irq[n]]);
    S.push(m);if(S.length>WINDOW*meta.hz*2)S.splice(0,S.length-WINDOW*meta.hz)}};
function mark(){const l=prompt('Mark label','event');if(l)fetch('/mark?label='+encodeURIComponent(l),{method:'POST'})}
function snap(){cv.toBlob(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download=`coreglass-live-${meta?meta.host:'host'}-${Date.now()}.png`;a.click()})}
function pause(){paused=!paused;document.getElementById('pz').textContent=paused?'Resume':'Pause'}
document.addEventListener('keydown',e=>{if(e.key==='m')mark();if(e.key==='p')snap();if(e.key===' '){e.preventDefault();pause()}});
requestAnimationFrame(draw);
</script></body></html>"""


def render(title):
    return (PAGE.replace("__TITLE__", esc(title)).replace("__FONTS__", FONT_CSS)
            .replace("__CMAP__", json.dumps([[a, list(c)] for a, c in CMAP])))
