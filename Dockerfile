# Render — container image for the FastAPI app (serves the web UI + API).
#
# Runs as a non-root user (UID 1000) so it works identically on Hugging Face
# Spaces, Cloud Run, Railway, and locally. Lean by default (core certified
# engines, no heavy native builds). Add engine families and the Julia/FreeBird
# runtime at build time:
#
#   docker build -t render .                                                  # lean
#   docker build --build-arg ENGINE_EXTRAS="dft,md,materials" -t render .     # PySCF + OpenMM + ASE
#   docker build --build-arg ENGINE_EXTRAS="dft,md,materials,ssa,des,abm,mcmc,nbody" \
#                --build-arg INSTALL_JULIA=true -t render .                    # + FreeBird.jl
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    RENDER_RUNS_DIR=/tmp/.render_runs

# Comma-separated optional-dependency groups from pyproject.toml. Empty = core only.
ARG ENGINE_EXTRAS=""
ARG INSTALL_JULIA="false"

# System toolchain (needed for native engine builds and the Julia installer).
RUN if [ -n "$ENGINE_EXTRAS" ] || [ "$INSTALL_JULIA" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            build-essential gfortran libopenblas-dev curl ca-certificates && \
        rm -rf /var/lib/apt/lists/* ; \
    fi

# Python deps installed to the system site-packages as root (world-readable, so
# the non-root runtime user can import them).
WORKDIR /install
COPY pyproject.toml ./
COPY render ./render
RUN if [ -n "$ENGINE_EXTRAS" ]; then pip install ".[$ENGINE_EXTRAS]" ; else pip install . ; fi

# Non-root user — Hugging Face Spaces runs containers as UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:/home/user/.juliaup/bin:$PATH \
    RENDER_JULIA=/home/user/.juliaup/bin/julia
WORKDIR /home/user/app

# Optional: Julia + FreeBird.jl for the atomistic-MC flagship engine. Installed
# AS the runtime user, with the package depot precompiled into the user-owned
# ~/.julia so `using FreeBird` is instant (and writable) at runtime.
RUN if [ "$INSTALL_JULIA" = "true" ]; then \
        curl -fsSL https://install.julialang.org | sh -s -- --yes && \
        /home/user/.juliaup/bin/julia -e 'import Pkg; Pkg.add(["FreeBird","Unitful"]); Pkg.precompile()' ; \
    fi

EXPOSE 8000

# Honour the platform-provided $PORT (Cloud Run, Railway, Render.com, HF Spaces).
CMD ["sh", "-c", "uvicorn render.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
