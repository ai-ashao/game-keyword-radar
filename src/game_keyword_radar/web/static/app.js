const state = {
  snapshot: null,
  history: [],
  comparison: null,
  query: "",
  type: "all",
  poller: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeImage(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "";
  } catch {
    return "";
  }
}

function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("visible");
  window.clearTimeout(element._timer);
  element._timer = window.setTimeout(() => element.classList.remove("visible"), 3600);
}

function updateRunState(status) {
  const container = $("#run-state");
  const text = $("#run-state-text");
  const scanButtons = [$("#scan-button"), $("#empty-scan")].filter(Boolean);
  if (status.running) {
    container.dataset.state = "running";
    text.textContent = status.message || "扫描中";
  } else if (status.phase === "failed") {
    container.dataset.state = "failed";
    text.textContent = status.error || status.message || "扫描失败";
  } else if (status.phase === "complete") {
    container.dataset.state = "ok";
    text.textContent = status.message;
  } else {
    container.dataset.state = state.snapshot ? "ok" : "idle";
    text.textContent = state.snapshot ? "快照可用" : "等待扫描";
  }
  scanButtons.forEach((button) => { button.disabled = Boolean(status.running); });
}

function formatTime(value) {
  if (!value) return "尚无快照";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function formatHistoryLabel(item) {
  const date = new Date(item.generated_at);
  const time = Number.isNaN(date.valueOf()) ? item.generated_at : new Intl.DateTimeFormat("zh-CN", {
    year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
  return `${time} · ${item.games_count} 游戏${item.is_demo ? " · 示例" : ""}`;
}

function formatNumber(value) {
  return value == null ? "—" : new Intl.NumberFormat("zh-CN").format(value);
}

function signed(value, digits = 0) {
  if (value == null) return "—";
  const number = digits ? Number(value).toFixed(digits) : String(value);
  return value > 0 ? `+${number}` : number;
}

function uniqueMissing(snapshot) {
  return new Set(snapshot.opportunities.flatMap((item) => item.missing_evidence)).size;
}

function renderMetrics(snapshot) {
  $("#metric-games").textContent = snapshot.games.length;
  $("#metric-opportunities").textContent = snapshot.opportunities.length;
  $("#metric-priority").textContent = snapshot.opportunities.filter((item) => item.score >= 60).length;
  $("#metric-evidence").textContent = uniqueMissing(snapshot);
  $("#snapshot-time").textContent = `更新 ${formatTime(snapshot.generated_at)}`;
  $("#snapshot-market").textContent = `${snapshot.country} · ${snapshot.language}`.toUpperCase();
  $("#fixture-banner").hidden = !snapshot.is_demo;
}

function renderRadar(snapshot) {
  const top = snapshot.opportunities.slice(0, 8);
  const dots = top.map((item, index) => {
    const angle = (index * 137.5 + 28) * Math.PI / 180;
    const radius = 11 + (69 - item.score) * 0.7 + (index % 3) * 3;
    const x = 50 + Math.cos(angle) * Math.min(39, radius);
    const y = 50 + Math.sin(angle) * Math.min(39, radius);
    const size = 7 + Math.max(0, item.score - 45) / 4;
    return `<span class="radar-dot ${index ? "secondary" : ""}" style="--x:${x}%;--y:${y}%;--size:${size}px" title="${escapeHtml(item.game_name)} · ${escapeHtml(item.keyword.cluster)}"></span>`;
  }).join("");
  $("#radar-dots").innerHTML = dots;
  $("#radar-primary").textContent = top[0] ? `${top[0].score.toFixed(0)} / ${top[0].keyword.cluster}` : "NO SIGNAL";
}

function filteredOpportunities() {
  if (!state.snapshot) return [];
  const query = state.query.trim().toLowerCase();
  return state.snapshot.opportunities.filter((item) => {
    const text = `${item.game_name} ${item.keyword.keyword} ${item.keyword.cluster}`.toLowerCase();
    return (!query || text.includes(query)) && (state.type === "all" || item.keyword.page_type === state.type);
  });
}

function renderRows() {
  const rows = filteredOpportunities();
  const target = $("#opportunity-rows");
  const empty = $("#empty-state");
  if (!state.snapshot) {
    target.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = rows.length > 0;
  if (!rows.length) {
    empty.querySelector("h3").textContent = "没有符合筛选的机会";
    empty.querySelector("p").textContent = "清除搜索词或切换页面类型。";
    target.innerHTML = "";
    return;
  }
  target.innerHTML = rows.map((item, index) => {
    const image = safeImage(item.game_image_url);
    const confidence = item.keyword.evidence_confidence || "low";
    return `
      <div class="table-row" role="button" tabindex="0" data-id="${escapeHtml(item.id)}" aria-label="查看 ${escapeHtml(item.game_name)} ${escapeHtml(item.keyword.cluster)} 详情">
        <div class="opportunity-cell">
          <span class="rank-number">${String(index + 1).padStart(2, "0")}</span>
          ${image ? `<img class="game-thumb" src="${image}" alt="" loading="lazy" />` : `<span class="game-thumb"></span>`}
          <span class="opportunity-copy">
            <strong>${escapeHtml(item.keyword.keyword)}</strong>
            <span>${escapeHtml(item.game_name)} · ${escapeHtml(item.keyword.cluster)}</span>
          </span>
        </div>
        <span class="type-badge">${escapeHtml(item.keyword.page_type)}</span>
        <span class="evidence-badge ${confidence === "low" ? "low" : ""}">${escapeHtml(confidence)} · 缺 ${item.missing_evidence.length}</span>
        <span class="score-cell"><strong>${item.score.toFixed(0)}</strong><span>/69</span></span>
      </div>`;
  }).join("");
  $$("#opportunity-rows .table-row").forEach((row) => {
    const open = () => openDetail(row.dataset.id);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
}

function renderDistribution(snapshot) {
  const bands = [
    { label: "60–69", min: 60, max: 69 },
    { label: "50–59", min: 50, max: 59 },
    { label: "40–49", min: 40, max: 49 },
    { label: "< 40", min: 0, max: 39 },
  ];
  const counts = bands.map((band) => snapshot.opportunities.filter((item) => item.score >= band.min && item.score <= band.max).length);
  const max = Math.max(1, ...counts);
  $("#score-bars").innerHTML = bands.map((band, index) => `
    <div class="score-bar-row">
      <span>${band.label}</span>
      <span class="bar-track"><span class="bar-fill" style="--bar:${(counts[index] / max) * 100}%"></span></span>
      <strong>${counts[index]}</strong>
    </div>`).join("");
}

function renderSources(snapshot) {
  $("#source-grid").innerHTML = snapshot.source_statuses.map((source) => `
    <article class="source-card ${escapeHtml(source.state)}">
      <header><h3>${escapeHtml(source.source.replaceAll("_", " "))}</h3><span class="source-state">${escapeHtml(source.state)}</span></header>
      <p>${escapeHtml(source.message)}</p>
      <small>${source.records} RECORDS · ${source.official_api ? "OFFICIAL" : "PUBLIC / UNOFFICIAL"}</small>
    </article>`).join("");
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  renderMetrics(snapshot);
  renderRadar(snapshot);
  renderRows();
  renderDistribution(snapshot);
  renderSources(snapshot);
  $("#download-report").removeAttribute("aria-disabled");
  $("#download-report").href = `/api/report?run_id=${encodeURIComponent(snapshot.run_id)}`;
}

const changeLabels = {
  new: "新增", removed: "离场", changed: "变化", rising: "上升", falling: "下降",
};

function renderGameChanges(items) {
  const target = $("#game-change-list");
  if (!items.length) {
    target.innerHTML = '<div class="change-list-empty">两次扫描中的游戏信号没有变化</div>';
    return;
  }
  target.innerHTML = items.slice(0, 12).map((item) => {
    let detail = "候选集合发生变化";
    if (item.change === "changed") {
      const players = `玩家 ${formatNumber(item.baseline_players)} → ${formatNumber(item.current_players)}`;
      const rank = item.rank_delta == null
        ? "排名证据不足"
        : `排名 ${formatNumber(item.baseline_rank)} → ${formatNumber(item.current_rank)}`;
      detail = `${players} · ${rank}`;
    }
    const signal = item.signal_delta == null ? "" : signed(item.signal_delta, 1);
    return `<article class="change-row">
      <span class="change-kind ${escapeHtml(item.change)}">${changeLabels[item.change] || escapeHtml(item.change)}</span>
      <span class="change-copy"><strong>${escapeHtml(item.game_name)}</strong><span>${escapeHtml(detail)}</span></span>
      <span class="change-value">信号<strong>${escapeHtml(signal || "—")}</strong></span>
    </article>`;
  }).join("");
}

function renderOpportunityChanges(items) {
  const target = $("#opportunity-change-list");
  if (!items.length) {
    target.innerHTML = '<div class="change-list-empty">两次扫描中的机会优先级没有变化</div>';
    return;
  }
  target.innerHTML = items.slice(0, 12).map((item) => {
    const score = item.score_delta == null ? "—" : signed(item.score_delta, 1);
    const detail = `${item.game_name} · ${item.cluster} · ${item.page_type}`;
    return `<article class="change-row">
      <span class="change-kind ${escapeHtml(item.change)}">${changeLabels[item.change] || escapeHtml(item.change)}</span>
      <span class="change-copy"><strong>${escapeHtml(item.keyword)}</strong><span>${escapeHtml(detail)}</span></span>
      <span class="change-value">优先级<strong>${escapeHtml(score)}</strong></span>
    </article>`;
  }).join("");
}

function renderComparison(comparison) {
  state.comparison = comparison;
  $("#history-empty").hidden = true;
  $("#history-content").hidden = false;
  $("#change-new-games").textContent = comparison.new_games;
  $("#change-removed-games").textContent = comparison.removed_games;
  $("#change-rising").textContent = comparison.rising_opportunities;
  $("#change-new-opportunities").textContent = comparison.new_opportunities;
  const note = $("#change-note");
  note.textContent = comparison.note;
  note.classList.toggle("warning", !comparison.comparable);
  renderGameChanges(comparison.game_changes);
  renderOpportunityChanges(comparison.opportunity_changes);
}

function showHistoryEmpty(title = "需要至少两次扫描", message = "再次扫描 Steam 后，这里会显示候选、玩家数、排名和机会优先级的变化。") {
  state.comparison = null;
  $("#history-content").hidden = true;
  $("#history-empty").hidden = false;
  $("#history-empty h3").textContent = title;
  $("#history-empty p").textContent = message;
}

function populateHistoryControls(preferredCurrent, preferredBaseline) {
  const currentSelect = $("#history-current");
  const baselineSelect = $("#history-baseline");
  currentSelect.innerHTML = state.history.map((item) =>
    `<option value="${escapeHtml(item.run_id)}">${escapeHtml(formatHistoryLabel(item))}</option>`
  ).join("");
  const current = state.history.some((item) => item.run_id === preferredCurrent)
    ? preferredCurrent : state.history[0]?.run_id;
  if (current) currentSelect.value = current;
  const candidates = state.history.filter((item) => item.run_id !== current);
  baselineSelect.innerHTML = candidates.map((item) =>
    `<option value="${escapeHtml(item.run_id)}">${escapeHtml(formatHistoryLabel(item))}</option>`
  ).join("");
  const currentIndex = state.history.findIndex((item) => item.run_id === current);
  const automatic = state.history[currentIndex + 1]?.run_id || candidates[0]?.run_id;
  const baseline = candidates.some((item) => item.run_id === preferredBaseline)
    ? preferredBaseline : automatic;
  if (baseline) baselineSelect.value = baseline;
  currentSelect.disabled = state.history.length === 0;
  baselineSelect.disabled = candidates.length === 0;
  return { current, baseline };
}

async function loadComparison(currentRunId, baselineRunId) {
  if (!currentRunId || !baselineRunId) {
    showHistoryEmpty();
    return;
  }
  try {
    const params = new URLSearchParams({
      current_run_id: currentRunId,
      baseline_run_id: baselineRunId,
    });
    renderComparison(await fetchJson(`/api/compare?${params}`));
  } catch (error) {
    showHistoryEmpty("无法生成变化对比", error.message);
  }
}

async function loadHistory(preferredCurrent = state.snapshot?.run_id, preferredBaseline) {
  try {
    state.history = await fetchJson("/api/snapshots");
    const selection = populateHistoryControls(preferredCurrent, preferredBaseline);
    if (state.history.length < 2) {
      showHistoryEmpty();
      return;
    }
    await loadComparison(selection.current, selection.baseline);
  } catch (error) {
    showHistoryEmpty("读取历史失败", error.message);
  }
}

async function selectHistoricalSnapshot(runId) {
  try {
    const snapshot = await fetchJson(`/api/snapshots/${encodeURIComponent(runId)}`);
    renderSnapshot(snapshot);
    const selection = populateHistoryControls(runId, $("#history-baseline").value);
    await loadComparison(selection.current, selection.baseline);
  } catch (error) {
    toast(`读取历史快照失败：${error.message}`, true);
  }
}

function breakdownRows(item) {
  const labels = {
    problem_intensity: ["问题强度", 25], page_intent: ["页面意图", 20], feasibility: ["开发可行", 20],
    maintenance: ["低维护", 10], game_signal: ["游戏信号", 15], evidence_confidence: ["证据置信", 10],
  };
  return Object.entries(item.score_breakdown).map(([key, value]) => {
    const [label, max] = labels[key];
    return `<div class="breakdown-row"><span>${label}</span><span class="breakdown-track"><span class="breakdown-fill" style="width:${Math.min(100, (value / max) * 100)}%"></span></span><strong>${value}</strong></div>`;
  }).join("");
}

function openDetail(id) {
  const item = state.snapshot?.opportunities.find((opportunity) => opportunity.id === id);
  if (!item) return;
  $("#detail-game").textContent = item.game_name;
  $("#detail-title").textContent = item.keyword.cluster;
  $("#detail-content").innerHTML = `
    <div class="detail-hero">
      <div>
        <p class="detail-summary"><strong>${escapeHtml(item.keyword.keyword)}</strong><br />${escapeHtml(item.keyword.rationale)}</p>
        <div class="keyword-list">${item.keyword.supporting_keywords.map((keyword) => `<span class="keyword-chip">${escapeHtml(keyword)}</span>`).join("")}</div>
      </div>
      <div class="detail-score"><strong>${item.score.toFixed(0)}</strong><span>OF 69 VALIDATION</span></div>
    </div>
    <div class="detail-grid">
      <section class="detail-card"><h3>评分明细</h3><div class="breakdown">${breakdownRows(item)}</div></section>
      <section class="detail-card"><h3>待补证据</h3><ul>${item.missing_evidence.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>
      <section class="detail-card"><h3>主要风险</h3><ul>${item.risks.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>
      <section class="detail-card"><h3>下一步验证</h3><ul>${item.next_steps.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>
    </div>`;
  $("#detail-dialog").showModal();
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch { /* keep status */ }
    throw new Error(message);
  }
  return response.json();
}

async function loadLatest() {
  try {
    renderSnapshot(await fetchJson("/api/snapshot"));
  } catch (error) {
    if (!String(error.message).startsWith("404")) toast(`读取快照失败：${error.message}`, true);
    renderRows();
  }
}

async function loadDemo() {
  try {
    const snapshot = await fetchJson("/api/demo", { method: "POST" });
    renderSnapshot(snapshot);
    await loadHistory(snapshot.run_id);
    toast("已载入明确标注的示例数据");
  } catch (error) { toast(`载入失败：${error.message}`, true); }
}

async function pollStatus() {
  try {
    const status = await fetchJson("/api/status");
    updateRunState(status);
    if (!status.running && state.poller) {
      window.clearInterval(state.poller);
      state.poller = null;
      if (status.phase === "complete") {
        await loadLatest();
        await loadHistory(state.snapshot?.run_id);
        toast(status.message);
      } else if (status.phase === "failed") {
        toast(status.error || status.message, true);
      }
    }
  } catch (error) { toast(`状态检查失败：${error.message}`, true); }
}

async function startScan(limit, withTrends) {
  try {
    const status = await fetchJson("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, with_trends: withTrends }),
    });
    updateRunState(status);
    $("#scan-dialog").close();
    toast("扫描已开始，现有结果会保留到新快照完成");
    if (!state.poller) state.poller = window.setInterval(pollStatus, 1400);
  } catch (error) { toast(`无法开始扫描：${error.message}`, true); }
}

function bindEvents() {
  [$("#demo-button"), $("#empty-demo")].forEach((button) => button?.addEventListener("click", loadDemo));
  [$("#scan-button"), $("#empty-scan")].forEach((button) => button?.addEventListener("click", () => $("#scan-dialog").showModal()));
  $("#detail-close").addEventListener("click", () => $("#detail-dialog").close());
  $("#scan-close").addEventListener("click", () => $("#scan-dialog").close());
  $("#search-input").addEventListener("input", (event) => { state.query = event.target.value; renderRows(); });
  $("#type-filter").addEventListener("change", (event) => { state.type = event.target.value; renderRows(); });
  $("#history-current").addEventListener("change", (event) => selectHistoricalSnapshot(event.target.value));
  $("#history-baseline").addEventListener("change", (event) => loadComparison($("#history-current").value, event.target.value));
  $("#scan-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const limit = Number($("#scan-limit").value);
    if (!Number.isInteger(limit) || limit < 1 || limit > 30) {
      toast("深度分析数量必须在 1 到 30 之间", true);
      return;
    }
    startScan(limit, $("#scan-trends").checked);
  });
  [$("#detail-dialog"), $("#scan-dialog")].forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await loadLatest();
  await loadHistory();
  try { updateRunState(await fetchJson("/api/status")); } catch { /* health shown by snapshot */ }
});
