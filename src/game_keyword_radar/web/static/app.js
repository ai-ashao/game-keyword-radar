'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url = value => {try {const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:'#';}catch{return '#';}};
const fmt = value => value === null || value === undefined ? '—' : new Intl.NumberFormat('en-US',{maximumFractionDigits:1}).format(value);
const date = value => value ? new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const percent = value => value === null || value === undefined ? '无可比样本' : `${value>0?'+':''}${fmt(value)}%`;
const labels={steam:'Steam',twitch:'Twitch',youtube:'YouTube',reddit:'Reddit',trends:'Trends'};
const statuses={ok:'已获取',partial:'部分样本',failed:'获取失败',unavailable:'不可用',skipped:'未采集',insufficient_data:'数据不足',budget_exhausted:'预算用完',stale:'已过期',ready_not_tested:'配置就绪 · 未实测'};
const actions={WATCH:'继续观察',VALIDATE:'进入验证',EXPAND_EXISTING_SITE:'优先扩展已有站',VALIDATE_NEW_SITE:'研究独立站',SKIP:'暂不研究'};
const stages={pending_semrush:'待 Semrush',pending_serp:'待 SERP',validated:'人工验证完成',skip:'已忽略',needs_validation:'尚未进入队列'};
const level={observed_question:'真实问题证据',observed_content_proxy:'答案型视频证据',hypothesis:'仅玩法推测'};
const state={snapshot:null,history:[],queue:[],sources:null,view:'overview',filter:'all',query:'',selectedGame:null,editing:null,more:12,scanning:false};
let toastTimer, pollTimer;
async function api(path,options={}) {
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{};throw new Error(Array.isArray(detail)?detail.map(x=>x.msg).join('\n'):typeof detail==='string'?detail:`请求失败 (${response.status})`);}
  return response.json();
}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,7000);}
function empty(text){return `<div class="no-results">${esc(text)}</div>`;}
function badge(status){return `<span class="pill ${status==='ok'?'good':['partial','unavailable','insufficient_data','budget_exhausted'].includes(status)?'amber':''}">${esc(statuses[status]||status)}</span>`;}
function sameScope(record){const s=state.snapshot;return s && record.market===s.country && record.language===s.language && record.is_demo===s.is_demo;}
function signalFor(slug,source){return state.snapshot?.platform_signals.find(s=>s.game_slug===slug&&s.source===source);}
function gameFor(slug){return state.snapshot?.entities.find(e=>e.slug===slug);}
function pagesFor(slug){return state.snapshot?.page_opportunities.filter(p=>p.game_slug===slug)||[];}
function showView(view,focus=false){
  state.view=view;
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==`${view}-view`);
  document.querySelectorAll('.nav').forEach(el=>{el.classList.toggle('active',el.dataset.view===view);if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('view-name').textContent={overview:'今日机会',pages:'页面机会图谱',queue:'验证队列',history:'历史变化',sources:'数据源与预算',detail:'游戏详情'}[view];
  if(view==='pages')renderPages();if(view==='queue')renderQueue();if(view==='history')renderHistory();if(view==='sources')renderSources();
  if(focus)window.scrollTo({top:0,behavior:'smooth'});
}
function applySnapshot(snapshot){
  snapshot.entities ||= [];snapshot.platform_signals ||= [];snapshot.question_clusters ||= [];snapshot.page_opportunities ||= [];snapshot.game_opportunities ||= [];
  state.snapshot=snapshot;
  $('data-mode').textContent=snapshot.is_demo?'DEMO · 合成示例':'LIVE · 实际扫描';
  $('data-mode').className=`pill ${snapshot.is_demo?'amber':'good'}`;
  $('demo-notice').hidden=!snapshot.is_demo;
  $('legacy-notice').hidden=snapshot.schema_version===2||snapshot.schema_version==='2';
  $('snapshot-time').textContent=`${date(snapshot.generated_at)} · ${snapshot.country} · ${snapshot.language} · ${snapshot.run_id}`;
  $('download-report').href=`/api/report?run_id=${encodeURIComponent(snapshot.run_id)}`;$('download-report').setAttribute('aria-disabled','false');
  $('export-csv').href=`/api/keywords.csv?run_id=${encodeURIComponent(snapshot.run_id)}`;$('export-csv').setAttribute('aria-disabled','false');
  renderOverview();renderPages();renderQueue();
  if(state.selectedGame&&gameFor(state.selectedGame))renderDetail(state.selectedGame);
}
function renderOverview(){
  const s=state.snapshot;
  if(!s){$('summary').innerHTML='';$('games').innerHTML='';$('empty').hidden=false;return;}
  const pages=s.page_opportunities,opps=s.game_opportunities;
  $('summary').innerHTML=[['游戏候选',s.entities.length||s.games.length,'跨平台实体去重后'],['证据触发页面',pages.filter(p=>p.evidence_level!=='hypothesis').length,'不含纯玩法猜测'],['有上升证据',opps.filter(g=>g.demand.rising_sources.length>=2).length,'至少两个平台方向上升'],['待人工验证',state.queue.filter(r=>sameScope(r)&&['pending_semrush','pending_serp'].includes(r.stage)).length,'尚未作出 Build 决策']].map(([name,value,sub])=>`<div class="summary-tile"><span>${name}</span><strong>${fmt(value)}</strong><small>${sub}</small></div>`).join('');
  if(!s.entities.length&&s.games.length){$('empty').hidden=true;$('games').innerHTML=s.games.map(g=>`<div class="legacy-item"><h3>${esc(g.name)}</h3><p>V1 Steam signal ${fmt(g.game_signal_score)} · 当前在线 ${fmt(g.current_players)}</p><p>仅旧版 Steam 记录，不能伪装成跨平台 Demand。</p></div>`).join('');return;}
  let filtered=opps.filter(g=>{
    const entity=gameFor(g.game_slug),pg=pagesFor(g.game_slug);
    if(state.query&&!`${entity.canonical_name} ${pg.map(p=>p.primary_keyword_hypothesis).join(' ')}`.toLowerCase().includes(state.query.toLowerCase()))return false;
    if(state.filter==='rising')return g.demand.rising_sources.length>=2;
    if(state.filter==='observed')return pg.some(p=>p.evidence_level!=='hypothesis');
    if(state.filter==='existing')return g.action==='EXPAND_EXISTING_SITE';
    if(state.filter==='watch')return g.action==='WATCH';
    return true;
  });
  $('empty').hidden=opps.length>0;
  $('games').innerHTML=filtered.length?filtered.slice(0,state.more).map(g=>{
    const entity=gameFor(g.game_slug),pg=pagesFor(g.game_slug);
    return `<article class="game-card"><div class="card-top"><div class="game-title"><div class="game-avatar" aria-hidden="true">${esc(entity.canonical_name[0])}</div><div><h3>${esc(entity.canonical_name)}</h3><small>${esc(entity.genres.slice(0,3).join(' / ')||'玩法仍待确认')}</small></div></div><span class="rank">#${g.rank}</span></div><div class="card-metrics"><div><label>DEMAND</label><strong>${fmt(g.demand.score)}</strong><small>${esc(g.demand.confidence)} confidence</small></div><div><label>可用证据覆盖</label><strong>${Math.round(g.demand.coverage*100)}<small>%</small></strong><small>${g.demand.available_sources.length}/5 个平台</small></div><div><label>页面假设</label><strong>${pg.length}</strong><small>${pg.filter(p=>p.evidence_level!=='hypothesis').length} 个有问题/内容证据</small></div></div><div class="signal-row">${Object.keys(labels).map(source=>{const sig=signalFor(g.game_slug,source);const rising=g.demand.rising_sources.includes(source);return `<span class="signal-chip ${esc(sig?.status||'')}" title="${esc(statuses[sig?.status]||'未获取')}">${labels[source]} ${rising?'↑':sig?.status==='ok'?'✓':['partial'].includes(sig?.status)?'◐':'—'}</span>`;}).join('')}</div><div class="card-bottom"><span class="action">${actions[g.action]}</span><button class="button subtle" data-game="${esc(g.game_slug)}">查看机会 →</button></div></article>`;
  }).join('')+(filtered.length>state.more?`<button id="show-more" class="button subtle">继续查看 ${filtered.length-state.more} 个候选</button>`:''):opps.length?empty('当前筛选没有结果。未达到筛选条件，不代表所有游戏都没有需求。'):'';
}
function pageCard(p,includeGame=false){
  const record=state.queue.find(r=>sameScope(r)&&r.page_id===p.id);
  return `<article class="page-card"><div class="page-top"><div>${includeGame?`<p>${esc(gameFor(p.game_slug)?.canonical_name||p.game_slug)}</p>`:''}<h3>${esc(p.primary_keyword_hypothesis)}</h3><span class="code">${esc(p.path)}</span></div><span class="page-score">${fmt(p.score)}<small> / 69</small></span></div><div class="page-meta"><span class="pill ${p.evidence_level==='hypothesis'?'amber':'good'}">${esc(level[p.evidence_level]||p.evidence_level)}</span><span>${esc(p.page_type)}</span><span>开发 ${esc(p.build_difficulty)}</span><span>维护 ${esc(p.maintenance_level)}</span><span>原始研究分 ${fmt(p.raw_score)}</span></div><p>${esc(p.page_value)}</p>${p.existing_site_fit?`<p><strong>优先承接：${esc(p.existing_site_fit)}</strong> · 扩页前仍需验证</p>`:''}<details><summary>WHY THIS PAGE EXISTS · ${p.trigger_signals.length} 条触发依据</summary>${p.trigger_signals.map(e=>`<div class="evidence">${e.url?`<a href="${esc(url(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a>`:esc(e.title)}<small>${esc(e.source)} · ${date(e.captured_at)} ${e.is_inference?'· 规则推测，并非搜索事实':''}</small></div>`).join('')}<div class="evidence"><strong>评分拆分</strong><pre>${esc(JSON.stringify(p.score_breakdown,null,2))}</pre></div></details><div class="page-actions"><button class="button ${record?'subtle':'primary'}" data-validate="${esc(p.id)}">${record?'编辑验证记录':'加入验证队列'}</button><span class="pill">${esc(stages[record?.stage||'needs_validation'])}</span></div></article>`;
}
function renderPages(){const s=state.snapshot;$('all-pages').innerHTML=s?.page_opportunities.length?s.page_opportunities.map(p=>pageCard(p,true)).join(''):empty('还没有 V2 页面机会。先扫描或加载示例。');}
function renderDetail(slug){
  const entity=gameFor(slug);if(!entity)return;
  state.selectedGame=slug;const g=state.snapshot.game_opportunities.find(g=>g.game_slug===slug);
  const clusters=state.snapshot.question_clusters.filter(c=>c.game_slug===slug);
  const cards=Object.keys(labels).map(source=>{
    const s=signalFor(slug,source);if(!s)return `<div class="platform-card"><h3>${labels[source]}</h3><p>缺失</p></div>`;
    const metrics=s.metrics,key={steam:'current_players',twitch:'total_viewers',youtube:'recent_guide_video_count',reddit:'question_count',trends:'recent_interest'}[source];
    const metricLabel={steam:'当前在线（瞬时）',twitch:metrics.sampling_complete?'观众（本次观测）':'观众（样本下限）',youtube:'攻略类视频（样本）',reddit:'问题标题（样本）',trends:'近期相对兴趣'}[source];
    return `<div class="platform-card"><h3>${labels[source]}</h3>${badge(s.status)}<strong>${fmt(metrics[key])}</strong><p>${metricLabel}</p><p>24h：${percent(s.history?.['24h']?.primary_percent)}<br>7d：${percent(s.history?.['7d']?.primary_percent)}</p><p>${date(s.captured_at)}<br>${esc(s.market)} · ${esc(s.confidence)}${s.cache_hit?' · 缓存':''}</p><details><summary>原始指标与限制</summary><pre>${esc(JSON.stringify(metrics,null,2))}</pre>${s.notes.map(n=>`<p>${esc(n)}</p>`).join('')}${s.history?.previous?`<p>相对前次观测（${fmt(s.history.previous.elapsed_hours)}h）：${percent(s.history.previous.primary_percent)}</p>`:''}</details></div>`;
  }).join('');
  $('game-detail').innerHTML=`<div class="detail-heading"><div><div class="eyebrow">GAME OPPORTUNITY / ${esc(actions[g?.action]||'继续观察')}</div><h1>${esc(entity.canonical_name)}</h1><p>${esc(g?.action_reason||'')}</p></div><div class="detail-score"><div><label>DEMAND</label><strong>${fmt(g?.demand.score)}</strong></div><div><label>证据覆盖</label><strong>${Math.round((g?.demand.coverage||0)*100)}%</strong></div></div></div><p class="footnote">实体匹配：${esc(entity.match_method)} · confidence ${fmt(entity.entity_match_confidence)} · ${esc(Object.entries(entity.platform_ids).map(([k,v])=>`${k}: ${v}`).join(' / '))}</p><div class="platform-grid">${cards}</div><div class="section-heading"><div><h2>玩家在找什么？</h2><p>问题计数是样本标题数；重复主题不等于相同关键词搜索次数。</p></div></div><div class="question-clusters">${clusters.map(c=>`<div class="cluster"><h3>${esc(c.cluster_name)}</h3><p>${c.question_count} 条相关标题 · ${c.source_count} 类来源 · ${esc(c.confidence)}</p>${c.examples.slice(0,3).map(e=>`<div class="evidence">${esc(e.title)}</div>`).join('')}</div>`).join('')||empty('尚未采集到明确的问题证据。')}</div><div class="section-heading"><div><h2>Page Graph</h2><p>页面研究分上限 69；未经人工检查不能视为 Build。</p></div></div>${pagesFor(slug).map(p=>pageCard(p)).join('')||empty('当前证据不足以触发页面节点。')}`;
}
function renderQueue(){
  $('queue-count').textContent=state.queue.filter(r=>!r.is_demo&&['pending_semrush','pending_serp'].includes(r.stage)).length;
  const filter=$('queue-filter').value;
  const list=state.queue.filter(r=>filter==='all'||r.stage===filter);
  $('queue-list').innerHTML=list.map(r=>`<article class="panel queue-card"><div><h3>${esc(r.keyword)}</h3><span class="pill ${r.is_demo?'amber':''}">${r.is_demo?'DEMO':'LIVE'} · ${esc(r.market)}</span> <span class="pill">${esc(stages[r.stage])}</span><p>${r.semrush_volume===null?'未填写搜索量':`Semrush ${fmt(r.semrush_volume)} / 月`} · ${date(r.updated_at)}</p>${r.decision_reason?`<p>${esc(r.decision_reason)}</p>`:''}</div><button class="button subtle" data-edit-record="${esc(r.page_id)}" data-record-scope="${esc(`${r.market}:${r.language}:${r.is_demo}`)}">编辑记录</button></article>`).join('')||empty('验证队列为空。打开游戏详情，在页面节点下点击“加入验证队列”。');
}
async function addQueue(id){
  const page=state.snapshot.page_opportunities.find(p=>p.id===id);if(!page)return;
  let record=state.queue.find(r=>sameScope(r)&&r.page_id===id);
  if(!record){record=await api('/api/validation',{method:'PUT',body:JSON.stringify({page_id:page.id,game_slug:page.game_slug,keyword:page.primary_keyword_hypothesis,market:state.snapshot.country,language:state.snapshot.language,is_demo:state.snapshot.is_demo,source_run_id:state.snapshot.run_id})});state.queue=await api('/api/validation');renderQueue();renderPages();renderOverview();if(state.selectedGame)renderDetail(state.selectedGame);toast('已加入待 Semrush 队列；也可现在填写验证记录。');}
  openValidation(record);
}
function localDate(value){if(!value)return '';const d=new Date(value);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
function openValidation(record){
  state.editing=record;$('validation-keyword').textContent=`${record.keyword} · ${record.market} ${record.is_demo?'· DEMO':''}`;
  const f=$('validation-form');f.reset();$('validation-error').hidden=true;
  for(const k of ['stage','decision','semrush_volume','semrush_kd','semrush_evidence','serp_notes','decision_reason'])f.elements[k].value=record[k]??'';
  for(const k of ['semrush_checked_at','serp_checked_at'])f.elements[k].value=localDate(record[k]);
  f.elements.serp_urls.value=(record.serp_urls||[]).join('\n');$('validation-dialog').showModal();
}
function renderHistory(){
  const selects=[$('current-snapshot'),$('baseline-snapshot')];const previous=selects.map(s=>s.value);
  selects.forEach(s=>s.innerHTML=state.history.map(h=>`<option value="${esc(h.run_id)}">${esc(h.run_id)} · ${h.is_demo?'DEMO':'LIVE'} · ${esc(h.country)}</option>`).join(''));
  selects[0].value=state.snapshot?.run_id||previous[0]||state.history[0]?.run_id||'';
  selects[1].value=previous[1]||state.history.find(h=>h.run_id!==selects[0].value)?.run_id||'';
  $('history-list').innerHTML=state.history.length?`<div class="table-wrap"><table><thead><tr><th>时间 / Run</th><th>市场</th><th>数据类型</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.history.map(h=>`<tr><td>${date(h.generated_at)}<br><span class="code">${esc(h.run_id)}</span></td><td>${esc(h.country)}</td><td>${h.is_demo?'DEMO':'LIVE'}</td><td>${badge(h.state)}</td><td><button class="button subtle" data-load-snapshot="${esc(h.run_id)}">查看快照</button></td></tr>`).join('')}</tbody></table></div>`:empty('还没有历史快照。');
}
async function compare(){
  const a=$('current-snapshot').value,b=$('baseline-snapshot').value;
  if(!a||!b||a===b){toast('请选择两个不同的快照。');return;}
  $('compare').disabled=true;
  try{
    const result=await api(`/api/compare?current_run_id=${encodeURIComponent(a)}&baseline_run_id=${encodeURIComponent(b)}`);
    const platforms=result.platform_changes||[];
    const gameRows=(result.v2_game_changes||[]).map(g=>`<tr><td>${esc(g.game_slug)}</td><td>${g.rank_change===null?'—':`${g.rank_change>0?'+':''}${g.rank_change}`}</td><td>${g.demand_score_change===null?'—':`${g.demand_score_change>0?'+':''}${fmt(g.demand_score_change)}`}</td><td>${g.score_comparable?'来源一致':'来源变化 / 新游戏，不直接解释分数涨跌'}</td></tr>`).join('');
    $('comparison').innerHTML=`<div class="notice ${result.comparable?'':'amber'}">${esc(result.note)}</div>${gameRows?`<div class="table-wrap"><table><thead><tr><th>游戏</th><th>排名上升</th><th>Demand 分差</th><th>可比性</th></tr></thead><tbody>${gameRows}</tbody></table></div>`:''}<div class="summary-grid">${[['新增页面',result.new_page_opportunities?.length??result.new_opportunities],['移出本次样本',result.removed_page_opportunities?.length??result.removed_opportunities],['可比平台观测',platforms.length],['游戏分数变化',result.v2_game_changes?.length??result.changed_games]].map(([k,v])=>`<div class="summary-tile"><span>${k}</span><strong>${fmt(v)}</strong></div>`).join('')}</div>${platforms.length?`<div class="table-wrap"><table><thead><tr><th>游戏 / 平台</th><th>观测间隔</th><th>指标</th><th>变化</th></tr></thead><tbody>${platforms.map(p=>`<tr><td>${esc(p.game_slug)} / ${esc(labels[p.source])}</td><td>${fmt(p.elapsed_hours)}h</td><td>${esc(p.primary_metric)}</td><td>${percent(p.primary_percent)}</td></tr>`).join('')}</tbody></table></div>`:empty('没有时间和采样范围都可比的平台观测；相同缓存样本不计算增长。')}<div class="panel"><h3>新增页面</h3>${(result.new_page_opportunities||[]).map(p=>`<p>${esc(p.primary_keyword_hypothesis)}</p>`).join('')||'<p>无新增 V2 页面节点。</p>'}<h3>移出本次样本的页面</h3>${(result.removed_page_opportunities||[]).map(p=>`<p>${esc(p.primary_keyword_hypothesis)}</p>`).join('')||'<p>无。</p>'}<p>“移出”不代表需求消失，也可能是本次发现或深度分析范围改变。</p></div>`;
  }catch(e){toast(e.message);}finally{$('compare').disabled=false;}
}
function renderSources(){
  const data=state.sources;if(!data){$('source-list').innerHTML=empty('正在读取本机数据源配置。');return;}
  $('source-list').innerHTML=`${data.is_demo?'<div class="notice amber">最近记录是示例。以下 fixture 状态不代表真实接口已经连通。</div>':''}<div class="source-grid">${data.configuration.map(c=>{const latest=data.latest_statuses.find(s=>s.source===c.source);return `<div class="panel"><h3>${esc(labels[c.source])}</h3>${badge(c.status)}<p>开关：${c.enabled?'开启':'关闭'} · 凭据 / 依赖：${c.configured?'就绪':'未配置'}</p><p>最近扫描：${esc(latest?statuses[latest.state]||latest.state:'尚未扫描')}</p><p>${esc(latest?.message||c.message)}</p><p>${latest?date(latest.checked_at):''}</p></div>`;}).join('')}</div>`;
  $('budget-list').innerHTML=`<div class="panel"><h2>请求预算</h2><div class="budget-grid">${Object.entries(data.budgets).map(([key,value])=>`<div><span>${esc(({discovery_limit:'发现游戏上限',deep_limit:'深度分析上限',youtube_search_calls_per_scan:'YouTube 搜索调用 / 扫描',youtube_search_calls_per_local_day:'YouTube 搜索调用 / 本机配额日',reddit_requests_per_scan:'Reddit 请求 / 扫描'})[key]||key)}</span><strong>${fmt(value)}</strong></div>`).join('')}</div><p>缓存命中不消耗新的搜索调用；本机预算不能代表项目其他客户端的配额消耗。</p></div>`;
}
async function refreshAux(){[state.history,state.queue,state.sources]=await Promise.all([api('/api/snapshots'),api('/api/validation'),api('/api/sources')]);renderHistory();renderQueue();renderSources();}
async function poll(){
  clearTimeout(pollTimer);
  try{
    const status=await api('/api/status');
    state.scanning=status.running;$('scan-button').disabled=status.running;$('demo').disabled=status.running;
    if(status.running){$('scan-progress').hidden=false;$('scan-progress').textContent=status.message;pollTimer=setTimeout(poll,1500);return;}
    if(status.phase==='complete'||status.phase==='failed'){
      $('scan-progress').hidden=false;$('scan-progress').textContent=status.message+(status.error?` (${status.error})`:'');
      await refreshAux();
      if(status.last_run_id){const result=await api(`/api/snapshots/${encodeURIComponent(status.last_run_id)}`);if(result.entities.length||result.games.length)applySnapshot(result);}
    }
  }catch(e){$('scan-button').disabled=false;$('demo').disabled=false;toast(e.message);}
}
document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-view]');if(nav){showView(nav.dataset.view,true);return;}
  const filter=event.target.closest('[data-filter]');if(filter){state.filter=filter.dataset.filter;state.more=12;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===filter));renderOverview();return;}
  const game=event.target.closest('[data-game]');if(game){renderDetail(game.dataset.game);showView('detail',true);return;}
  const validation=event.target.closest('[data-validate]');if(validation){validation.disabled=true;try{await addQueue(validation.dataset.validate);}catch(e){toast(e.message);}finally{validation.disabled=false;}return;}
  const record=event.target.closest('[data-edit-record]');if(record){const r=state.queue.find(r=>r.page_id===record.dataset.editRecord&&`${r.market}:${r.language}:${r.is_demo}`===record.dataset.recordScope);if(r)openValidation(r);return;}
  const load=event.target.closest('[data-load-snapshot]');if(load){try{applySnapshot(await api(`/api/snapshots/${encodeURIComponent(load.dataset.loadSnapshot)}`));showView('overview',true);}catch(e){toast(e.message);}return;}
  if(event.target.id==='show-more'){state.more+=12;renderOverview();}
});
$('search').addEventListener('input',e=>{state.query=e.target.value;state.more=12;renderOverview();});
$('queue-filter').addEventListener('change',renderQueue);
$('back-overview').addEventListener('click',()=>showView('overview',true));
$('compare').addEventListener('click',compare);
$('demo').addEventListener('click',async()=>{try{$('demo').disabled=true;applySnapshot(await api('/api/demo',{method:'POST'}));await refreshAux();renderOverview();showView('overview',true);}catch(e){toast(e.message);}finally{$('demo').disabled=false;}});
$('scan-form').addEventListener('submit',async event=>{event.preventDefault();$('scan-button').disabled=true;try{await api('/api/scan',{method:'POST',body:JSON.stringify({discovery_limit:Number($('discovery-limit').value),deep:Number($('deep-limit').value),with_trends:$('trends-enabled').checked})});await poll();}catch(e){$('scan-button').disabled=false;toast(e.message);}});
for(const id of ['close-dialog','cancel-dialog'])$(id).addEventListener('click',()=>$('validation-dialog').close());
$('validation-form').addEventListener('submit',async event=>{
  event.preventDefault();const f=event.target;const record={...state.editing};
  for(const k of ['stage','decision','semrush_evidence','serp_notes','decision_reason'])record[k]=f.elements[k].value;
  for(const k of ['semrush_volume','semrush_kd'])record[k]=f.elements[k].value===''?null:Number(f.elements[k].value);
  for(const k of ['semrush_checked_at','serp_checked_at'])record[k]=f.elements[k].value?new Date(f.elements[k].value).toISOString():null;
  record.serp_urls=f.elements.serp_urls.value.split('\n').map(s=>s.trim()).filter(Boolean);
  $('save-validation').disabled=true;$('validation-error').hidden=true;
  try{
    await api('/api/validation',{method:'PUT',body:JSON.stringify(record)});state.queue=await api('/api/validation');
    renderQueue();renderPages();renderOverview();if(state.selectedGame)renderDetail(state.selectedGame);
    $('validation-dialog').close();toast('验证记录已保存；历史扫描快照未改写。');
  }catch(e){$('validation-error').textContent=e.message;$('validation-error').hidden=false;$('validation-error').scrollIntoView({block:'nearest'});}finally{$('save-validation').disabled=false;}
});
(async()=>{
  try{await refreshAux();try{applySnapshot(await api('/api/snapshot'));}catch(e){if(!e.message.includes('Snapshot was not found'))throw e;renderOverview();}await poll();}
  catch(e){toast(e.message);renderOverview();}
})();
