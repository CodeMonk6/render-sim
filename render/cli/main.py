import typer
from rich import print as rprint
from rich.console import Console

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
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate only; do not run."),
) -> None:
    """Submit a natural-language simulation question."""
    console.print(f"[bold]Question:[/bold] {question}")
    console.print("[yellow]⚙ Intent parsing not yet implemented (Phase 0.6)[/yellow]")


@app.command()
def eval(
    engine: str = typer.Option("", "--engine", "-e", help="Engine to evaluate (all if empty)."),
) -> None:
    """Run the reference-case evaluation harness."""
    from render.engines.reference import HarmonicOscillatorAdapter
    from render.eval.runner import eval_engine
    from render.registry import registry

    if not registry:
        registry.register(HarmonicOscillatorAdapter())

    targets = (
        [registry.get(engine)] if engine else [a for a in registry.list_all() if a.reference_cases]
    )

    if not targets:
        console.print("[yellow]No engines with reference cases registered.[/yellow]")
        raise typer.Exit(0)

    overall_ok = True
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

    raise typer.Exit(0 if overall_ok else 1)


@app.command()
def replay(
    manifest: str = typer.Argument(..., help="Path to a RunManifest JSON file."),
) -> None:
    """Replay a prior run from its provenance manifest."""
    console.print(f"[bold]Replaying:[/bold] {manifest}")
    console.print("[yellow]⚙ Replay not yet implemented (Phase 0.5)[/yellow]")
