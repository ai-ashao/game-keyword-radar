from __future__ import annotations
import asyncio
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ValidationError
from game_keyword_radar import __version__
from game_keyword_radar.config import Settings
from game_keyword_radar.demo import save_demo
from game_keyword_radar.history import compare_snapshots
from game_keyword_radar.history_v2 import compare_v2
from game_keyword_radar.models import ScanSnapshot, ValidationRecord, utc_now, GameAnnotation, GameEntity
from game_keyword_radar.monitoring import MonitorController
from game_keyword_radar.annotations import apply_annotation
from game_keyword_radar.analyzers.entity_resolution import slugify
from game_keyword_radar.pipeline import Scanner, configured_sources
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.validation import ValidationStore
from game_keyword_radar.sources.base import safe_error

WEB_ROOT=Path(__file__).resolve().parent

def snapshot_payload(snapshot):
    data=snapshot.model_dump(mode='json');data['state']=snapshot.state.value
    return data

class ScanRequest(BaseModel):
    # V1 limit remains <=30. Broad V2 discovery is a separate setting.
    limit:int|None=Field(default=None,ge=1,le=30)
    discovery_limit:int|None=Field(default=None,ge=1,le=100)
    deep:int|None=Field(default=None,ge=0,le=30)
    with_trends:bool|None=None
    selection_profile:Literal["opportunity"]|None=None

class ManualSeed(BaseModel):
    canonical_name: str=Field(min_length=1,max_length=160)
    platform: Literal['steam','twitch']
    platform_id: str=Field(pattern=r'^\d{1,20}$')
    reason: str=Field(min_length=3,max_length=1000)
    evidence_url: str=Field(min_length=8,max_length=2000)


@dataclass
class ScanManager:
    settings:Settings
    running:bool=False
    phase:str='idle'
    message:str='Ready'
    started_at:datetime|None=None
    finished_at:datetime|None=None
    last_run_id:str|None=None
    error:str|None=None
    _task:asyncio.Task|None=field(default=None,repr=False)
    def as_dict(self):
        return {k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in vars(self).items() if k not in {'settings','_task'}}
    def progress(self,phase,message):self.phase=phase;self.message=message
    def start(self,request):
        if self.running:return False
        self.running=True;self.phase='discovery';self.message='正在扫描跨平台游戏需求'
        self.started_at=utc_now();self.finished_at=None;self.error=None
        self._task=asyncio.create_task(self._run(request));return True
    async def _run(self,request):
        try:
            snapshot=await Scanner(self.settings,progress=self.progress).run(**request.model_dump())
            self.last_run_id=snapshot.run_id
            self.phase='complete' if snapshot.entities or snapshot.games else 'failed'
            self.message=f'完成：{len(snapshot.entities)} 个实体；深度入选 {snapshot.selection_summary.get("deep_selected",0)}；可人工验证 {snapshot.selection_summary.get("validation_candidates",0)}' if snapshot.entities else '没有可用候选；上一次有效快照已保留，请查看数据源状态'
        except Exception as exc:
            self.phase='failed';self.message='扫描失败；已保存的快照保持不变';self.error=safe_error(exc)
        finally:
            self.running=False;self.finished_at=utc_now()

