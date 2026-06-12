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
    console.print("[yellow]⚙ Eval harness not yet implemented (Phase 0.8)[/yellow]")


@app.command()
def replay(
    manifest: str = typer.Argument(..., help="Path to a RunManifest JSON file."),
) -> None:
    """Replay a prior run from its provenance manifest."""
    console.print(f"[bold]Replaying:[/bold] {manifest}")
    console.print("[yellow]⚙ Replay not yet implemented (Phase 0.5)[/yellow]")
