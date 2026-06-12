/* Render — front-end controller. Vanilla JS, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const PALETTE = ["#4f46e5", "#0f9d6b", "#be123c", "#b7791f", "#7c3aed", "#0891b2"];

const EXAMPLES = [
  "Model a measles outbreak (R₀ ≈ 4) in a town of 50,000 with 5 initial infections over 180 days",
  "Simulate a damped harmonic oscillator, ω₀ = 2 rad/s, damping ratio 0.1, x₀ = 1, for 20 s",
  "Run an SEIR epidemic with incubation, β = 0.5, γ = 0.1, σ = 0.2 in a population of 10,000",
  "Solve a Lotka–Volterra predator–prey system for 50 time units",
];

/* ---------------- init ---------------- */
function init() {
  const ex = $("examples");
  EXAMPLES.forEach((t) => {
    const c = document.createElement("button");
    c.className = "chip"; c.type = "button"; c.textContent = t;
    c.onclick = () => { $("q").value = t; $("q").focus(); };
    ex.appendChild(c);
  });
  $("run-btn").onclick = submitAsk;
  $("clear-btn").onclick = clearAll;
  $("q").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submitAsk();
  });
  loadHealth();
  loadCoverage();
  loadHistory();
}

async function loadHealth() {
  try {
    const d = await (await fetch("/health")).json();
    $("version").textContent = "v" + d.version;
    const pill = $("provider-pill");
    pill.textContent = (d.provider || "live").toUpperCase();
    pill.className = "pill " + (d.has_key ? "pill-live" : "pill-muted");
    pill.title = d.model ? ("Model: " + d.model) : "LLM provider";
  } catch (_) { $("provider-pill").textContent = "OFFLINE"; }
}

/* ---------------- ask flow ---------------- */
function setLoading(on) {
  const b = $("run-btn");
  b.disabled = on;
  b.innerHTML = on ? '<span class="spinner"></span><span class="btn-label">Running…</span>'
                   : '<span class="btn-label">Run simulation</span>';
}
function flash(kind, title, body) {
  const f = $("flash");
  const icon = { loading: "⏳", clarify: "❓", abstain: "⛔", error: "⚠️", ok: "✓" }[kind] || "";
  f.className = "flash " + kind;
  f.innerHTML = `<span class="fi">${icon}</span><div><div class="flash-title">${esc(title)}</div>${body ? `<div>${esc(body)}</div>` : ""}</div>`;
  f.hidden = false;
}
function hideFlash() { $("flash").hidden = true; }

async function submitAsk() {
  const q = $("q").value.trim();
  if (!q) { $("q").focus(); return; }
  const engine = $("engine").value.trim() || null;
  const dry = $("dry").checked;

  $("results").hidden = true;
  $("skeleton").hidden = false;
  setLoading(true);
  flash("loading", "Mapping your question to a validated engine and running it…");

  try {
    const res = await fetch("/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, engine, dry_run: dry, interpret_result: true }),
    });
    const data = await res.json();
    if (!res.ok) { flash("error", "Something went wrong", data.detail || ("HTTP " + res.status)); return; }
    route(data);
    loadHistory();
  } catch (e) {
    flash("error", "Network error", e.message);
  } finally {
    setLoading(false);
    $("skeleton").hidden = true;
  }
}

function route(d) {
  if (d.status === "clarify") {
    flash("clarify", "I need a bit more detail",
      d.message + (d.missing_fields?.length ? " (" + d.missing_fields.join(", ") + ")" : ""));
    return;
  }
  if (d.status === "abstain") { flash("abstain", "Out of scope — I won't guess", d.message); return; }
  if (d.status === "error") { flash("error", "Run failed", d.message); return; }
  if (d.status === "dry_run") {
    flash("ok", "Intent is valid (dry run)",
      `Engine ${d.engine_name} would run with: ${JSON.stringify(filterParams(d.parameters))}`);
    return;
  }
  hideFlash();
  renderResult(d);
}

