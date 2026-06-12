# Render — container image for the FastAPI app (serves the web UI + API).
#
# The base image ships the always-available certified engines (ODE, epidemic/PK,
# and the closed-form reference engine) with zero heavy native builds, so it
# deploys cleanly on small free tiers. Add more engine families at build time:
#
#   docker build -t render .                                   # lean default
#   docker build --build-arg ENGINE_EXTRAS="ssa,des,abm,mcmc,nbody,materials" -t render .
#   docker build --build-arg ENGINE_EXTRAS="dft,md,materials"  -t render .   # heavy: PySCF + OpenMM
#
# FreeBird.jl needs a Julia runtime; build with INSTALL_JULIA=true to vendor it.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Comma-separated optional-dependency groups from pyproject.toml. Empty = core only.
ARG ENGINE_EXTRAS=""
ARG INSTALL_JULIA="false"

# Build toolchain only when heavy/native engines are requested; kept out of the
# final layer to keep the image small for lean builds.
RUN if [ -n "$ENGINE_EXTRAS" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            build-essential gfortran libopenblas-dev && \
        rm -rf /var/lib/apt/lists/* ; \
    fi

WORKDIR /app

# Copy metadata first for better layer caching, then the package.
COPY pyproject.toml ./
COPY render ./render

RUN if [ -n "$ENGINE_EXTRAS" ]; then \
        pip install ".[$ENGINE_EXTRAS]" ; \
    else \
        pip install . ; \
    fi

# Optional: vendor a Julia runtime + FreeBird.jl for the atomistic-MC engine.
RUN if [ "$INSTALL_JULIA" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
        curl -fsSL https://install.julialang.org | sh -s -- --yes && \
        /root/.juliaup/bin/julia -e 'import Pkg; Pkg.add(["FreeBird","Unitful"]); Pkg.precompile()' && \
        rm -rf /var/lib/apt/lists/* ; \
    fi
ENV PATH="/root/.juliaup/bin:${PATH}"

# Manifests (provenance) land here; mount a volume to persist across restarts.
ENV RENDER_RUNS_DIR=/data/.render_runs
RUN mkdir -p /data/.render_runs
VOLUME ["/data"]

EXPOSE 8000

# Honour the platform-provided $PORT (Cloud Run, Railway, Render.com, HF Spaces).
CMD ["sh", "-c", "uvicorn render.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
