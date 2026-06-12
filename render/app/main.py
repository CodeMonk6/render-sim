"""Render FastAPI application — main entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import render
from render.app.routers import ask as ask_router
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

  <!-- Engines panel -->
  <div class="card">
    <h2>Available engines</h2>
    <div id="engines-list" class="engines-grid"><span style="color:#6c757d">Loading…</span></div>
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
async function loadEngines(){
  try{
    const res=await fetch('/eval');
    const data=await res.json();
    const grid=document.getElementById('engines-list');
    if(!data.scores||!data.scores.length){grid.innerHTML='<span style="color:#6c757d">No engines registered.</span>';return;}
    let html='';
    for(const s of data.scores){
      const cls=s.status==='certified'?'cert':'exp';
      const icon=s.ok?'✓':'⚠';
      html+='<div class="engine-chip '+cls+'"><strong>'+s.engine+'</strong><br>'+
            icon+' '+s.passed+'/'+s.total+' cases · '+s.status+'</div>';
    }
    grid.innerHTML=html;
  }catch(e){document.getElementById('engines-list').innerHTML='<span style="color:#e63946">Could not load engines</span>';}
}
loadEngines();
</script>
</body>
</html>
"""
