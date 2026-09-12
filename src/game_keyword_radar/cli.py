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
from game_keyword_radar.validation_io import SearchEvidenceStore, export_validation_pack
from game_keyword_radar.sources.sitemap import SitemapScanner
from game_keyword_radar.sources.youtube import YouTubeProvider
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.history import compare_snapshots
from game_keyword_radar.history_v2 import compare_v2
from game_keyword_radar.provider_state import BestEffortCircuitBreaker
from game_keyword_radar.discovery_inbox import DiscoveryInbox
from game_keyword_radar.sources.trends_rss import fetch_trending_rss

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
    """Run bounded discovery and Deep enrichment. Optional providers degrade instead of blocking."""
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
    """Configuration readiness only; best-effort readiness is reported separately."""
    rows=configured_sources(Settings.load())
    for row in rows:
        status=row['status']
        if row['source']=='youtube' and status=='unavailable' and YouTubeProvider.public_available():
            status='best_effort_ready'
        typer.echo(f'{row["source"]:10} {status}')
    typer.echo(f'{"sitemap":10} ready_no_key')
    typer.echo(f'{"youtube-public":10} '+('best_effort_ready' if YouTubeProvider.public_available() else 'optional_dependency_missing'))

@app.command()
def validate():
    """Inspect the persisted manual validation queue; edit it in the Dashboard."""
    rows=ValidationStore(Settings.load()).list()
    typer.echo(json.dumps([r.model_dump(mode='json') for r in rows],ensure_ascii=False,indent=2))

@app.command('export-validation')
def export_validation(output:Path=typer.Option(Path('reports/validation-pack.csv')),run_id:str|None=typer.Option(None)):
    """Export candidate/page research material for Semrush/Trends/SERP validation."""
    settings=Settings.load();store=SnapshotStore(settings)
    snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None: raise typer.BadParameter('Snapshot not found')
    path=output if output.is_absolute() else settings.project_root/output
    typer.echo(str(export_validation_pack(snapshot,path)))

@app.command('import-semrush')
def import_semrush(path:Path=typer.Argument(...),market:str|None=typer.Option(None),language:str|None=typer.Option(None)):
    """Append Semrush CSV evidence. Missing fields stay null; repeated imports are deduplicated."""
    settings=Settings.load();source=path if path.is_absolute() else settings.project_root/path
    if not source.is_file(): raise typer.BadParameter('CSV file not found')
    result=SearchEvidenceStore(settings.data_dir).import_semrush(source,market=market or settings.country,language=language or settings.language)
    typer.echo(json.dumps(result,ensure_ascii=False,indent=2))

@app.command('import-trends')
def import_trends(path:Path=typer.Argument(...),geo:str|None=typer.Option(None),timeframe:str|None=typer.Option(None),search_type:str=typer.Option('web')):
    """Append Google Trends Explore CSV as relative evidence; never converts it to search volume."""
    settings=Settings.load();source=path if path.is_absolute() else settings.project_root/path
    if not source.is_file(): raise typer.BadParameter('CSV file not found')
    result=SearchEvidenceStore(settings.data_dir).import_trends(source,geo=geo or settings.trends_geo,timeframe=timeframe or settings.trends_timeframe,search_type=search_type)
    typer.echo(json.dumps(result,ensure_ascii=False,indent=2))

@app.command('sitemap-scan')
def sitemap_scan(url:list[str]=typer.Option(...,'--url'),source_id:list[str]=typer.Option([], '--source-id'),max_entries:int=typer.Option(5000,min=1,max=50000)):
    """Read public Sitemaps incrementally. First run establishes baseline and emits zero new events."""
    settings=Settings.load()
    if source_id and len(source_id)!=len(url): raise typer.BadParameter('--source-id count must match --url count')
    ids=source_id or [f'sitemap-{i+1}' for i in range(len(url))]
    async def run():
        scanner=SitemapScanner(settings.data_dir,timeout=settings.request_timeout,max_entries=max_entries)
        try:
            return [await scanner.scan(sid,u) for sid,u in zip(ids,url)]
        finally:
            await scanner.close()
    rows=asyncio.run(run())
    inbox=DiscoveryInbox(settings.data_dir)
    inbox_result=inbox.append_many([{"source":"sitemap", **entry} for result in rows for entry in result.new_entries])
    typer.echo(json.dumps({"scans":[r.__dict__ for r in rows],"inbox":inbox_result},ensure_ascii=False,indent=2))

@app.command('trends-rss')
def trends_rss(geo:str|None=typer.Option(None),limit:int=typer.Option(50,min=1,max=200)):
    """Fetch Google Trends Trending RSS and append topic hints to the discovery inbox."""
    settings=Settings.load();region=geo or settings.trends_geo
    try:
        rows=asyncio.run(fetch_trending_rss(geo=region,timeout=settings.request_timeout))[:limit]
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        typer.echo(f'Trends RSS failed: {safe_error(exc)}',err=True);raise typer.Exit(1)
    result=DiscoveryInbox(settings.data_dir).append_many(rows)
    typer.echo(json.dumps({"region":region,"topics":rows,"inbox":result},ensure_ascii=False,indent=2))

@app.command('discovery-inbox')
def discovery_inbox(limit:int=typer.Option(100,min=1,max=1000)):
    """Inspect unresolved low-cost discovery hints; these are not auto-merged GameEntity facts."""
    settings=Settings.load();rows=DiscoveryInbox(settings.data_dir).list(limit)
    typer.echo(json.dumps(rows,ensure_ascii=False,indent=2))

@app.command('provider-state')
def provider_state(name:str=typer.Argument(...)):
    """Inspect a best-effort provider's local circuit-breaker state."""
    settings=Settings.load();typer.echo(json.dumps(BestEffortCircuitBreaker(settings.data_dir,name).state(),ensure_ascii=False,indent=2))

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
    """Run cheap Steam/Twitch observation only. Best-effort deep sources are not called."""
    settings=Settings.load()
    try:
        snapshot=asyncio.run(Scanner(settings,progress=lambda _,msg:typer.echo(msg)).monitor_once())
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        typer.echo(safe_error(exc),err=True);raise typer.Exit(1)
    typer.echo(f'Monitoring saved: {snapshot.run_id}; independent full report preserved')

@app.command()
def candidates(lane:str|None=typer.Option(None),run_id:str|None=typer.Option(None)):
    """Inspect saved lane decisions, including deferred and monitor-only rows."""
    store=SnapshotStore(Settings.load());snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None:raise typer.BadParameter('Snapshot not found')
    if lane not in {None,'new_release','rising','new_demand','exploration','monitor_only','deferred_budget','excluded'}:
        raise typer.BadParameter('Unknown lane or destination')
    rows=[d.model_dump(mode='json') for d in snapshot.selection_decisions if lane is None or d.primary_lane==lane or d.decision==lane]
    typer.echo(json.dumps(rows,ensure_ascii=False,indent=2))

@app.command()
def explain(game_slug:str,run_id:str|None=typer.Option(None)):
    """Replay the stored pre-deep reason, not today's reinterpretation."""
    store=SnapshotStore(Settings.load());snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
    if snapshot is None:raise typer.BadParameter('Snapshot not found')
    decision=next((d for d in snapshot.selection_decisions if d.game_slug==game_slug),None)
    if decision is None:raise typer.BadParameter('No decision recorded; old snapshots stay unclassified')
    typer.echo(decision.model_dump_json(indent=2))
