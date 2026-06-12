"""Render CLI — render [ask | eval | replay | serve]"""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

import render

app = typer.Typer(
    name="render",
    help="Natural-language → simulation → interpretation co-pilot for researchers.",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Print version and exit."),
) -> None:
    if version:
        rprint(f"render {render.__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        rprint(ctx.get_help())


@app.command()
def ask(
    question: str = typer.Argument(..., help="Scientific question or simulation request."),
    engine: str = typer.Option("", "--engine", "-e", help="Force a specific engine by name."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate only; do not run."),
    save_dir: Path = typer.Option(
        Path(".render_runs"), "--save-dir", help="Directory to save run manifests."
    ),
    no_interpret: bool = typer.Option(False, "--no-interpret", help="Skip interpretation step."),
) -> None:
    """Submit a natural-language simulation question and run it."""
    from render.pipeline import run_question

    console.print(f"[bold]Question:[/bold] {question}")
    with console.status("Mapping to a validated engine and running…"):
        result = run_question(
            question,
            engine=engine or None,
            dry_run=dry_run,
            interpret_result=not no_interpret,
            manifest_dir=save_dir,
        )

    if result.engine_name:
        console.print(
            f"  engine=[cyan]{result.engine_name}[/cyan] "
            f"family={result.engine_family} status={result.engine_status}"
        )

    if result.status == "clarify":
        console.print(f"[yellow]Need more info:[/yellow] {result.message}")
        if result.missing_fields:
            console.print(f"  Missing: {', '.join(result.missing_fields)}")
        raise typer.Exit(0)
    if result.status == "abstain":
        console.print(f"[red]Cannot run:[/red] {result.message}")
        raise typer.Exit(1)
    if result.status == "error":
        console.print(f"[red]{result.message}[/red]")
        raise typer.Exit(1)
    if result.status == "dry_run":
        console.print("[green]Dry-run complete — intent valid.[/green]")
        if result.parameters:
            console.print(f"  parameters: {result.parameters}")
        raise typer.Exit(0)

    # --- Results ---
    if result.quantities:
        table = Table(title="Results")
        table.add_column("Quantity")
        table.add_column("Value", justify="right")
        table.add_column("Unit")
        for q in result.quantities:
            val = f"{q['value']:.6g}" if isinstance(q["value"], (int, float)) else str(q["value"])
            table.add_row(q["name"], val, q.get("unit", ""))
        console.print(table)

    for w in result.warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")

    if result.interpretation:
        badge = result.status_badge or ""
        console.print(f"\n[bold]Interpretation:[/bold] [dim]{badge}[/dim]\n{result.interpretation}")
        if result.assumptions:
            console.print("\n[dim]Assumptions:[/dim]")
            for a in result.assumptions:
                console.print(f"  • {a}")
    if result.confidence is not None:
        console.print(f"\n[dim]Confidence: {result.confidence:.0%}[/dim]")

    console.print(f"\n[dim]Provenance → {result.replay_cmd}[/dim]")


@app.command()
def eval(
    engine: str = typer.Option("", "--engine", "-e", help="Engine to evaluate (all if empty)."),
    json_out: Path | None = typer.Option(None, "--json", help="Write scorecard to JSON file."),
) -> None:
    """Run the reference-case evaluation harness."""
    from render.engines.reference import HarmonicOscillatorAdapter
    from render.eval.runner import eval_engine
    from render.registry import registry

    _register_all_engines(registry)
    if "harmonic_oscillator" not in registry:
        registry.register(HarmonicOscillatorAdapter())

    targets = (
        [registry.get(engine)] if engine else [a for a in registry.list_all() if a.reference_cases]
    )

    if not targets:
        console.print("[yellow]No engines with reference cases registered.[/yellow]")
        raise typer.Exit(0)

    overall_ok = True
    scorecard: list[dict] = []
    for adapter in targets:
        report = eval_engine(adapter)
        status = "[green]PASS[/green]" if report.ok else "[red]FAIL[/red]"
        console.print(
            f"\n[bold]{adapter.name}[/bold] ({adapter.status}) — {status} "
            f"({report.passed}/{report.total})"
        )
        for case in report.cases:
            icon = "✓" if case.passed else "✗"
            color = "green" if case.passed else "red"
            console.print(f"  [{color}]{icon}[/{color}] {case.case_name}")
            for f in case.failures:
                console.print(f"      [red]{f}[/red]")
            for w in case.warnings:
                console.print(f"      [yellow]⚠ {w}[/yellow]")
        if not report.ok:
            overall_ok = False
        scorecard.append(
            {
                "engine": adapter.name,
                "status": adapter.status,
                "ok": report.ok,
                "passed": report.passed,
                "total": report.total,
            }
        )

    if json_out:
        import json

        json_out.write_text(json.dumps(scorecard, indent=2))
        console.print(f"[dim]Scorecard → {json_out}[/dim]")

    raise typer.Exit(0 if overall_ok else 1)


@app.command()
def replay(
    manifest_path: Path = typer.Argument(..., help="Path to a RunManifest JSON file."),
    check_tolerance: float = typer.Option(
        0.01, "--rtol", help="Relative tolerance for comparing replay vs original."
    ),
) -> None:
    """Replay a prior run from its provenance manifest and check reproducibility."""
    from render.engines.reference import HarmonicOscillatorAdapter
    from render.execute.local import run_local
    from render.registry import registry
    from render.types import RunManifest

    _register_all_engines(registry)
    if "harmonic_oscillator" not in registry:
        registry.register(HarmonicOscillatorAdapter())

    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        raise typer.Exit(1)

    original = RunManifest.model_validate_json(manifest_path.read_text())
    console.print(f"[bold]Replaying:[/bold] {original.run_id}")
    console.print(f"  engine={original.engine_name}  timestamp={original.timestamp.isoformat()}")

    try:
        adapter = registry.get(original.engine_name)
    except KeyError:
        console.print(f"[red]Engine '{original.engine_name}' not in registry.[/red]")
        raise typer.Exit(1) from None

    with console.status("Re-running…"):
        replay_manifest = run_local(adapter, original.intent)

    # Compare quantities
    console.print("\n[bold]Comparison:[/bold]")
    all_ok = True
    for orig_q in original.bundle.quantities:
        rep_q = replay_manifest.bundle.get(orig_q.name)
        if rep_q is None:
            console.print(f"  [red]✗ {orig_q.name}: missing in replay[/red]")
            all_ok = False
            continue
        try:
            oval = float(orig_q.value)
            rval = float(rep_q.value)
            denom = abs(oval) if oval != 0 else 1.0
            rel_diff = abs(oval - rval) / denom
            ok = rel_diff <= check_tolerance
            color = "green" if ok else "red"
            icon = "✓" if ok else "✗"
            console.print(
                f"  [{color}]{icon}[/{color}] {orig_q.name}: "
                f"orig={oval:.6g} replay={rval:.6g} "
                f"(Δrel={rel_diff:.2e})"
            )
            if not ok:
                all_ok = False
        except (TypeError, ValueError):
            console.print(f"  [dim]~ {orig_q.name}: non-numeric, skipping[/dim]")

    if all_ok:
        console.print("\n[green]✓ Reproduced within tolerance.[/green]")
    else:
        console.print("\n[red]✗ Some quantities differ beyond tolerance.[/red]")

    raise typer.Exit(0 if all_ok else 1)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the Render web API server."""
    import uvicorn

    uvicorn.run("render.app.main:app", host=host, port=port, reload=reload)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _show_results(manifest) -> None:  # type: ignore[no-untyped-def]
    table = Table(title=f"Results — {manifest.engine_name} ({manifest.engine_status})")
    table.add_column("Quantity", style="bold")
    table.add_column("Value")
    table.add_column("Unit")
    for q in manifest.bundle.quantities:
        table.add_row(q.name, str(q.value), q.unit or "-")
    console.print(table)
    if manifest.validation.warnings:
        for w in manifest.validation.warnings:
            console.print(f"[yellow]⚠ {w}[/yellow]")


def _show_pathway_table(proposal) -> None:  # type: ignore[no-untyped-def]
    table = Table(title=f"Modeling pathways for: {proposal.question[:60]}")
    table.add_column("#", style="dim")
    table.add_column("Engine")
    table.add_column("Fidelity")
    table.add_column("Cost")
    table.add_column("Status")
    for i, p in enumerate(proposal.pathways, 1):
        badge = "✓" if p.status == "certified" else "⚠"
        table.add_row(str(i), p.engine, p.fidelity, p.estimated_cost, f"{badge} {p.status}")
    console.print(table)
    if proposal.recommendation:
        console.print(f"[bold]Recommendation:[/bold] {proposal.recommendation}")


def _register_all_engines(registry) -> None:  # type: ignore[no-untyped-def]
    """Register all available engine adapters via the canonical bootstrap."""
    from render.registry.bootstrap import register_all_engines

    register_all_engines(registry)
