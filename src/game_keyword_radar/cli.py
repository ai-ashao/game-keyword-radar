from __future__ import annotations
import asyncio
import json
from pathlib import Path
import typer
from game_keyword_radar.config import Settings
from game_keyword_radar.demo import save_demo
from game_keyword_radar.pipeline import Scanner, configured_sources
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.validation import ValidationStore
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.history import compare_snapshots
from game_keyword_radar.history_v2 import compare_v2

app=typer.Typer(no_args_is_help=True,help='Local game demand / keyword research workbench. Dashboard is the primary interface.')
@app.command()
def serve(host:str=typer.Option('127.0.0.1'),port:int=typer.Option(3000,min=1,max=65535)):
    """Start the local Dashboard (loopback only; no authentication system)."""
    if host not in {'127.0.0.1','localhost','::1'}:raise typer.BadParameter('Local workbench has no login; bind to loopback only')
    import uvicorn
    uvicorn.run('game_keyword_radar.web.app:app',host=host,port=port,reload=False)
@app.command()
def scan(limit:int|None=typer.Option(None,min=1,max=30),deep:int|None=typer.Option(None,min=0,max=30),
         discovery_limit:int|None=typer.Option(None,min=1,max=100),with_trends:bool|None=typer.Option(None,'--with-trends/--without-trends'), selection_profile:str=typer.Option('opportunity')):
    """Run bounded Steam+Twitch discovery and optional deep enrichment."""
    settings=Settings.load()
    try:
        snapshot=asyncio.run(Scanner(settings,progress=lambda _,msg:typer.echo(msg)).run(limit=limit,deep=deep,discovery_limit=discovery_limit,with_trends=with_trends,selection_profile=selection_profile))
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        typer.echo(f'Scan failed: {safe_error(exc)}',err=True);raise typer.Exit(1)
    typer.echo(f'{snapshot.state.value}: {len(snapshot.entities)} games, {len(snapshot.page_opportunities)} page hypotheses, run {snapshot.run_id}')
    if not snapshot.entities:raise typer.Exit(2)
@app.command()
def demo():
    """Write explicitly synthetic fixture data; never overwrite the live default."""
    settings=Settings.load();snapshot=save_demo(settings)
    typer.echo(f'DEMO fixture: {snapshot.run_id}; report {MarkdownReporter(settings).save(snapshot)}')
@app.command()
def report(output:Path|None=typer.Option(None),run_id:str|None=typer.Option(None)):
    settings=Settings.load();store=SnapshotStore(settings)
    snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None:raise typer.BadParameter('No snapshot exists. Use the Dashboard or run game-radar demo first.')
    reporter=MarkdownReporter(settings)
    if output:
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(reporter.render(snapshot),encoding='utf-8');typer.echo(str(output))
    else:typer.echo(str(reporter.save(snapshot)))
@app.command()
def sources():
    """Configuration readiness only, never a claim of live API verification."""
    for row in configured_sources(Settings.load()):typer.echo(f'{row["source"]:10} {row["status"]}')
@app.command()
def validate():
    """Inspect the persisted manual validation queue; edit it in the Dashboard."""
    rows=ValidationStore(Settings.load()).list()
    typer.echo(json.dumps([r.model_dump(mode='json') for r in rows],ensure_ascii=False,indent=2))
@app.command()
def compare(current:str=typer.Argument(...),baseline:str=typer.Argument(...)):
    store=SnapshotStore(Settings.load());a=store.load_snapshot(current);b=store.load_snapshot(baseline)
    if a is None or b is None:raise typer.BadParameter('Snapshot not found')
    if current==baseline:raise typer.BadParameter('Choose distinct snapshots')
    result=compare_snapshots(a,b).model_dump(mode='json')
    if a.entities and b.entities:
        extra=compare_v2(a,b);extra['v2_removed_game_slugs']=extra.pop('removed_games');result.update(extra)
    typer.echo(json.dumps(result,ensure_ascii=False,indent=2))


@app.command('monitor-once')
def monitor_once():
    """Run bounded Steam/Twitch observation only. Does not replace the full report."""
    settings=Settings.load()
    try:
        snapshot=asyncio.run(Scanner(settings,progress=lambda _,msg:typer.echo(msg)).monitor_once())
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        typer.echo(safe_error(exc),err=True)
        raise typer.Exit(1)
    typer.echo(f'Monitoring saved: {snapshot.run_id}; independent full report preserved')

@app.command()
def candidates(lane:str|None=typer.Option(None),run_id:str|None=typer.Option(None)):
    """Inspect saved lane decisions, including deferred and monitor-only rows."""
    store=SnapshotStore(Settings.load())
    snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None:raise typer.BadParameter('Snapshot not found')
    if lane not in {None,'new_release','rising','new_demand','exploration','monitor_only','deferred_budget','excluded'}:
        raise typer.BadParameter('Unknown lane or destination')
    rows=[d.model_dump(mode='json') for d in snapshot.selection_decisions if lane is None or d.primary_lane==lane or d.decision==lane]
    typer.echo(json.dumps(rows,ensure_ascii=False,indent=2))

@app.command()
def explain(game_slug:str,run_id:str|None=typer.Option(None)):
    """Replay the stored pre-deep reason, not today's reinterpretation."""
    store=SnapshotStore(Settings.load())
    snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None:raise typer.BadParameter('Snapshot not found')
    decision=next((d for d in snapshot.selection_decisions if d.game_slug==game_slug),None)
    if decision is None:raise typer.BadParameter('No decision recorded; old snapshots stay unclassified')
    typer.echo(decision.model_dump_json(indent=2))
