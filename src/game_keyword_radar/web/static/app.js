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
const state={snapshot:null,history:[],queue:[],sources:null,view:'overview',filter:'today',query:'',selectedGame:null,editing:null,more:12,scanning:false};
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
  $('view-name').textContent={overview:'今日机会',pages:'页面机会图谱',queue:'验证队列',history:'历史变化',sources:'数据源与预算',detail:'游戏详情',monitoring:'观察与轻量监测'}[view];
  if(view==='pages')renderPages();if(view==='queue')renderQueue();if(view==='history')renderHistory();if(view==='sources')renderSources();if(view==='monitoring'){refreshMonitoring();loadPolicy();renderWatchList();}
  if(focus)window.scrollTo({top:0,behavior:'smooth'});
}
function applySnapshot(snapshot){
  snapshot.entities ||= [];snapshot.platform_signals ||= [];snapshot.question_clusters ||= [];snapshot.page_opportunities ||= [];snapshot.game_opportunities ||= [];
  state.snapshot=snapshot;
  $('data-mode').textContent=snapshot.is_demo?'DEMO · 合成示例':'LIVE · 实际扫描';
  $('data-mode').className=`pill ${snapshot.is_demo?'amber':'good'}`;
  $('demo-notice').hidden=!snapshot.is_demo;
  $('legacy-notice').hidden=snapshot.analysis_version==='2.1';
  $('snapshot-time').textContent=`${date(snapshot.generated_at)} · ${snapshot.country} · ${snapshot.language} · ${snapshot.run_id}`;
  $('download-report').href=`/api/report?run_id=${encodeURIComponent(snapshot.run_id)}`;$('download-report').setAttribute('aria-disabled','false');
  $('export-csv').href=`/api/keywords.csv?run_id=${encodeURIComponent(snapshot.run_id)}`;$('export-csv').setAttribute('aria-disabled','false');
  renderOverview();renderPages();renderQueue();renderWatchList();
  if(state.selectedGame&&gameFor(state.selectedGame))renderDetail(state.selectedGame);
}
const laneNames={new_release:'新游候选',rising:'增长线索',new_demand:'老游新需求',exploration:'探索候选'};
const momentumNames={unknown:'基线不足',early_signal:'早期信号',rising:'有可比增长',stable:'有稳定观测',falling:'有可比下降',mixed:'方向冲突',inconclusive:'变化尚不充分'};
const breadthNames={unknown:'广度未知',concentrated:'单主播集中',broadening:'传播正在扩展',distributed:'多频道分布'};
const destinationNames={selected:'已分配深度',deferred_budget:'预算延后 / 冷却',monitor_only:'仅观察',excluded:'明确排除'};
const sourceCount=slug=>Object.keys(labels).filter(source=>{const s=signalFor(slug,source);return s&&['ok','partial'].includes(s.status)&&Object.keys(s.metrics||{}).length;}).length;
function decisionFor(slug){return state.snapshot?.selection_decisions?.find(d=>d.game_slug===slug);}
function gameCard(g){
  const e=gameFor(g.game_slug),d=decisionFor(g.game_slug),pg=pagesFor(g.game_slug),m=d?.momentum;
  return `<article class="game-card"><div class="card-top"><div class="game-title"><div class="game-avatar" aria-hidden="true">${esc(e.canonical_name[0])}</div><div><h3>${esc(e.canonical_name)}</h3><small>${esc(d?.lifecycle?.reason||'历史版本未记录生命周期')}</small></div></div></div>
  <div class="page-meta"><span class="pill ${d?.primary_lane==='exploration'?'amber':'good'}">${esc(d?.entry_origin==='manual'?'人工研究':laneNames[d?.primary_lane]||'常青 / 观察')}</span><span>${esc(destinationNames[d?.decision]||'旧版本记录')}</span></div>
  <div class="why-now"><small>WHY NOW · 为什么现在值得看</small><p>${esc(d?.reasons?.[0]||'旧版本未记录入选理由，不按新政策补猜。')}</p></div>
  <div class="research-facts"><div><span>增长状态</span><strong>${esc(momentumNames[m?.state]||'历史未记录')}</strong></div><div><span>来源覆盖</span><strong>${sourceCount(g.game_slug)} / 5</strong></div><div><span>具体页面</span><strong>${pg.filter(p=>p.evidence_level!=='hypothesis').length}<small> / 假设 ${pg.filter(p=>p.evidence_level==='hypothesis').length}</small></strong></div></div>
  <div class="signal-row">${Object.keys(labels).map(source=>{const sig=signalFor(g.game_slug,source);return `<span class="signal-chip ${esc(sig?.status||'')}" title="${esc(statuses[sig?.status]||'未获取')}">${labels[source]} ${m?.rising_sources?.includes(source)?'↑':sig?.status==='ok'?'✓':sig?.status==='partial'?'◐':'—'}</span>`;}).join('')}</div><div class="card-bottom"><span class="action">${esc(actions[g.action])}</span><button class="button subtle" data-game="${esc(g.game_slug)}">查看依据 →</button></div></article>`;
}
function renderOverview(){
  const s=state.snapshot;
  if(!s){$('summary').innerHTML='';$('games').innerHTML='';$('empty').hidden=false;$('selection-funnel').hidden=true;return;}
  const ss=s.selection_summary||{},opps=s.game_opportunities||[];
  $('summary').innerHTML=[['去重实体',s.entities.length||s.games.length,'原始库，不等于新机会'],['本轮轻量观测',ss.monitored_entities,'初筛之前读取历史'],['深度入选',ss.deep_selected,'按通道分配，不必填满'],['可人工验证',ss.validation_candidates,'具体任务，未自动 Build']].map(([name,value,sub])=>`<div class="summary-tile"><span>${name}</span><strong>${fmt(value)}</strong><small>${sub}</small></div>`).join('');
  $('selection-funnel').hidden=s.analysis_version!=='2.1';
  $('selection-funnel').textContent=`原始记录 ${fmt(ss.raw_discovery_rows)} → 去重实体 ${fmt(ss.unique_entities)} → 元数据补全 ${fmt(ss.metadata_entities)} → 轻量观测 ${fmt(ss.monitored_entities)} → 符合条件 ${fmt(ss.eligible_entities)} → 深度 ${fmt(ss.deep_selected)}。成熟无新触发 ${fmt(ss.mature_without_trigger)}；预算延后 ${fmt(ss.budget_deferred)}；探索 ${fmt(ss.lane_selected?.exploration)}。页面：真实问题 ${fmt(ss.question_pages)} / 内容代理 ${fmt(ss.content_proxy_pages)} / 玩法假设 ${fmt(ss.hypothesis_pages)}。`;
  if(!s.entities.length&&s.games.length){$('empty').hidden=true;$('games').innerHTML=s.games.map(g=>`<div class="legacy-item"><h3>${esc(g.name)}</h3><p>旧版 Steam 记录 · 当前在线 ${fmt(g.current_players)}</p><p>历史未记录 V2.1 准入理由。</p></div>`).join('');return;}
  let filtered=opps.filter(g=>{
    const e=gameFor(g.game_slug),d=decisionFor(g.game_slug);
    if(state.query&&!`${e?.canonical_name} ${pagesFor(g.game_slug).map(p=>p.primary_keyword_hypothesis).join(' ')}`.toLowerCase().includes(state.query.toLowerCase()))return false;
    if(s.analysis_version!=='2.1')return true;
    if(state.filter==='all')return true;
    if(state.filter==='today')return d?.selected_for_deep;
    return d?.primary_lane===state.filter||d?.decision===state.filter;
  });
  $('empty').hidden=opps.length>0;
  if(!filtered.length){$('games').innerHTML=opps.length?empty('本轮没有符合这个视图的候选。不会用成熟热榜填满；可查看预算延后、观察列表和来源诊断。'):'';return;}
  if(state.filter==='today'&&s.analysis_version==='2.1'){
    $('games').innerHTML=Object.entries(laneNames).map(([lane,name])=>{
      const rows=filtered.filter(g=>decisionFor(g.game_slug)?.primary_lane===lane);
      return `<section class="lane-section"><div class="section-heading"><div><h2>${name}<span class="lane-count">${rows.length}</span></h2><p>${lane==='exploration'?'弱信号与人工研究单列，不冒充已验证精选。':lane==='rising'?'与自身同口径历史相比；规模大不是增长证据。':lane==='new_release'?'平台近期发行可暂入，首次扫描不等于首次发售。':'必须有近期可定位的具体任务，不以旧模板制造新需求。'}</p></div></div><div class="lane-grid">${rows.map(gameCard).join('')||empty('本通道当前没有分配到深度候选，保留空位。')}</div></section>`;
    }).join('');
  }else{
    $('games').innerHTML=`<div class="lane-grid">${filtered.slice(0,state.more).map(gameCard).join('')}</div>`+(filtered.length>state.more?`<button id="show-more" class="button subtle">继续查看 ${filtered.length-state.more} 个实体</button>`:'');
  }
}
function pageCard(p,includeGame=false){
  const record=state.queue.find(r=>sameScope(r)&&r.page_id===p.id);
  return `<article class="page-card"><div class="page-top"><div>${includeGame?`<p>${esc(gameFor(p.game_slug)?.canonical_name||p.game_slug)}</p>`:''}<h3>${esc(p.primary_keyword_hypothesis)}</h3><span class="code">${esc(p.path)}</span></div><span class="page-score">${fmt(p.score)}<small> / 69</small></span></div><div class="page-meta"><span class="pill ${p.evidence_level==='hypothesis'?'amber':'good'}">${esc(level[p.evidence_level]||p.evidence_level)}</span><span>${esc(p.page_type)}</span><span>开发 ${esc(p.build_difficulty)}</span><span>维护 ${esc(p.maintenance_level)}</span><span>原始研究分 ${fmt(p.raw_score)}</span></div><p>${esc(p.page_value)}</p>${p.existing_site_fit?`<p><strong>优先承接：${esc(p.existing_site_fit)}</strong> · 扩页前仍需验证</p>`:''}<details><summary>WHY THIS PAGE EXISTS · ${p.trigger_signals.length} 条触发依据</summary>${p.trigger_signals.map(e=>`<div class="evidence">${e.url?`<a href="${esc(url(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a>`:esc(e.title)}<small>${esc(e.source)} · ${date(e.captured_at)} ${e.is_inference?'· 规则推测，并非搜索事实':''}</small></div>`).join('')}<div class="evidence"><strong>评分拆分</strong><pre>${esc(JSON.stringify(p.score_breakdown,null,2))}</pre></div></details><div class="page-actions"><button class="button ${record?'subtle':'primary'}" data-validate="${esc(p.id)}">${record?'编辑验证记录':'加入验证队列'}</button><span class="pill">${esc(stages[record?.stage||'needs_validation'])}</span></div></article>`;
}
function renderPages(){const s=state.snapshot;$('all-pages').innerHTML=s?.page_opportunities.length?s.page_opportunities.map(p=>pageCard(p,true)).join(''):empty('还没有 V2 页面机会。先扫描或加载示例。');}
function comparisonText(d,source,period){
  if(!d)return '旧版本点对仅见兼容诊断';
  const key=source==='steam'?'current_players':'total_viewers';
  const c=d.momentum.comparisons.find(c=>c.source===source&&c.metric===key&&c.period===period);
  if(!c)return '无可比窗口';
  return `${c.percent_change===null?`${fmt(c.baseline_value)} → ${fmt(c.current_value)}（低基数）`:percent(c.percent_change)} · ${c.qualified?'多点窗口':'有限线索'} / ${c.pair_count} 对`;
}
function renderDetail(slug){
  const entity=gameFor(slug);if(!entity)return;
  state.selectedGame=slug;const g=state.snapshot.game_opportunities.find(g=>g.game_slug===slug),d=decisionFor(slug);
  const clusters=state.snapshot.question_clusters.filter(c=>c.game_slug===slug),a=state.snapshot.annotations?.[slug]||{};
  const cards=Object.keys(labels).map(source=>{
    const s=signalFor(slug,source);if(!s)return `<div class="platform-card"><h3>${labels[source]}</h3><p>缺失</p></div>`;
    const metrics=s.metrics,key={steam:'current_players',twitch:'total_viewers',youtube:'recent_guide_video_count',reddit:'question_count',trends:'recent_interest'}[source];
    const metricLabel={steam:'全球在线（瞬时观测）',twitch:metrics.sampling_complete?'观众（采集窗口观测）':'观众（样本下限）',youtube:'攻略视频（内容代理样本）',reddit:'问题标题（样本）',trends:'近期相对兴趣'}[source];
    return `<div class="platform-card"><h3>${labels[source]}</h3>${badge(s.status)}<strong>${fmt(metrics[key])}</strong><p>${metricLabel}</p>${['steam','twitch'].includes(source)?`<p>24h：${esc(comparisonText(d,source,'24h'))}<br>7d：${esc(comparisonText(d,source,'7d'))}</p>`:'<p>不是 Google 搜索量</p>'}<p>${date(s.captured_at)}<br>${esc(s.market)} · ${esc(s.confidence)}${s.cache_hit?' · 复用原观测':''}</p><details><summary>原始指标与限制</summary><pre>${esc(JSON.stringify(metrics,null,2))}</pre><p>观测 ID：${esc(s.observation_id||'历史未记录')}</p>${s.notes.map(n=>`<p>${esc(n)}</p>`).join('')}<p>失败原因：${esc(s.failure_reason||'无')}</p><p>采集窗口：${date(s.window_started_at)} — ${date(s.window_finished_at)}</p></details></div>`;
  }).join('');
  $('game-detail').innerHTML=`<div class="detail-heading"><div><div class="eyebrow">${esc(d?.entry_origin==='manual'?'MANUAL RESEARCH':'GAME OPPORTUNITY')} / ${esc(laneNames[d?.primary_lane]||'仅观察')}</div><h1>${esc(entity.canonical_name)}</h1><p>${esc(d?.lifecycle.reason||'历史版本未记录生命周期')}</p></div></div><div class="research-facts detail-facts"><div><span>增长状态</span><strong>${esc(momentumNames[d?.momentum.state]||'历史未记录')}</strong></div><div><span>传播广度</span><strong>${esc(breadthNames[d?.momentum.breadth]||'未知')}</strong></div><div><span>来源覆盖</span><strong>${sourceCount(slug)} / 5</strong></div><div><span>入选判断</span><strong>${esc(destinationNames[d?.decision]||'历史未记录')}</strong></div></div>
  <div class="panel"><h2>WHY NOW · 本轮入选依据</h2>${(d?.reasons||['旧版本未记录，不补猜。']).map(x=>`<p>${esc(x)}</p>`).join('')}<p>下一步：${esc(g?.action_reason||'继续补充证据')}</p><small>政策 ${esc(d?.policy_version||'未记录')} · ${date(d?.as_of)} · 发行与本机首次发现 ${date(entity.first_seen_at)} 分开记录</small><details><summary>比较、限制与预算诊断</summary>${(d?.momentum.limitations||[]).map(x=>`<p>${esc(x)}</p>`).join('')}<pre>${esc(JSON.stringify(d||{},null,2))}</pre></details></div>
  <p class="footnote">实体匹配：${esc(entity.match_method)} · ${esc(Object.entries(entity.platform_ids).map(([k,v])=>`${k}: ${v}`).join(' / '))}</p><div class="platform-grid">${cards}</div>
  <div class="section-heading"><div><h2>玩家在找什么？</h2><p>真实问题、答案型内容代理、玩法假设分别计数；不是搜索次数。</p></div></div><div class="question-clusters">${clusters.map(c=>`<div class="cluster"><h3>${esc(c.cluster_name)}</h3><p>${c.question_count} 条真实问题 · ${c.content_proxy_count||0} 条内容代理</p>${c.examples.slice(0,3).map(e=>`<div class="evidence">${esc(e.title)}<small>${esc(e.source)} · 发布 ${date(e.published_at)}</small></div>`).join('')}</div>`).join('')||empty('尚未获得具体问题 / 内容证据；不等于玩家没有需求。')}</div>
  <div class="section-heading"><div><h2>Page Graph</h2><p>预验证分上限 69，入选不等于 Build。</p></div></div>${pagesFor(slug).map(p=>pageCard(p)).join('')||empty('暂无可解释页面节点。')}
  <details class="panel"><summary>人工观察、忽略与证据纠正</summary><p>保存人工来源，下一次扫描使用；不会改写当前历史判断。手动研究消耗本轮名额，不伪装为自动发现。</p><form id="annotation-form"><div class="form-grid"><label class="check"><input name="watch" type="checkbox" ${a.watch?'checked':''}> 加入观察</label><label class="check"><input name="ignored" type="checkbox" ${a.ignored?'checked':''}> 明确忽略</label><label class="check"><input name="request_research" type="checkbox"> 请求下一轮手动研究</label><label>首次公开可玩日期（有依据才填）<input name="first_public_playable_at" type="date" value="${esc(a.first_public_playable_at||'')}"></label><label>发行阶段<select name="release_stage">${['unknown','released','early_access','demo','upcoming'].map(x=>`<option value="${x}" ${a.release_stage===x?'selected':''}>${esc(({unknown:'不修改 / 待核实',released:'已发售',early_access:'抢先体验',demo:'试玩',upcoming:'未发售'})[x])}</option>`).join('')}</select></label><label>具体问题意图<select name="intent"><option value="">无补充</option>${['workshop','calculator','tracker','codes','tier-list','locations','builds','errors','walkthrough','guide'].map(x=>`<option value="${x}" ${a.intent===x?'selected':''}>${x}</option>`).join('')}</select></label><label>证据 URL<input name="evidence_url" type="url" value="${esc(a.evidence_url||'')}"></label><label>证据发布时间<input name="evidence_published_at" type="datetime-local" value="${localDate(a.evidence_published_at)}"></label><label>核实的 Steam ID<input name="steam_id" pattern="[0-9]*" value="${esc(a.platform_ids?.steam||'')}"></label><label>核实的 Twitch ID<input name="twitch_id" pattern="[0-9]*" value="${esc(a.platform_ids?.twitch||'')}"></label></div><label>已核实别名（逗号分隔）<input name="aliases" value="${esc((a.aliases||[]).join(', '))}"></label><label>理由 / 具体问题<textarea name="reason" rows="2" maxlength="2000">${esc(a.reason||'')}</textarea></label><button type="submit" class="button primary">保存人工记录</button></form></details>
  <details class="panel"><summary>旧版本研究分（仅兼容，不参与 V2.1 初筛）</summary><p>旧 Demand ${fmt(g?.demand.score)}；权重覆盖 ${Math.round((g?.demand.coverage||0)*100)}%。不是成功率，不是增长状态。</p></details>`;
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
    const gameRows=(result.v2_game_changes||[]).map(g=>`<tr><td>${esc(g.game_slug)}</td><td>${g.rank_change===null?'—':`${g.rank_change>0?'+':''}${g.rank_change}`}</td><td>${g.demand_score_change===null?'—':`${g.demand_score_change>0?'+':''}${fmt(g.demand_score_change)}`}</td><td>${g.score_comparable?'口径一致':'政策 / 来源 / 采样变化，不解释成需求涨跌'} · ${g.change==='unchanged'?'未变化':esc((g.changed_fields||[]).join(' / '))}</td></tr>`).join('');
    $('comparison').innerHTML=`<div class="notice ${result.comparable?'':'amber'}">${esc(result.note)}</div>${gameRows?`<div class="table-wrap"><table><thead><tr><th>游戏</th><th>排名上升</th><th>Demand 分差</th><th>可比性</th></tr></thead><tbody>${gameRows}</tbody></table></div>`:''}<div class="summary-grid">${[['新增页面',result.new_page_opportunities?.length??result.new_opportunities],['移出本次样本',result.removed_page_opportunities?.length??result.removed_opportunities],['可比平台观测',platforms.length],['游戏分数变化',result.score_changed_games??result.changed_games]].map(([k,v])=>`<div class="summary-tile"><span>${k}</span><strong>${fmt(v)}</strong></div>`).join('')}</div>${platforms.length?`<div class="table-wrap"><table><thead><tr><th>游戏 / 平台</th><th>观测间隔</th><th>指标</th><th>变化</th></tr></thead><tbody>${platforms.map(p=>`<tr><td>${esc(p.game_slug)} / ${esc(labels[p.source])}</td><td>${fmt(p.elapsed_hours)}h</td><td>${esc(p.primary_metric)}</td><td>${percent(p.primary_percent)}</td></tr>`).join('')}</tbody></table></div>`:empty('没有时间和采样范围都可比的平台观测；相同缓存样本不计算增长。')}<div class="panel"><h3>新增页面</h3>${(result.new_page_opportunities||[]).map(p=>`<p>${esc(p.primary_keyword_hypothesis)}</p>`).join('')||'<p>无新增 V2 页面节点。</p>'}<h3>移出本次样本的页面</h3>${(result.removed_page_opportunities||[]).map(p=>`<p>${esc(p.primary_keyword_hypothesis)}</p>`).join('')||'<p>无。</p>'}<p>“移出”不代表需求消失，也可能是本次发现或深度分析范围改变。</p></div>`;
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


let monitoringTimer;
async function refreshMonitoring(){
  clearTimeout(monitoringTimer);
  try{
    const m=await api('/api/monitoring');
    $('monitor-status').textContent=`${m.enabled?'定时监测已开启':'定时监测未开启'} · 间隔 ${m.interval_minutes} 分钟 · ${m.message}。最近完成 ${date(m.last_completed_at)}；下次 ${date(m.next_due_at)}。${m.gap_note||''}${m.error?' 错误：'+m.error:''}`;
    document.querySelectorAll('[data-monitor]').forEach(b=>b.disabled=b.dataset.monitor==='stop'?!(m.enabled||m.running):m.enabled||m.running||state.scanning);
    if(m.enabled||m.running)monitoringTimer=setTimeout(refreshMonitoring,2500);
  }catch(e){toast(e.message);}
}
async function loadPolicy(){try{const p=await api('/api/policy');$('policy-json').value=JSON.stringify(p.policy,null,2);$('policy-hash').textContent=` ${p.version} · ${p.config_hash}`;}catch(e){toast(e.message);}}
function renderWatchList(){
  const rows=(state.snapshot?.game_opportunities||[]).filter(g=>{const d=decisionFor(g.game_slug);return !d?.selected_for_deep||state.snapshot.annotations?.[g.game_slug]?.watch;});
  $('watch-list').innerHTML=`<div class="section-heading"><h2>观察 / 延后记录</h2></div><div class="lane-grid">${rows.map(gameCard).join('')||empty('当前没有观察或延后记录。人工种子会在下一轮进入发现池。')}</div>`;
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-monitor]');if(!b)return;
  b.disabled=true;
  try{await api('/api/monitoring/'+b.dataset.monitor,{method:'POST'});await refreshMonitoring();}catch(error){toast(error.message);b.disabled=false;}
});
$('policy-form').addEventListener('submit',async e=>{
  e.preventDefault();try{await api('/api/policy',{method:'PUT',body:JSON.stringify(JSON.parse($('policy-json').value))});await loadPolicy();await refreshMonitoring();toast('已应用到当前服务会话；历史和配置文件未覆盖。');}catch(error){toast(error.message);}
});
$('seed-form').addEventListener('submit',async e=>{
  e.preventDefault();const values=Object.fromEntries(new FormData(e.target));
  try{await api('/api/seeds',{method:'POST',body:JSON.stringify(values)});e.target.reset();toast('人工种子已保存。运行扫描或轻量监测后查看结果。');}catch(error){toast(error.message);}
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='annotation-form')return;
  e.preventDefault();const f=e.target,previous=state.snapshot.annotations?.[state.selectedGame]||{};
  const v=Object.fromEntries(new FormData(f));
  const record={...previous,game_slug:state.selectedGame,is_demo:state.snapshot.is_demo,watch:!!v.watch,ignored:!!v.ignored,
    reason:v.reason,evidence_url:v.evidence_url||null,first_public_playable_at:v.first_public_playable_at||null,
    release_stage:v.release_stage,intent:v.intent||null,checked_at:new Date().toISOString(),
    evidence_published_at:v.evidence_published_at?new Date(v.evidence_published_at).toISOString():null,
    platform_ids:{...(v.steam_id?{steam:v.steam_id}:{}),...(v.twitch_id?{twitch:v.twitch_id}:{})},
    aliases:v.aliases.split(',').map(x=>x.trim()).filter(Boolean)};
  if(v.request_research)record.research_requested_at=new Date().toISOString();
  try{const saved=await api('/api/annotations',{method:'PUT',body:JSON.stringify(record)});state.snapshot.annotations||={};state.snapshot.annotations[state.selectedGame]=saved;renderWatchList();toast('人工记录已保存；当前快照的初筛理由保持不变。');}catch(error){toast(error.message);}
});
