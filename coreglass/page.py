"""Single self-contained HTML studio: frames, export buttons, ranked table, embedded summary JSON."""

import json

from .views import FONT_CSS, esc

CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#020306;color:#eef2f8;font:15px/1.5 Inter,'Helvetica Neue','Liberation Sans',Arial,sans-serif}
header{position:sticky;top:0;z-index:2;display:flex;gap:10px;align-items:center;padding:12px 24px;
  background:#05070bcc;backdrop-filter:blur(10px);border-bottom:1px solid #1c2433}
.mark{font-weight:800;letter-spacing:6px;margin-right:18px}.mark b{color:#2de2ff}
button{background:#0c1017;color:#eef2f8;border:1px solid #1c2433;border-radius:8px;padding:7px 13px;font:inherit;cursor:pointer}
button:hover{border-color:#2de2ff}button.on{background:#2de2ff;color:#05070b;border-color:#2de2ff;font-weight:700}
.sp{flex:1}.hint{color:#8590a3;font-size:13px}
main{padding:22px 24px;display:grid;justify-items:center}
.frame{display:none;width:min(100%,calc((100vh - 90px)*16/9));height:auto;border-radius:14px;box-shadow:0 30px 80px #000c}
.frame.on{display:block}
body.wall .frame{display:block;margin-bottom:22px}
.flow[stroke-dasharray]{animation:dash 1.4s linear infinite}
@keyframes dash{to{stroke-dashoffset:-36}}
section{max-width:1600px;width:100%;margin-top:28px}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 10px;border-bottom:1px solid #1c2433;text-align:left;vertical-align:top}
th{color:#8590a3;font-weight:600}td.f{font:700 15px 'JetBrains Mono','DejaVu Sans Mono',monospace;color:#2de2ff}
"""

JS = """
const frames=[...document.querySelectorAll('svg.frame')];let cur=0;
const tabs=[...document.querySelectorAll('button[data-i]')];
function show(i){cur=(i+frames.length)%frames.length;frames.forEach((f,j)=>f.classList.toggle('on',j===cur));
  tabs.forEach((t,j)=>t.classList.toggle('on',j===cur));history.replaceState(null,'','#'+frames[cur].id);
  if(!document.body.classList.contains('wall'))scrollTo(0,0)}
function save(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),5000)}
function svgText(f){return new XMLSerializer().serializeToString(f)}
function exportSvg(){const f=frames[cur];save(new Blob([svgText(f)],{type:'image/svg+xml'}),`coreglass-${f.id}.svg`)}
function exportPng(scale=2){const f=frames[cur],img=new Image();
  img.onload=()=>{const c=document.createElement('canvas');c.width=1600*scale;c.height=900*scale;
    c.getContext('2d').drawImage(img,0,0,c.width,c.height);c.toBlob(b=>save(b,`coreglass-${f.id}@${scale}x.png`))};
  img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svgText(f))}
function copySummary(){navigator.clipboard.writeText(document.getElementById('coreglass-summary-md').textContent)}
tabs.forEach(t=>t.onclick=()=>show(+t.dataset.i));
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')show(cur+1);if(e.key==='ArrowLeft')show(cur-1);
  if(e.key==='p')exportPng();if(e.key==='s')exportSvg();if(e.key==='w')document.body.classList.toggle('wall')});
const start=frames.findIndex(f=>'#'+f.id===location.hash);show(start<0?0:start);
"""


def render(frames, summary, md):
    tabs = "".join(f'<button data-i="{i}">{esc(name)}</button>' for i, (name, _) in enumerate(frames))
    rows = "".join(
        f"<tr><td class=f>{f['factor']:.2f}×</td><td>{esc(f['kind'])}</td><td>{esc(f['component'])}</td>"
        f"<td>{esc(f['what'])}</td><td>{esc(f['prov'])}</td><td>{esc(f['src'])}</td></tr>"
        for f in summary["findings"])
    blob = json.dumps(summary, indent=1).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coreglass · {esc(summary['title'])}</title>
<meta name="description" content="Coreglass inference studio. Machine-readable summary: script#coreglass-summary (JSON) and pre#coreglass-summary-md.">
<style>{FONT_CSS}{CSS}</style></head>
<body>
<header><span class="mark">CORE<b>GLASS</b></span>{tabs}<span class="sp"></span>
<span class="hint">← → views · p png · s svg · w wall</span>
<button onclick="exportPng()">PNG 2×</button><button onclick="exportSvg()">SVG</button>
<button onclick="copySummary()">Copy LLM summary</button></header>
<main>{"".join(svg for _, svg in frames)}
<section><h2>Levers, largest factor first</h2>
<table><tr><th>factor</th><th>kind</th><th>component</th><th>finding</th><th>prov</th><th>source</th></tr>{rows}</table>
<pre id="coreglass-summary-md" hidden>{esc(md)}</pre></section></main>
<script type="application/json" id="coreglass-summary">{blob}</script>
<script>{JS}</script>
</body></html>"""
