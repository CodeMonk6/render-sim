"""Local (in-process) engine runner.

Runs an engine adapter synchronously in the current process and returns a
complete RunManifest.  Heavy / HPC engines use the Slurm runner instead.
"""

from __future__ import annotations

import platform
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from render.registry.protocol import EngineAdapter
from render.types import Intent, RawOutputs, RunManifest, ValidationReport
from render.validate.stack import post_run_validate, pre_run_validate


def run_local(
    adapter: EngineAdapter,
    intent: Intent,
    *,
    manifest_dir: Path | None = None,
) -> RunManifest:
    """Execute *adapter* with *intent* locally; return a provenance manifest.

    Steps:
      1. Pre-run validation (layers 1-3).
      2. Build engine inputs.
      3. Run and record wall time.
      4. Parse raw outputs.
      5. Post-run validation (layer 5).
      6. Build and (optionally) persist a RunManifest.
    """
    # 1. Pre-run validation
    validation = pre_run_validate(adapter, intent)

    # 2. Build inputs
    inputs = adapter.build_inputs(intent)

    # 3. Run
    t0 = time.perf_counter()
    raw: RawOutputs = adapter.run(inputs, intent.resources)
    elapsed = time.perf_counter() - t0
    if raw.wall_time_s == 0.0:
        raw = raw.model_copy(update={"wall_time_s": round(elapsed, 6)})

    # 4. Parse
    bundle = adapter.parse(raw)

    # 5. Post-run validation (layer 5)
    post_val = post_run_validate(bundle)
    validation = _merge_post(validation, post_val)

    # 6. Build manifest
    run_id = uuid.uuid4()
    engine_version = getattr(adapter, "version", "0.0.0")
    plat = f"{sys.platform}/py{platform.python_version()}"

    if manifest_dir is not None:
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{run_id}.json"
        replay_cmd = f"render replay {manifest_path}"
    else:
        replay_cmd = f"render replay --run-id {run_id}"

    manifest = RunManifest(
        run_id=run_id,
        timestamp=datetime.now(UTC),
        intent=intent,
        engine_name=adapter.name,
        engine_version=engine_version,
        engine_status=adapter.status,
        environment=adapter.environment,
        inputs=inputs,
        raw_outputs=raw,
        bundle=bundle,
        validation=validation,
        platform=plat,
        seed=inputs.seed,
        replay_cmd=replay_cmd,
    )

    if manifest_dir is not None:
        manifest_path.write_text(manifest.model_dump_json(indent=2))  # type: ignore[union-attr]

    return manifest


def _merge_post(pre: ValidationReport, post: ValidationReport) -> ValidationReport:
    if not post.passed or post.warnings:
        return ValidationReport(
            passed=pre.passed and post.passed,
            failed_layer=post.failed_layer if not post.passed else pre.failed_layer,
            errors=pre.errors + post.errors,
            warnings=pre.warnings + post.warnings,
            in_regime=pre.in_regime and post.in_regime,
            confidence=min(pre.confidence, post.confidence),
        )
    return pre
