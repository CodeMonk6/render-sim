"""Render FastAPI application — main entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import render
from render.app.routers import ask as ask_router
from render.app.routers import coverage as coverage_router
from render.app.routers import eval as eval_router

app = FastAPI(
    title="Render",
    description="Natural-language → simulation → interpretation co-pilot for researchers.",
    version=render.__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(ask_router.router)
app.include_router(eval_router.router)
app.include_router(coverage_router.router)

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _HTML


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": render.__version__}


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Render — Simulation Co-pilot</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,sans-serif;background:#f8f9fa;color:#212529;min-height:100vh}
  header{background:#1a1a2e;color:#fff;padding:1rem 2rem;display:flex;align-items:center;gap:1rem}
  header h1{font-size:1.5rem;font-weight:700;letter-spacing:-0.5px}
  header span.badge{font-size:0.75rem;background:#e63946;color:#fff;padding:0.2rem 0.5rem;border-radius:4px}
  main{max-width:860px;margin:2rem auto;padding:0 1rem}
  .card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:1.5rem;margin-bottom:1.5rem}
  .card h2{font-size:1.1rem;margin-bottom:1rem;color:#1a1a2e}
  textarea{width:100%;height:80px;resize:vertical;border:1px solid #ced4da;border-radius:4px;padding:.5rem;font-size:.95rem;font-family:inherit}
  textarea:focus{outline:none;border-color:#4361ee}
  .row{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.75rem;align-items:center}
  input[type=text]{flex:1;min-width:140px;border:1px solid #ced4da;border-radius:4px;padding:.45rem .6rem;font-size:.9rem}
  .btn{padding:.45rem 1rem;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;font-weight:600;transition:background .15s}
  .btn-primary{background:#4361ee;color:#fff}.btn-primary:hover{background:#3a51d4}
  .btn-secondary{background:#6c757d;color:#fff}.btn-secondary:hover{background:#5a6268}
  #status{margin-top:.75rem;font-size:.9rem;color:#6c757d}
  #results{white-space:pre-wrap;font-family:monospace;font-size:.85rem;background:#f1f3f5;
           border-radius:4px;padding:1rem;max-height:500px;overflow-y:auto}
  .badge-cert{color:#2d6a4f;background:#d8f3dc;padding:.15rem .4rem;border-radius:3px;font-size:.8rem;font-weight:600}
  .badge-exp{color:#9b2226;background:#ffddd2;padding:.15rem .4rem;border-radius:3px;font-size:.8rem;font-weight:600}
  table{width:100%;border-collapse:collapse;font-size:.9rem}
  th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e9ecef}
  th{background:#f1f3f5;font-weight:600}
  .engines-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.5rem}
  .engine-chip{padding:.3rem .6rem;border-radius:4px;font-size:.8rem;border:1px solid #dee2e6}
  .engine-chip.cert{background:#d8f3dc;border-color:#95d5b2}
  .engine-chip.exp{background:#ffddd2;border-color:#ffb4a2}
  .cov-summary{display:flex;flex-wrap:wrap;gap:.75rem;margin-bottom:1rem}
  .stat{background:#f1f3f5;border-radius:6px;padding:.5rem .9rem;text-align:center;min-width:84px}
  .stat .n{font-size:1.4rem;font-weight:700;color:#1a1a2e;line-height:1}
  .stat .l{font-size:.7rem;color:#6c757d;text-transform:uppercase;letter-spacing:.04em;margin-top:.2rem}
  .stat.cert .n{color:#2d6a4f}.stat.exp .n{color:#9b2226}
  .fam{margin-bottom:.75rem;border:1px solid #e9ecef;border-radius:6px;overflow:hidden}
  .fam-head{display:flex;align-items:center;gap:.5rem;background:#f8f9fa;padding:.45rem .7rem;font-weight:600;font-size:.9rem;border-bottom:1px solid #e9ecef}
  .fam-head .count{margin-left:auto;font-size:.75rem;font-weight:500;color:#6c757d}
  .eng-row{display:flex;align-items:center;gap:.6rem;padding:.4rem .7rem;font-size:.85rem;border-top:1px solid #f1f3f5}
  .eng-row:first-child{border-top:none}
  .eng-row .nm{font-weight:600;min-width:150px}
  .eng-row .rt{color:#6c757d;font-size:.78rem}
  .eng-row .refs{margin-left:auto;font-size:.78rem;color:#495057}
  .pill{font-size:.68rem;font-weight:700;padding:.1rem .4rem;border-radius:3px;text-transform:uppercase;letter-spacing:.03em}
  .pill.cert{color:#2d6a4f;background:#d8f3dc}.pill.exp{color:#9b2226;background:#ffe5db}
  .cov-err{background:#fff3cd;border:1px solid #ffe69c;color:#664d03;border-radius:6px;padding:.5rem .8rem;font-size:.8rem;margin-bottom:1rem}
  footer{text-align:center;padding:2rem;color:#adb5bd;font-size:.85rem}
</style>
</head>
<body>
<header>
  <h1>Render</h1>
  <span>NL → Simulation → Interpretation Co-pilot</span>
</header>
<main>
  <!-- Ask panel -->
  <div class="card">
    <h2>Ask a simulation question</h2>
    <textarea id="q" placeholder="e.g. Simulate a harmonic oscillator with k=5 N/m and mass=1 kg for 10 seconds"></textarea>
    <div class="row">
      <input type="text" id="eng" placeholder="Engine (optional, e.g. scipy_ode)">
      <label style="font-size:.85rem;display:flex;align-items:center;gap:.3rem">
        <input type="checkbox" id="dry"> Dry run
      </label>
      <button class="btn btn-primary" onclick="submitAsk()">Run</button>
      <button class="btn btn-secondary" onclick="clearResults()">Clear</button>
    </div>
    <div id="status"></div>
  </div>

  <!-- Results panel -->
  <div class="card" id="results-card" style="display:none">
    <h2>Results <span id="engine-badge"></span></h2>
    <div id="quantities-table"></div>
    <h3 style="margin:.75rem 0 .4rem;font-size:.95rem">Interpretation</h3>
    <div id="interp" style="font-size:.9rem;line-height:1.5"></div>
    <details style="margin-top:.75rem">
      <summary style="cursor:pointer;font-size:.85rem;color:#6c757d">Raw JSON</summary>
      <pre id="results"></pre>
    </details>
  </div>

  <!-- Coverage scoreboard -->
  <div class="card">
    <h2>Engine coverage scoreboard</h2>
    <div id="cov-summary" class="cov-summary"></div>
    <div id="cov-errors"></div>
    <div id="cov-families"><span style="color:#6c757d">Loading…</span></div>
  </div>
</main>
<footer>Render v""" + render.__version__ + """ · WashU DTRC grant 1908</footer>

<script>
async function submitAsk(){
  const q=document.getElementById('q').value.trim();
  if(!q){alert('Enter a question.');return;}
  const eng=document.getElementById('eng').value.trim();
  const dry=document.getElementById('dry').checked;
  document.getElementById('status').textContent='Running…';
  document.getElementById('results-card').style.display='none';
  try{
    const res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q,engine:eng||null,dry_run:dry,interpret_result:true})});
    const data=await res.json();
    if(!res.ok){document.getElementById('status').textContent='Error: '+(data.detail||res.status);return;}
    document.getElementById('status').textContent='Done — run '+( data.run_id||'(dry)');
    renderResults(data);
  }catch(e){document.getElementById('status').textContent='Network error: '+e.message;}
}
function renderResults(data){
  const card=document.getElementById('results-card');
  card.style.display='block';
  const badge=document.getElementById('engine-badge');
  if(data.engine_status){
    const cls=data.engine_status==='certified'?'badge-cert':'badge-exp';
    badge.innerHTML='<span class="'+cls+'">'+(data.status_badge||data.engine_status)+'</span>';
  }
  // Quantities table
  const tbl=document.getElementById('quantities-table');
  if(data.quantities&&data.quantities.length){
    let html='<table><thead><tr><th>Quantity</th><th>Value</th><th>Unit</th></tr></thead><tbody>';
    for(const q of data.quantities){
      html+='<tr><td>'+q.name+'</td><td>'+q.value+'</td><td>'+(q.unit||'-')+'</td></tr>';
    }
    html+='</tbody></table>';
    tbl.innerHTML=html;
  } else { tbl.innerHTML=''; }
  // Interpretation
  const interp=document.getElementById('interp');
  if(data.interpretation){
    let txt=data.interpretation;
    if(data.confidence!=null) txt+='\\n\\nConfidence: '+(data.confidence*100).toFixed(0)+'%';
    if(data.assumptions&&data.assumptions.length) txt+='\\nAssumptions: '+data.assumptions.join('; ');
    interp.textContent=txt;
  } else { interp.textContent='(no interpretation)'; }
  document.getElementById('results').textContent=JSON.stringify(data,null,2);
}
function clearResults(){
  document.getElementById('status').textContent='';
  document.getElementById('results-card').style.display='none';
  document.getElementById('q').value='';
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function loadCoverage(){
  const famBox=document.getElementById('cov-families');
  const sumBox=document.getElementById('cov-summary');
  const errBox=document.getElementById('cov-errors');
  try{
    const res=await fetch('/coverage');
    const data=await res.json();
    sumBox.innerHTML=
      '<div class="stat"><div class="n">'+data.total_engines+'</div><div class="l">Engines</div></div>'+
      '<div class="stat"><div class="n">'+data.family_count+'</div><div class="l">Families</div></div>'+
      '<div class="stat cert"><div class="n">'+data.certified+'</div><div class="l">Certified</div></div>'+
      '<div class="stat exp"><div class="n">'+data.experimental+'</div><div class="l">Experimental</div></div>'+
      '<div class="stat"><div class="n">'+data.total_reference_cases+'</div><div class="l">Ref. cases</div></div>';
    errBox.innerHTML = (data.registration_errors&&data.registration_errors.length)
      ? '<div class="cov-err"><strong>⚠ Registration errors:</strong> '+data.registration_errors.map(esc).join('; ')+'</div>'
      : '';
    if(!data.families||!data.families.length){famBox.innerHTML='<span style="color:#6c757d">No engines registered.</span>';return;}
    let html='';
    for(const f of data.families){
      html+='<div class="fam"><div class="fam-head">'+esc(f.family)+
            '<span class="count">'+f.certified+' certified · '+f.experimental+' experimental</span></div>';
      for(const e of f.engines){
        const cls=e.status==='certified'?'cert':'exp';
        const refTitle=e.reference_case_names.length?' title="'+esc(e.reference_case_names.join(', '))+'"':'';
        html+='<div class="eng-row"><span class="pill '+cls+'">'+(e.status==='certified'?'✓ cert':'⚠ exp')+'</span>'+
              '<span class="nm">'+esc(e.name)+'</span>'+
              '<span class="rt">'+esc(e.runtime)+(e.env_summary?' · '+esc(e.env_summary):'')+'</span>'+
              '<span class="refs"'+refTitle+'>'+e.reference_cases+' ref case'+(e.reference_cases===1?'':'s')+'</span></div>';
      }
      html+='</div>';
    }
    famBox.innerHTML=html;
  }catch(e){famBox.innerHTML='<span style="color:#e63946">Could not load coverage: '+esc(e.message)+'</span>';}
}
loadCoverage();
</script>
</body>
</html>
"""
