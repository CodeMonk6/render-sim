"""Canonical engine bootstrap — the single source of truth for which adapters exist.

Every entry point that needs the full engine matrix (CLI, REST API, eval harness)
registers through :func:`register_all_engines` so the live registry is identical
everywhere.  The previous approach duplicated the adapter list in the CLI and
swallowed *all* exceptions with a bare ``except: pass`` — which silently hid a
wrong class name (``SIRAdapter`` vs the real ``EpiAdapter``), so the epidemiology
family never registered anywhere.  That is exactly the "silently wrong" failure
this project forbids.

This module distinguishes the two failure modes:

* **A class named here does not exist** — a bug in *our* canonical list. Recorded
  as an error and surfaced (e.g. via the ``/coverage`` endpoint); never hidden.
* **An engine module fails to import** (a genuinely-missing optional dependency) —
  tolerated and recorded as a skip, because adapters use lazy imports and a heavy
  backend may be absent locally while the adapter is still worth listing.

Registration never raises, so it can run on every request without breaking a
session; callers inspect the returned :class:`BootstrapReport` to see what
happened.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from render.engines.reference import HarmonicOscillatorAdapter
from render.registry import EngineRegistry

# Canonical (module path, adapter class name) pairs — one row per registered
# engine.  Keep this list correct: a wrong class name here is a hard error, not a
# silent skip.
ENGINE_SPECS: list[tuple[str, str]] = [
    ("render.engines.ode", "SciPyODEAdapter"),
    ("render.engines.epi", "EpiAdapter"),
    ("render.engines.ssa", "GillesPy2Adapter"),
    ("render.engines.des", "SimPyAdapter"),
    ("render.engines.abm", "MesaAdapter"),
    ("render.engines.nbody", "ReboundAdapter"),
    ("render.engines.mcmc", "EmceeAdapter"),
    ("render.engines.sbml", "TelluriumAdapter"),
    ("render.engines.md", "OpenMMAdapter"),
    ("render.engines.lammps", "LAMMPSAdapter"),
    ("render.engines.gromacs", "GROMACSAdapter"),
    ("render.engines.dft", "PySCFAdapter"),
    ("render.engines.materials_utils", "ASEAdapter"),
    ("render.engines.freebird", "FreeBirdAdapter"),
    ("render.engines.fem", "FEniCSxAdapter"),
    ("render.engines.em", "MeepAdapter"),
    ("render.engines.cfd", "SU2Adapter"),
]


@dataclass
class BootstrapReport:
    """Outcome of a :func:`register_all_engines` call.

    ``errors`` are config bugs (a class named in :data:`ENGINE_SPECS` is missing);
    these should never appear in a correct build.  ``skipped`` are tolerated
    import failures (optional backend absent).  ``registered`` lists the engine
    *names* now in the registry from this call.
    """

    registered: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (spec, reason)
    errors: list[tuple[str, str]] = field(default_factory=list)    # (spec, reason)

    @property
    def ok(self) -> bool:
        """True when no canonical-list config bug was hit."""
        return not self.errors


def register_all_engines(reg: EngineRegistry | None = None) -> BootstrapReport:
    """Register every canonical engine adapter into ``reg`` (default: the singleton).

    Idempotent: an engine already in the registry is left untouched and recorded in
    ``already_present``.  Never raises — inspect the returned report.
    """
    if reg is None:
        from render.registry import registry as _singleton
        reg = _singleton

    report = BootstrapReport()

    # The built-in closed-form reference engine is always available.
    if "harmonic_oscillator" not in reg:
        reg.register(HarmonicOscillatorAdapter())
        report.registered.append("harmonic_oscillator")
    else:
        report.already_present.append("harmonic_oscillator")

    for module_path, class_name in ENGINE_SPECS:
        spec = f"{module_path}.{class_name}"
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:  # tolerate a missing optional backend
            report.skipped.append((spec, f"import failed: {type(exc).__name__}: {exc}"))
            continue

        cls = getattr(mod, class_name, None)
        if cls is None:
            # Our canonical list names a class that does not exist — a real bug.
            report.errors.append((spec, "class not found in module"))
            continue

        try:
            adapter = cls()
        except Exception as exc:
            report.skipped.append((spec, f"construction failed: {type(exc).__name__}: {exc}"))
            continue

        if adapter.name in reg:
            report.already_present.append(adapter.name)
            continue

        try:
            reg.register(adapter)
            report.registered.append(adapter.name)
        except Exception as exc:
            report.errors.append((spec, f"registration rejected: {exc}"))

    return report
