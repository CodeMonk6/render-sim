"""Entry point called by the Slurm batch script on the compute node.

The batch script does:
    python -c "from render.execute.slurm_aiida._runner import run_job; \
               run_job('adapter_name', 'intent.json', 'manifest.json')"

This module loads the adapter from the registry, deserializes the intent,
runs it locally (on the compute node), and writes the RunManifest.
"""
from __future__ import annotations

from pathlib import Path

from render.types import Intent, RunManifest


def run_job(adapter_name: str, intent_path: str, manifest_path: str) -> RunManifest:
    """Load adapter by name, run the intent, write the manifest."""
    from render.execute.local import run_local
    from render.registry import registry

    adapter = registry.get(adapter_name)
    if adapter is None:
        raise ValueError(
            f"Adapter '{adapter_name}' not found in registry. "
            f"Available: {[a.name for a in registry.list_all()]}"
        )

    intent = Intent.model_validate_json(Path(intent_path).read_text())
    manifest_dir = Path(manifest_path).parent
    manifest = run_local(adapter, intent, manifest_dir=manifest_dir)

    out = Path(manifest_path)
    out.write_text(manifest.model_dump_json(indent=2))
    return manifest
