from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.storage import SnapshotStore


app = typer.Typer(
    no_args_is_help=True,
    help="Local dashboard for traceable game keyword opportunity research.",
)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address. Keep the default for local use."),
    port: int = typer.Option(3000, min=1, max=65535),
) -> None:
    """Start the local Dashboard."""
    import uvicorn

    uvicorn.run("game_keyword_radar.web.app:app", host=host, port=port, reload=False)


@app.command()
def scan(
    limit: int = typer.Option(10, min=1, max=30),
    with_trends: bool = typer.Option(False, help="Use the optional unofficial Trends provider."),
) -> None:
    """Run a Steam scan and write JSON plus Markdown outputs."""
    snapshot = asyncio.run(Scanner(Settings()).run(limit=limit, with_trends=with_trends))
    typer.echo(
        f"{snapshot.state.value}: {len(snapshot.games)} games, "
        f"{len(snapshot.opportunities)} opportunities, run {snapshot.run_id}"
    )


@app.command()
def demo() -> None:
    """Write a clearly-labelled fixture snapshot for exploring the Dashboard."""
    settings = Settings()
    snapshot = build_demo_snapshot(settings)
    SnapshotStore(settings).save_snapshot(snapshot)
    path = MarkdownReporter(settings).save(snapshot)
    typer.echo(f"Demo snapshot ready. Report: {path}")


@app.command()
def report(output: Path | None = typer.Option(None, help="Optional output path.")) -> None:
    """Regenerate Markdown from the latest snapshot."""
    settings = Settings()
    snapshot = SnapshotStore(settings).load_latest()
    if snapshot is None:
        raise typer.BadParameter("No snapshot exists. Run `game-radar demo` or `game-radar scan` first.")
    reporter = MarkdownReporter(settings)
    content = reporter.render(snapshot)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        typer.echo(str(output))
    else:
        typer.echo(str(reporter.save(snapshot)))