/* ---------------- result rendering ---------------- */
function renderResult(d) {
  $("results").hidden = false;

  const cert = d.engine_status === "certified";
  const badge = $("result-badge");
  badge.className = "badge " + (cert ? "cert" : "exp");
  badge.textContent = d.status_badge || (cert ? "✓ CERTIFIED ENGINE" : "⚠ EXPERIMENTAL ENGINE");

  $("result-engine").innerHTML =
    `Engine <span class="mono">${esc(d.engine_name)}</span> · family <span class="mono">${esc(d.engine_family)}</span>`;

  // confidence
  if (typeof d.confidence === "number") {
    $("confidence").hidden = false;
    $("conf-val").textContent = Math.round(d.confidence * 100) + "%";
    $("conf-fill").style.width = Math.round(d.confidence * 100) + "%";
  } else $("confidence").hidden = true;

  // metrics
  const mc = $("metrics-card");
  if (d.quantities?.length) {
    mc.hidden = false;
    $("metrics").innerHTML = d.quantities.map((q) => {
      const v = typeof q.value === "number" ? fmtNum(q.value, q.unit, q.name) : esc(q.value);
      return `<div class="metric"><div class="m-name" title="${esc(q.name)}">${esc(q.name)}</div>
        <div class="m-val">${v}<span class="m-unit">${esc(q.unit || "")}</span></div></div>`;
    }).join("");
  } else mc.hidden = true;

  // plot
  drawPlot(d.series);

  // interpretation
  const ic = $("interp-card");
  if (d.interpretation) {
    ic.hidden = false;
    $("interp").innerHTML = mdLite(d.interpretation);
    const as = $("assumptions");
    if (d.assumptions?.length) {
      as.hidden = false;
      as.innerHTML = "<h4>Assumptions</h4><ul>" +
        d.assumptions.map((a) => `<li>${esc(a)}</li>`).join("") + "</ul>";
    } else as.hidden = true;
  } else ic.hidden = true;

  // provenance
  const pc = $("prov-card");
  if (d.run_id) {
    pc.hidden = false;
    $("prov-runid").textContent = d.run_id;
    $("prov-replay").textContent = d.replay_cmd || ("render replay --run-id " + d.run_id);
    const dl = $("prov-download");
    dl.href = "/runs/" + encodeURIComponent(d.run_id);
    dl.setAttribute("download", "render-" + d.run_id.slice(0, 8) + ".json");
    $("prov-params").textContent = JSON.stringify(filterParams(d.parameters), null, 2);
  } else pc.hidden = true;

  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Keep only the schema-bound params (drop the LLM's generic first-pass keys for display).
function filterParams(p) {
  if (!p) return {};
  const drop = ["system_type", "model_type", "disease"];
  const out = {};
  for (const k of Object.keys(p)) if (!drop.includes(k)) out[k] = p[k];
  return out;
}

const COUNT_UNITS = ["persons", "person", "people", "cells", "molecules", "individuals", "agents", "particles"];
function fmtNum(x, unit, name) {
  if (typeof x !== "number" || !isFinite(x)) return String(x);
  const a = Math.abs(x);
  // Count quantities read as whole things — no fractional persons.
  if ((unit && COUNT_UNITS.includes(unit)) || (name && /count|^n_|nfev/i.test(name))) {
    return Math.round(x).toLocaleString();
  }
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return x.toExponential(3);
  // Trim to ~4 significant figures, drop trailing zeros.
  const r = Number(x.toPrecision(4));
  return r.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/* ---------------- SVG line chart ---------------- */
function drawPlot(series) {
  const card = $("plot-card");
  if (!series || !series.x || !series.y || !series.y.length) { card.hidden = true; return; }
  card.hidden = false;
  $("plot-title").textContent = series.title || "Trajectory";

  const W = 680, H = 300, Pl = 56, Pr = 18, Pt = 16, Pb = 42;
  const xs = series.x.values;
  const allY = series.y.flatMap((s) => s.values);
  let yMin = Math.min(...allY), yMax = Math.max(...allY);
  if (yMin === yMax) { yMax += 1; yMin -= 1; }
  const yPad = (yMax - yMin) * 0.06; yMin -= yPad; yMax += yPad;
  const xMin = xs[0], xMax = xs[xs.length - 1];
  const sx = (x) => Pl + (x - xMin) / (xMax - xMin || 1) * (W - Pl - Pr);
  const sy = (y) => H - Pb - (y - yMin) / (yMax - yMin || 1) * (H - Pt - Pb);

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">`;
  // horizontal grid + y ticks
  const NY = 4;
  for (let i = 0; i <= NY; i++) {
    const yv = yMin + (yMax - yMin) * i / NY;
    const yp = sy(yv);
    svg += `<line class="grid-line" x1="${Pl}" y1="${yp}" x2="${W - Pr}" y2="${yp}"/>`;
    svg += `<text class="axis-text" x="${Pl - 8}" y="${yp + 3}" text-anchor="end">${fmtTick(yv)}</text>`;
  }
  // x ticks
  const NX = 5;
  for (let i = 0; i <= NX; i++) {
    const xv = xMin + (xMax - xMin) * i / NX;
    const xp = sx(xv);
    svg += `<text class="axis-text" x="${xp}" y="${H - Pb + 16}" text-anchor="middle">${fmtTick(xv)}</text>`;
  }
  // axes
  svg += `<line class="axis-line" x1="${Pl}" y1="${Pt}" x2="${Pl}" y2="${H - Pb}"/>`;
  svg += `<line class="axis-line" x1="${Pl}" y1="${H - Pb}" x2="${W - Pr}" y2="${H - Pb}"/>`;
  // axis titles
  const xt = series.x.unit ? `${series.x.name} (${series.x.unit})` : series.x.name;
  svg += `<text class="axis-title" x="${(Pl + W - Pr) / 2}" y="${H - 6}" text-anchor="middle">${esc(xt)}</text>`;
  // series paths
  series.y.forEach((s, idx) => {
    const color = PALETTE[idx % PALETTE.length];
    const dpath = s.values.map((v, i) => (i ? "L" : "M") + sx(xs[i]).toFixed(1) + " " + sy(v).toFixed(1)).join(" ");
    svg += `<path class="series-path" d="${dpath}" stroke="${color}"/>`;
  });
  svg += `</svg>`;
  $("plot").innerHTML = svg;

  $("legend").innerHTML = series.y.map((s, i) =>
    `<span class="lg"><span class="sw" style="background:${PALETTE[i % PALETTE.length]}"></span>${esc(s.name)}</span>`
  ).join("");
}
function fmtTick(v) {
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-2 || a >= 1e5)) return v.toExponential(1);
  return (Math.round(v * 100) / 100).toLocaleString();
}

/* ---------------- markdown-lite (safe) ---------------- */
function mdLite(src) {
  const lines = String(src).split("\n");
  let html = "", inUl = false, inOl = false;
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
  const closeLists = () => { if (inUl) { html += "</ul>"; inUl = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  for (let raw of lines) {
    const line = raw.trim();
    if (!line) { closeLists(); continue; }
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)/))) { closeLists(); html += `<h3>${inline(m[2])}</h3>`; }
    else if ((m = line.match(/^[-•*]\s+(.*)/))) { if (!inUl) { closeLists(); html += "<ul>"; inUl = true; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = line.match(/^\d+[.)]\s+(.*)/))) { if (!inOl) { closeLists(); html += "<ol>"; inOl = true; } html += `<li>${inline(m[1])}</li>`; }
    else { closeLists(); html += `<p>${inline(line)}</p>`; }
  }
  closeLists();
  return html;
}