def create_app(settings=None):
    resolved=settings or Settings.load()
    store=SnapshotStore(resolved);reporter=MarkdownReporter(resolved);manager=ScanManager(resolved);validations=ValidationStore(resolved)
    monitor=MonitorController(resolved)
    templates=Jinja2Templates(directory=str(WEB_ROOT/'templates'))
    @asynccontextmanager
    async def lifespan(app):
        if resolved.monitoring.enabled:
            monitor.start()
        yield
        await monitor.stop()
        if manager._task and not manager._task.done():
            manager._task.cancel()
            try:await manager._task
            except asyncio.CancelledError:pass
    web=FastAPI(title='Game Keyword Radar',version=__version__,docs_url='/api/docs',redoc_url=None,lifespan=lifespan)
    web.state.settings=resolved;web.state.store=store;web.state.reporter=reporter;web.state.scan_manager=manager;web.state.monitor_controller=monitor
    web.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])
    @web.middleware('http')
    async def local_security(request,call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail':'Cross-origin writes are not allowed on this local workbench'},status_code=403)
            if request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'detail':'Cross-site writes are not allowed'},status_code=403)
            try:
                size=int(request.headers.get('content-length','0'))
            except ValueError:
                return JSONResponse({'detail':'Invalid content length'},status_code=400)
            if size>65536:
                return JSONResponse({'detail':'Request body too large'},status_code=413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
    web.mount('/static',StaticFiles(directory=str(WEB_ROOT/'static')),name='static')
    @web.get('/',response_class=HTMLResponse)
    async def index(request:Request):
        return templates.TemplateResponse(request=request,name='index.html',context={'version':__version__,'country':resolved.country,
            'discovery_limit':resolved.discovery_limit,'deep_limit':resolved.deep_analysis_limit,'trends_enabled':resolved.trends_enabled})
    def get_snapshot(run_id=None):
        snapshot=store.load_snapshot(run_id) if run_id else store.load_latest()
        if snapshot is None:raise HTTPException(404,'Snapshot was not found')
        return snapshot
    def full_payload(snapshot):
        data=snapshot_payload(snapshot)
        data['page_opportunities']=validations.projected_pages(snapshot)
        data['annotations']={k:v.model_dump(mode='json') for k,v in store.load_annotations(is_demo=snapshot.is_demo).items()}
        return data
    @web.get('/api/snapshot')
    async def latest():return full_payload(get_snapshot())
    @web.get('/api/snapshots')
    async def history():return [s.model_dump(mode='json') for s in store.list_snapshots()]
    @web.get('/api/snapshots/{run_id}')
    async def historic(run_id:str):return full_payload(get_snapshot(run_id))
    @web.get('/api/status')
    async def scan_status():return manager.as_dict()
    @web.post('/api/scan',status_code=status.HTTP_202_ACCEPTED)
    async def scan(request:ScanRequest):
        if monitor.running:raise HTTPException(409,'A lightweight observation is running')
        if not manager.start(request):raise HTTPException(409,'A scan is already running')
        return manager.as_dict()
    @web.post('/api/demo')
    async def demo():
        if manager.running or monitor.running:raise HTTPException(409,'A scan or monitoring run is already running')
        snapshot=save_demo(resolved);reporter.save(snapshot)
        return full_payload(snapshot)
    @web.get('/api/sources')
    async def sources():
        latest=store.load_latest()
        last_attempt=None
        try:
            last_attempt=ScanSnapshot.model_validate_json((resolved.data_dir/'last-attempt.json').read_text())
        except (OSError,ValueError):pass
        return {'configuration':configured_sources(resolved),
            'latest_statuses':[s.model_dump(mode='json') for s in (last_attempt or latest).source_statuses] if (last_attempt or latest) else [],
            'is_demo':(last_attempt or latest).is_demo if (last_attempt or latest) else None,
            'last_attempt_run_id':last_attempt.run_id if last_attempt else None,
            'budgets':{'discovery_limit':resolved.discovery_limit,'deep_limit':resolved.deep_analysis_limit,
                'youtube_search_calls_per_scan':resolved.youtube_search_budget,'youtube_search_calls_per_local_day':resolved.youtube_daily_search_budget,
                'reddit_requests_per_scan':resolved.reddit_max_requests},
            'configuration_file':str(resolved.project_root/'radar.toml')}
    @web.get('/api/compare')
    async def compare(current_run_id:str,baseline_run_id:str|None=None):
        current=get_snapshot(current_run_id)
        if baseline_run_id is None:
            candidates=[s for s in store.list_snapshots() if s.generated_at<current.generated_at and
                (s.country,s.language,s.is_demo)==(current.country,current.language,current.is_demo)]
            if not candidates:raise HTTPException(404,'No earlier comparable snapshot exists')
            baseline_run_id=candidates[0].run_id
        if baseline_run_id==current_run_id:raise HTTPException(422,'Current and baseline snapshots must differ')
        baseline=get_snapshot(baseline_run_id)
        result=compare_snapshots(current,baseline).model_dump(mode='json')
        if current.entities and baseline.entities:
            extra=compare_v2(current,baseline)
            extra['v2_removed_game_slugs']=extra.pop('removed_games')
            result.update(extra)
        return result
    @web.get('/api/validation')
    async def queue():
        try:return [r.model_dump(mode='json') for r in validations.list()]
        except ValueError as exc:raise HTTPException(409,str(exc))
    @web.put('/api/validation')
    async def save_validation(record:ValidationRecord):
        snapshot=get_snapshot(record.source_run_id or None)
        page=next((p for p in snapshot.page_opportunities if p.id==record.page_id),None)
        if page is None:raise HTTPException(404,'Page opportunity does not exist in the referenced scan')
        identity=(record.game_slug,record.keyword,record.market,record.language,record.is_demo)
        expected=(page.game_slug,page.primary_keyword_hypothesis,snapshot.country,snapshot.language,snapshot.is_demo)
        if identity!=expected:raise HTTPException(422,'Validation identity/market/demo type must match the referenced page')
        record.source_run_id=snapshot.run_id
        return validations.save(record).model_dump(mode='json')
    @web.get('/api/keywords.csv',response_class=PlainTextResponse)
    async def export_keywords(run_id:str|None=None):
        snapshot=get_snapshot(run_id);buffer=io.StringIO();writer=csv.writer(buffer)
        writer.writerow(['Keyword','Game','Page type','Evidence level','Existing site','Validation status'])
        def safe(v):
            text=str(v or '')
            return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
        for p in validations.projected_pages(snapshot):
            writer.writerow([safe(p[k]) for k in ('primary_keyword_hypothesis','game_slug','page_type','evidence_level','existing_site_fit','validation_status')])
        return PlainTextResponse(buffer.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{snapshot.run_id}-validation-keywords.csv"'})
    @web.get('/api/report',response_class=PlainTextResponse)
    async def report(run_id:str|None=None):
        snapshot=get_snapshot(run_id)
        return PlainTextResponse(reporter.render(snapshot),headers={'Content-Disposition':f'attachment; filename="{snapshot.run_id}-game-keywords.md"'})
    @web.get('/api/policy')
    async def get_policy():
        return {'version':resolved.selection.policy_version,'config_hash':resolved.policy_hash(),
                'policy':resolved.public_policy(),'scope':'local service session; file is not overwritten'}

    @web.put('/api/policy')
    async def update_policy(payload:dict):
        if manager.running or monitor.enabled or monitor.running:
            raise HTTPException(409,'Stop monitoring and wait for scanning before changing policy')
        if set(payload)-set(resolved.public_policy()):
            raise HTTPException(422,'Unknown policy section; credentials cannot be edited here')
        try:
            candidate=Settings.model_validate({**resolved.model_dump(), **{name:{**getattr(resolved,name).model_dump(),**value} for name,value in payload.items()}})
        except (ValueError, TypeError) as exc:
            raise HTTPException(422,str(exc))
        for name in payload:
            setattr(resolved,name,getattr(candidate,name))
            resolved.__pydantic_fields_set__.add(name)
        return await get_policy()

    @web.get('/api/monitoring')
    async def monitor_status():
        return monitor.status()

    @web.post('/api/monitoring/once',status_code=202)
    async def monitor_once():
        if manager.running or not monitor.once():
            raise HTTPException(409,'A scan or monitoring task is already active')
        return monitor.status()

    @web.post('/api/monitoring/start',status_code=202)
    async def monitor_start():
        if manager.running or not monitor.start():
            raise HTTPException(409,'A scan or monitoring task is already active')
        return monitor.status()

    @web.post('/api/monitoring/stop')
    async def monitor_stop():
        await monitor.stop()
        return monitor.status()

    @web.get('/api/candidates')
    async def candidates(lane: str|None=None,run_id: str|None=None):
        snapshot=get_snapshot(run_id)
        if lane is not None and lane not in {'new_release','rising','new_demand','exploration','monitor_only','deferred_budget','excluded'}:
            raise HTTPException(422,'Unknown candidate lane / destination')
        return [d.model_dump(mode='json') for d in snapshot.selection_decisions
                if lane is None or d.primary_lane==lane or d.decision==lane]

    @web.get('/api/explain/{game_slug}')
    async def explain(game_slug:str,run_id:str|None=None):
        snapshot=get_snapshot(run_id)
        row=next((d for d in snapshot.selection_decisions if d.game_slug==game_slug),None)
        if row is None:
            raise HTTPException(404,'No selection record; legacy snapshots are not retrospectively classified')
        return {'run_id':snapshot.run_id,'before_deep':row.model_dump(mode='json'),
                'after_deep':next((g.model_dump(mode='json') for g in snapshot.game_opportunities if g.game_slug==game_slug),None)}

    @web.put('/api/annotations')
    async def save_annotation(record:GameAnnotation):
        if manager.running or monitor.running:
            raise HTTPException(409,'Wait for the current scan before editing entity evidence')
        now=utc_now()
        if record.checked_at>now or record.evidence_published_at and record.evidence_published_at>now or record.research_requested_at and record.research_requested_at>now:
            raise HTTPException(422,'Evidence and requests cannot be dated in the future')
        previous=store.load_annotations(is_demo=record.is_demo).get(record.game_slug)
        # Users cannot forge consumption timestamps to bypass the manual queue.
        record.research_consumed_at=previous.research_consumed_at if previous else None
        entities=store.load_entities() if not record.is_demo else get_snapshot().entities
        target=next((e for e in entities if e.slug==record.game_slug),None)
        if target is None:
            raise HTTPException(404,'Known game required; use the manual seed endpoint first')
        for source,identity in record.platform_ids.items():
            if any(e.slug!=record.game_slug and e.platform_ids.get(source)==identity for e in entities):
                raise HTTPException(409,'Platform ID already belongs to another entity; resolve before merging')
        try:
            store.save_annotation(record)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc))
        return record.model_dump(mode='json')

    @web.post('/api/seeds')
    async def seed(payload:ManualSeed):
        if manager.running or monitor.running:
            raise HTTPException(409,'Wait for scanning to finish')
        try:
            with store.scan_lock():
                entities=store.load_entities()
                target=next((e for e in entities if e.platform_ids.get(payload.platform)==payload.platform_id),None)
                if target is None:
                    base=slugify(payload.canonical_name)
                    slug=base if not any(e.slug==base for e in entities) else base+'-'+payload.platform+'-'+payload.platform_id
                    target=GameEntity(slug=slug,canonical_name=payload.canonical_name,platform_ids={payload.platform:payload.platform_id},
                        discovery_sources=['manual_seed'],first_seen_at=utc_now())
                    entities.append(target)
                record=GameAnnotation(game_slug=target.slug,watch=True,reason=payload.reason,evidence_url=payload.evidence_url,checked_at=utc_now())
                store.save_entities(entities)
                store.save_annotation(record,locked=True)
        except (ValueError,RuntimeError) as exc:
            raise HTTPException(422 if isinstance(exc,ValueError) else 409,str(exc))
        return {'entity':target.model_dump(mode='json'),'annotation':record.model_dump(mode='json'),'note':'人工种子，仅保存标识与证据；未请求任意证据URL，也未自动验证发行信息'}

    @web.get('/health')
    async def health():return {'status':'ok','version':__version__}
    return web

app=create_app()
