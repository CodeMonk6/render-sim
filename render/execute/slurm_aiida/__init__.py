"""Slurm / AiiDA runner for HPC execution on WashU Compute2.

Architecture:
  1. SlurmRunner.submit() writes a job script, calls sbatch, and returns a job ID.
  2. SlurmRunner.wait() polls squeue until the job is COMPLETED or FAILED.
  3. SlurmRunner.collect() reads the output directory and returns a RunManifest.

The thin-Slurm path writes the same RunManifest as the local runner, so
provenance and replay work identically regardless of execution site.

AiiDA integration (optional, enabled by [hpc] extra):
  When aiida-core is installed, SlurmRunner can alternatively submit via an
  AiiDA Slurm scheduler/transport for automatic provenance graph capture.

Usage:
    runner = SlurmRunner(partition="general-cpu", account="compute2-workshop")
    job_id = runner.submit(adapter, intent)
    manifest = runner.wait_and_collect(job_id)
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from render.registry.protocol import EngineAdapter
from render.types import Intent, RunManifest


@dataclass
class SlurmJobSpec:
    """Slurm sbatch parameters derived from an Intent's ResourceSpec."""

    partition: str = ""
    account: str = ""
    nodes: int = 1
    ntasks_per_node: int = 1
    memory_gb: int = 4
    walltime: str = "01:00:00"
    gpu: bool = False
    constraint: str = ""


class SlurmRunner:
    """Submit and monitor jobs on a Slurm cluster; collect RunManifest on completion."""

    def __init__(
        self,
        *,
        partition: str = "general-cpu",
        account: str = "compute2-workshop",
        work_dir: Path = Path(".render_slurm"),
        python_cmd: str = "python",
    ) -> None:
        self.partition = partition
        self.account = account
        self.work_dir = Path(work_dir)
        self.python_cmd = python_cmd

    def submit(self, adapter: EngineAdapter, intent: Intent) -> str:
        """Write a batch script and call sbatch; return the Slurm job ID."""
        job_dir = self.work_dir / str(intent.intent_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        # Serialize intent
        intent_file = job_dir / "intent.json"
        intent_file.write_text(intent.model_dump_json(indent=2))

        # Write job script
        script = self._build_script(adapter, intent, job_dir)
        script_file = job_dir / "job.sh"
        script_file.write_text(script)
        script_file.chmod(0o755)

        result = subprocess.run(
            ["sbatch", str(script_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        # sbatch output: "Submitted batch job 12345"
        job_id = result.stdout.strip().split()[-1]
        (job_dir / "job_id.txt").write_text(job_id)
        return job_id

    def poll(self, job_id: str) -> str:
        """Return the Slurm job state string (PENDING, RUNNING, COMPLETED, FAILED, …)."""
        result = subprocess.run(
            ["squeue", "-j", job_id, "-h", "-o", "%T"],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip()
        if not state:
            # Job has left the queue — check sacct
            acct = subprocess.run(
                ["sacct", "-j", job_id, "-n", "-o", "State"],
                capture_output=True,
                text=True,
            )
            state = acct.stdout.strip().split("\n")[0].strip() if acct.stdout.strip() else "UNKNOWN"
        return state

    def wait(self, job_id: str, poll_interval: float = 30.0, timeout: float = 86400.0) -> str:
        """Block until the job completes; return final state string."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.poll(job_id)
            if state in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL"}:
                return state
            time.sleep(poll_interval)
        return "TIMEOUT"

    def collect(self, job_id: str) -> RunManifest:
        """Read the manifest written by the batch job; raise if job failed."""
        job_dirs = list(self.work_dir.glob("*"))
        manifest_file = None
        for d in job_dirs:
            jid_file = d / "job_id.txt"
            if jid_file.exists() and jid_file.read_text().strip() == job_id:
                manifest_file = d / "manifest.json"
                break
        if manifest_file is None or not manifest_file.exists():
            raise FileNotFoundError(
                f"Manifest for job {job_id} not found in {self.work_dir}"
            )
        return RunManifest.model_validate_json(manifest_file.read_text())

    def submit_and_wait(self, adapter: EngineAdapter, intent: Intent) -> RunManifest:
        """Convenience: submit, wait, and collect."""
        job_id = self.submit(adapter, intent)
        state = self.wait(job_id)
        if state != "COMPLETED":
            raise RuntimeError(f"Slurm job {job_id} ended with state {state!r}")
        return self.collect(job_id)

    def _build_script(self, adapter: EngineAdapter, intent: Intent, job_dir: Path) -> str:
        res = intent.resources
        walltime = _hours_to_slurm(res.walltime_hours)
        lines = ["#!/bin/bash"]
        if self.partition:
            lines.append(f"#SBATCH --partition={self.partition}")
        if self.account:
            lines.append(f"#SBATCH --account={self.account}")
        lines += [
            f"#SBATCH --nodes={res.nodes}",
            f"#SBATCH --ntasks-per-node={res.cores_per_node}",
            f"#SBATCH --mem={int(res.memory_gb)}G",
            f"#SBATCH --time={walltime}",
            f"#SBATCH --output={job_dir}/slurm-%j.out",
            f"#SBATCH --error={job_dir}/slurm-%j.err",
        ]
        if res.gpu:
            lines.append("#SBATCH --gres=gpu:1")

        # Initialize Lmod + Slurm (RIS guide), then activate the render env and
        # load any engine-specific module.
        lines += [
            "",
            "# Initialize RIS module system, then activate render conda env",
            "source /etc/profile >/dev/null 2>&1 || true",
            "ml load ris >/dev/null 2>&1 || true",
            "source \"$HOME/.render_c2_env\"",
        ]
        env = adapter.environment
        if env.module_name:
            lines += [f"ml load {env.module_name} 2>/dev/null || true"]

        lines += [
            "",
            "set -euo pipefail",
            f"cd {job_dir}",
            f"{self.python_cmd} -c \\"
            f"\"from render.execute.slurm_aiida._runner import run_job; "
            f"run_job('{adapter.name}', 'intent.json', 'manifest.json')\"",
        ]
        return "\n".join(lines) + "\n"


def _hours_to_slurm(hours: float) -> str:
    total_secs = int(hours * 3600)
    h = total_secs // 3600
    m = (total_secs % 3600) // 60
    s = total_secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
