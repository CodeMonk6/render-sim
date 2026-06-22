# Render

**A natural-language to simulation to interpretation co-pilot for researchers.**

Ask a scientific question in plain English. Render parses the intent, routes it to a validated simulation engine, runs it with full provenance, and returns a grounded, plain-language interpretation — never a fabricated number.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)
![Typer](https://img.shields.io/badge/CLI-Typer-2C9CD6)
![NumPy](https://img.shields.io/badge/NumPy-013243?logo=numpy&logoColor=white)
![SciPy](https://img.shields.io/badge/SciPy-8CAAE6?logo=scipy&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-structured%20output-7C3AED)
![SLURM](https://img.shields.io/badge/HPC-SLURM-EE0000)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tested-pytest-0A9EDC?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/status-research-blue)

---

## What it does

Running a scientific simulation usually means knowing *which* tool to use, learning its input format, hand-translating your question into parameters, executing it, and then carefully checking that the output is physically sane. That friction keeps simulation out of reach for anyone who isn't already an expert in a specific solver.

Render collapses that workflow into a single question. You type something like *"how does a damped pendulum decay over 10 seconds?"* or *"simulate the folding energetics of a small peptide"*, and Render:

- figures out which **family of physics/chemistry** the question belongs to,
- selects a concrete **engine** capable of answering it,
- extracts and validates the **parameters** against that engine's schema,
- **runs** the simulation (locally, or as a heavy job on an HPC cluster),
- and writes back a **grounded interpretation** with a confidence badge and explicit assumptions.

The guiding principle is trust. Every numeric claim in the final answer must trace back to a quantity the simulation actually produced, and every engine that earns a "Certified" badge has reproduced published reference results within statistical tolerance.

## How it works

Render is built around a uniform **engine adapter contract** and a **seven-layer validation stack**. A single orchestration entry point drives both the REST API and the CLI, so their behavior is identical.

```
  natural-language question
            │
            ▼
   ┌──────────────────┐   structured-output LLM parse
   │  Intent parsing   │   → family + engine + raw parameters
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐   re-extract into the chosen engine's
   │ Parameter binding │   Pydantic schema (skipped if already valid)
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐   clarify if under-specified;
   │ Validate / abstain│   abstain rather than guess
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐   local run, or dispatch to a SLURM HPC cluster
   │     Execute       │   → typed results + provenance manifest
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐   number-grounded, plain-language explanation
   │  Interpretation   │   with confidence + assumptions
   └──────────────────┘
```

**The seven-layer validation stack** runs around every execution:

1. Pydantic schema validation of the intent
2. Physical-constraint and unit checks (dimensional analysis via Pint)
3. In-regime check (is the request inside the engine's validity envelope?)
4. Per-engine pre-flight dry run
5. Post-run sanity (NaN/Inf, convergence)
6. Reference-case regression (reproduce published results within tolerance)
7. Interpretation number-grounding (the explainer may only cite real result values)

**Why parameter binding is two passes:** the first NL pass picks an engine but emits generic parameter names; once the engine is known, Render re-extracts the question directly into *that engine's* schema. The second pass is skipped when the first already satisfies the schema, so well-formed requests stay fast.

## Highlights

- **Pluggable engine registry.** Adding a new simulation engine means implementing one `EngineAdapter` protocol and supplying reference cases — nothing else in the pipeline changes. The registry currently spans engine families across classical mechanics, ODE/CFD/FEM solvers, molecular dynamics, density-functional theory, stochastic chemical kinetics, agent-based and discrete-event models, n-body, MCMC, epidemiology, and electromagnetics.
- **Trust as a first-class concept.** Engines carry an explicit `certified` / `experimental` status. Certification is earned, not declared: an engine is promoted only after it reproduces its published reference cases within statistical tolerance.
- **Anti-hallucination by construction.** The interpretation layer is checked against the actual result bundle — any number in the prose that doesn't match a produced quantity (within tolerance) is flagged as a fabrication. Citation years and small contextual integers are deliberately ignored so plain prose isn't penalized.
- **Clarify or abstain.** When a question is under-specified or outside an engine's regime, Render asks a focused clarifying question or abstains, rather than silently guessing.
- **Reproducible by default.** Every run writes a provenance manifest, and a `replay` command re-executes a saved manifest and compares against the original within a relative tolerance.
- **One pipeline, two front ends.** A Typer CLI (`ask`, `eval`, `replay`, `serve`) and a FastAPI service (with a small static web UI, `/docs`, optional token gate, and per-IP rate limiting) share the exact same core.
- **Provider-agnostic LLM layer.** Structured outputs via the `instructor` library, with a clean abstraction over multiple LLM providers and a configurable default model.
- **HPC certification harness.** Engine certification jobs run as batch submissions on a SLURM HPC cluster; results are collected into a certification scorecard.

## Usage

```bash
render ask "how does a damped pendulum decay over 10 seconds?"
```

The same question can be posed through the REST API (`POST /ask`) or the web UI served by `render serve`.

## Tech stack

- **Language:** Python 3.11+
- **Web / API:** FastAPI + Uvicorn, with a lightweight static front end
- **CLI:** Typer + Rich
- **Validation & typing:** Pydantic v2, Pint (units)
- **Scientific core:** NumPy, SciPy, Matplotlib
- **LLM:** `instructor` for structured outputs over a provider-agnostic client
- **Simulation engines (optional extras):** OpenMM, LAMMPS, GROMACS, PySCF, ASE / pymatgen, GillesPy2, SimPy, Mesa, emcee, REBOUND, Tellurium, and a Julia-backed engine via `juliacall`
- **HPC orchestration:** AiiDA + SLURM batch jobs
- **Packaging & tooling:** `uv`, Hatchling, Ruff, mypy, pytest (with coverage)
- **Delivery:** Docker / docker-compose, GitHub Actions CI and image publishing

## Status

Active research project. The core pipeline — intent parsing, parameter binding, the seven-layer validation stack, local execution with provenance, grounded interpretation, and the CLI + API front ends — is in place, with a growing roster of engines moving from experimental toward certified as they pass their reference cases. The code lives in a private repository; this page is a public overview of the architecture and approach.