/* ---------------- coverage ---------------- */
async function loadCoverage() {
  try {
    const d = await (await fetch("/coverage")).json();
    $("cov-summary").innerHTML =
      `<div class="stat"><div class="n">${d.total_engines}</div><div class="l">Engines</div></div>
       <div class="stat cert"><div class="n">${d.certified}</div><div class="l">Certified</div></div>
       <div class="stat exp"><div class="n">${d.experimental}</div><div class="l">Experimental</div></div>`;
    $("cov-errors").innerHTML = (d.registration_errors?.length)
      ? `<div class="cov-err"><strong>⚠ Registration errors:</strong> ${d.registration_errors.map(esc).join("; ")}</div>` : "";
    $("cov-families").innerHTML = (d.families || []).map((f) => {
      const rows = f.engines.map((e) =>
        `<div class="eng-row"><span class="dot ${e.status === "certified" ? "cert" : "exp"}"></span>
          <span class="nm" title="${esc(e.name)}">${esc(e.name)}</span>
          <span class="rt">${esc(e.runtime)}${e.reference_cases ? " · " + e.reference_cases + " ref" : ""}</span></div>`).join("");
      const cnt = `<span class="count">${f.certified ? `<span class="c-ok">${f.certified}✓</span>` : ""}` +
                  `${f.experimental ? `<span class="c-exp">${f.experimental}⚠</span>` : ""}</span>`;
      return `<div class="fam"><div class="fam-head"><span class="fam-name">${esc(f.family)}</span>${cnt}</div>${rows}</div>`;
    }).join("");
  } catch (e) {
    $("cov-families").innerHTML = `<span class="muted">Could not load coverage.</span>`;
  }
}

/* ---------------- history ---------------- */
async function loadHistory() {
  try {
    const d = await (await fetch("/runs?limit=12")).json();
    const h = $("history");
    if (!d.runs?.length) { h.innerHTML = `<span class="muted">No runs yet.</span>`; return; }
    h.innerHTML = d.runs.map((r) =>
      `<div class="hrow" data-id="${esc(r.run_id)}">
        <div class="hq">${esc(r.question || r.engine_name)}</div>
        <div class="hmeta"><span class="dot ${r.engine_status === "certified" ? "cert" : "exp"}"></span>
          <span class="nm">${esc(r.engine_name)}</span></div></div>`).join("");
    h.querySelectorAll(".hrow").forEach((el) => el.onclick = () => openRun(el.dataset.id));
  } catch (_) { /* leave as-is */ }
}

async function openRun(id) {
  try {
    const m = await (await fetch("/runs/" + encodeURIComponent(id))).json();
    const series = (m.bundle && m.bundle.metadata) ? m.bundle.metadata.series : null;
    renderResult({
      status: "ok",
      engine_name: m.engine_name, engine_family: (m.intent || {}).family,
      engine_status: m.engine_status, run_id: m.run_id,
      quantities: (m.bundle?.quantities || []).map((q) => ({ name: q.name, value: q.value, unit: q.unit })),
      series,
      interpretation: null,
      confidence: (m.validation || {}).confidence,
      assumptions: (m.intent || {}).assumptions || [],
      replay_cmd: m.replay_cmd, parameters: (m.intent || {}).parameters || {},
    });
    hideFlash();
  } catch (e) { flash("error", "Could not load run", e.message); }
}

function clearAll() {
  $("q").value = ""; $("engine").value = ""; $("dry").checked = false;
  $("results").hidden = true; hideFlash(); $("q").focus();
}

document.addEventListener("DOMContentLoaded", init);
