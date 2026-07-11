const $ = (sel) => document.querySelector(sel);

// ---------- theme ----------
const themeToggle = $("#theme-toggle");
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("signal-theme", t);
}
(function initTheme() {
  const saved = localStorage.getItem("signal-theme");
  if (saved) applyTheme(saved);
})();
themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(current === "dark" ? "light" : "dark");
});

// ---------- generate ----------
const topicInput = $("#topic-input");
const urlField = $("#url-field");
const urlInput = $("#url-input");
const generateBtn = $("#generate-btn");
const planBtn = $("#plan-btn");
const jobStatusEl = $("#job-status");
const jobStatusText = $("#job-status-text");
const jobSpinner = $("#job-spinner");
const jobLog = $("#job-log");
const checkpointPanel = $("#checkpoint-panel");
const checkpointPrompt = $("#checkpoint-prompt");
const checkpointChoices = $("#checkpoint-choices");

topicInput.addEventListener("input", () => {
  urlField.hidden = topicInput.value.trim().length === 0;
});

let pollTimer = null;

async function startGenerate(mode) {
  generateBtn.disabled = true;
  planBtn.disabled = true;
  const body = {};
  if (mode === "director") body.mode = "director";
  if (topicInput.value.trim()) {
    body.topic = topicInput.value.trim();
    if (urlInput.value.trim()) body.article_url = urlInput.value.trim();
  }
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Could not start generation.");
      generateBtn.disabled = false;
      planBtn.disabled = false;
      return;
    }
    const { job_id } = await res.json();
    watchJob(job_id);
  } catch (e) {
    alert("Could not reach the dashboard server.");
    generateBtn.disabled = false;
    planBtn.disabled = false;
  }
}
generateBtn.addEventListener("click", () => startGenerate("video"));
planBtn.addEventListener("click", () => startGenerate("director"));

function renderJob(job) {
  jobStatusEl.hidden = false;
  jobLog.textContent = job.log.join("\n");
  jobLog.scrollTop = jobLog.scrollHeight;
  const running = job.status === "running";
  generateBtn.disabled = running;
  planBtn.disabled = running;
  if (running) {
    jobSpinner.hidden = false;
    jobStatusText.textContent = "Running…";
  } else if (job.status === "done") {
    jobSpinner.hidden = true;
    jobStatusText.textContent = "Done — see results below.";
    hideCheckpoint();
  } else {
    jobSpinner.hidden = true;
    jobStatusText.textContent = "Failed — see log below.";
    hideCheckpoint();
  }
}

// ---------- checkpoints ----------
let _pendingKey = null;
function hideCheckpoint() {
  checkpointPanel.hidden = true;
  checkpointChoices.innerHTML = "";
  _pendingKey = null;
}

function renderCheckpoint(pending) {
  if (!pending) { hideCheckpoint(); return; }
  const key = pending.name + ":" + (pending.choices || []).map((c) => c.label).join("|");
  if (key === _pendingKey) return; // already rendered this exact prompt
  _pendingKey = key;
  checkpointPanel.hidden = false;
  checkpointPrompt.textContent = pending.prompt || `Choose (${pending.name})`;
  checkpointChoices.innerHTML = "";
  (pending.choices || []).forEach((c, i) => {
    const btn = document.createElement("button");
    btn.className = "checkpoint-choice" + (i === pending.auto_index ? " recommended" : "");
    btn.innerHTML = `
      <div class="checkpoint-choice-label">${escapeHtml(c.label)}${i === pending.auto_index ? ' <span class="rec-tag">recommended</span>' : ""}</div>
      ${c.detail ? `<div class="checkpoint-choice-detail">${escapeHtml(c.detail)}</div>` : ""}
    `;
    btn.addEventListener("click", () => decideCheckpoint(i));
    checkpointChoices.appendChild(btn);
  });
}

async function decideCheckpoint(choice) {
  checkpointChoices.querySelectorAll("button").forEach((b) => (b.disabled = true));
  await fetch("/api/checkpoint/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  hideCheckpoint();
}

async function pollCheckpoint() {
  try {
    const res = await fetch("/api/checkpoint");
    const { pending } = await res.json();
    renderCheckpoint(pending);
  } catch (e) { /* transient */ }
}

function watchJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  let wasRunning = true;
  pollTimer = setInterval(async () => {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) { clearInterval(pollTimer); return; }
    const job = await res.json();
    renderJob(job);
    if (job.status === "running") {
      pollCheckpoint();
    } else {
      clearInterval(pollTimer);
      hideCheckpoint();
      if (wasRunning) loadRuns();
      wasRunning = false;
    }
  }, 1500);
}

async function resumeAnyJob() {
  const res = await fetch("/api/jobs/latest");
  const { job } = await res.json();
  if (job && job.status === "running") watchJob(job.id);
  else if (job) renderJob(job);
}

// ---------- runs grid ----------
const runsGrid = $("#runs-grid");
const runsCount = $("#runs-count");
const emptyState = $("#empty-state");

function qaBadge(report) {
  if (!report) return { cls: "plain", label: "No QA" };
  if (report.overall === "pass") return { cls: "good", label: "Pass" };
  const failCount = (report.items || []).filter((i) => i.result === "fail").length;
  return { cls: "bad", label: `${failCount} gap${failCount === 1 ? "" : "s"}` };
}

function statusChip(status) {
  const map = {
    approved: { cls: "good", label: "Approved" },
    rejected: { cls: "bad", label: "Rejected" },
    pending_review: { cls: "warn", label: "Pending" },
  };
  return map[status] || { cls: "plain", label: status || "unknown" };
}

function slugDate(slug) {
  const m = slug.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : "";
}

function runCard(run) {
  const qa = qaBadge(run.review_report);
  const st = statusChip(run.metadata.status);
  const title = run.metadata.title || run.metadata.hook_text || run.slug;
  const el = document.createElement("div");
  el.className = "run-card";
  el.innerHTML = `
    <div class="run-thumb">
      ${run.thumb_url ? `<img src="${run.thumb_url}" alt="">` : `<div class="no-thumb">No preview</div>`}
      <span class="chip ${qa.cls} qa-badge">${qa.label}</span>
    </div>
    <div class="run-body">
      <div class="run-title">${escapeHtml(title)}</div>
      <div class="run-meta">
        <span class="run-date">${slugDate(run.slug)}</span>
        <span class="chip ${st.cls}">${st.label}</span>
      </div>
    </div>
  `;
  el.addEventListener("click", () => openDetail(run.slug));
  return el;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function loadRuns() {
  const res = await fetch("/api/runs");
  const { runs } = await res.json();
  runsGrid.innerHTML = "";
  runsCount.textContent = runs.length ? `${runs.length} video${runs.length === 1 ? "" : "s"}` : "";
  emptyState.hidden = runs.length > 0;
  runs.forEach((r) => runsGrid.appendChild(runCard(r)));
}

// ---------- detail overlay ----------
const overlay = $("#detail-overlay");
const detailPanel = $("#detail-panel");

function closeDetail() {
  overlay.hidden = true;
  detailPanel.innerHTML = "";
}
overlay.addEventListener("click", (e) => { if (e.target === overlay) closeDetail(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !overlay.hidden) closeDetail(); });

function qaItemRow(item, checklistById) {
  const spec = checklistById[item.id];
  const label = spec ? spec.question : item.id;
  return `
    <div class="qa-item ${item.result}">
      <span class="qa-id">${item.id}</span>
      <div>
        <div>${escapeHtml(label)}</div>
        ${item.result === "fail" ? `<div class="qa-note">${escapeHtml(item.gap_note || "")}</div>` : ""}
      </div>
    </div>
  `;
}

let _checklistById = null;
async function getChecklistById() {
  if (_checklistById) return _checklistById;
  const res = await fetch("/api/checklist");
  const { gate_b } = await res.json();
  _checklistById = {};
  gate_b.forEach((item) => { _checklistById[item.id] = item; });
  return _checklistById;
}

async function openDetail(slug) {
  const res = await fetch(`/api/runs/${slug}`);
  if (!res.ok) return;
  const run = await res.json();
  const meta = run.metadata;
  const report = run.review_report;
  const checklistById = await getChecklistById();

  const qaSection = report ? `
    <div class="detail-block">
      <h4>QA gate</h4>
      <div class="qa-summary">
        <span class="chip ${report.overall === "pass" ? "good" : "bad"}">${report.overall === "pass" ? "All checks passed" : "Blocked"}</span>
      </div>
      <div class="qa-list">
        ${(report.items || []).map((i) => qaItemRow(i, checklistById)).join("")}
      </div>
    </div>
  ` : `<div class="detail-block"><h4>QA gate</h4><div class="detail-text">Not graded (no ANTHROPIC_API_KEY at render time).</div></div>`;

  detailPanel.innerHTML = `
    <button class="detail-close" id="detail-close-btn" aria-label="Close">✕</button>
    ${run.video_url ? `<div class="detail-video"><video src="${run.video_url}" controls playsinline></video></div>` : ""}
    <h3 class="detail-title">${escapeHtml(meta.title || meta.hook_text || slug)}</h3>
    <div class="detail-source"><a href="${meta.source_article}" target="_blank" rel="noopener">${escapeHtml(meta.source_article || "")}</a></div>

    <div class="detail-block">
      <h4>YouTube</h4>
      <div class="detail-text"><strong>${escapeHtml(meta.youtube?.title || "")}</strong>\n\n${escapeHtml(meta.youtube?.description || "")}</div>
    </div>
    <div class="detail-block">
      <h4>Instagram caption</h4>
      <div class="detail-text">${escapeHtml(meta.instagram?.caption || "")}</div>
    </div>

    ${qaSection}

    <div class="detail-actions">
      <button class="btn btn-good" id="approve-btn">Approve</button>
      <button class="btn btn-bad" id="reject-btn">Reject</button>
    </div>
    <div class="status-note">Current status: <strong>${meta.status}</strong></div>
  `;

  $("#detail-close-btn").addEventListener("click", closeDetail);
  $("#approve-btn").addEventListener("click", () => setStatus(slug, "approved"));
  $("#reject-btn").addEventListener("click", () => setStatus(slug, "rejected"));

  overlay.hidden = false;
}

async function setStatus(slug, status) {
  await fetch(`/api/runs/${slug}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  closeDetail();
  loadRuns();
}

// ---------- view tabs ----------
const views = { studio: $("#view-studio"), usage: $("#view-usage"), analytics: $("#view-analytics"), evals: $("#view-evals"), config: $("#view-config") };
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      const active = t === tab;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", String(active));
    });
    Object.entries(views).forEach(([name, el]) => { el.hidden = name !== tab.dataset.view; });
    if (tab.dataset.view === "config") loadConfig();
    if (tab.dataset.view === "evals") loadEvals();
    if (tab.dataset.view === "usage") loadUsage();
    if (tab.dataset.view === "analytics") loadAnalytics();
  });
});

// ---------- analytics ----------
function fmtNum(n) { return !n ? "0" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }

async function loadAnalytics() {
  const tiles = $("#analytics-tiles"), rows = $("#analytics-rows"), empty = $("#analytics-empty");
  const banner = $("#analytics-banner"), src = $("#analytics-source");
  tiles.innerHTML = ""; rows.innerHTML = "";
  let d;
  try { d = await (await fetch("/api/analytics")).json(); }
  catch { tiles.innerHTML = `<div class="muted">Failed to load analytics.</div>`; return; }
  banner.hidden = d.source !== "dummy";
  src.textContent = `${d.platform} · ${d.source === "dummy" ? "sample data" : "live"} · ${d.totals.videos} videos`;
  const t = d.totals;
  const tileData = [
    ["Total views", fmtNum(t.views), "all videos"],
    ["Avg retention", (t.avg_retention_pct || 0) + "%", "average view %"],
    ["Watch hours", fmtNum(Math.round(t.watch_hours)), "estimated"],
    ["New followers", fmtNum(t.new_followers), "attributed"],
  ];
  tiles.innerHTML = tileData.map(([label, big, sub]) =>
    `<div class="usage-tile"><div class="usage-tile-label">${label}</div><div class="usage-tile-value">${big}</div><div class="usage-tile-sub">${sub}</div></div>`).join("");

  const vids = d.videos || [];
  empty.hidden = vids.length > 0;
  rows.innerHTML = vids.map(v => {
    const pred = v.predicted_score != null
      ? `<span class="chip ${v.predicted_score >= 70 ? "chip-good" : v.predicted_score >= 55 ? "" : "chip-warn"}">${v.predicted_score}</span>`
      : `<span class="muted">—</span>`;
    return `<tr>
      <td class="mono">${escapeHtml(v.date || "")}</td>
      <td class="usage-title" title="${escapeHtml(v.title || "")}">${escapeHtml(v.title || v.slug)}</td>
      <td class="num">${pred}</td>
      <td class="num">${fmtNum(v.views)}</td>
      <td class="num">${v.avg_view_pct}%</td>
      <td class="num">${fmtNum(v.likes)}</td>
      <td class="num">${fmtNum(v.comments)}</td>
      <td class="num">${fmtNum(v.shares)}</td>
      <td class="num">${fmtNum(v.new_followers)}</td>
    </tr>`;
  }).join("");
}

// ---------- usage ----------
function fmtMoney(v) { return v === null || v === undefined ? "—" : "$" + v.toFixed(v < 1 ? 3 : 2); }
function fmtTok(n) { return !n ? "0" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }

async function loadUsage() {
  const tiles = $("#usage-tiles"), rows = $("#usage-rows"), empty = $("#usage-empty");
  tiles.innerHTML = ""; rows.innerHTML = "";
  let data;
  try { data = await (await fetch("/api/usage")).json(); }
  catch { tiles.innerHTML = `<div class="muted">Failed to load usage.</div>`; return; }
  const t = data.totals || {};
  const spentThisMonth = (data.videos || []).filter(v => v.tracked && (v.date || "").slice(0, 7) === new Date().toISOString().slice(0, 7))
    .reduce((a, v) => a + (v.cost_usd || 0), 0);
  const avg = t.videos_tracked ? t.cost_usd / t.videos_tracked : 0;
  const tileData = [
    ["Total spend", fmtMoney(t.cost_usd), `${t.videos_tracked || 0} videos tracked`],
    ["This month", fmtMoney(spentThisMonth), "current calendar month"],
    ["Avg / video", fmtMoney(avg), "across tracked videos"],
    ["Tokens (all)", fmtTok((t.input_tokens || 0) + (t.output_tokens || 0)), `${fmtTok(t.input_tokens)} in · ${fmtTok(t.output_tokens)} out`],
  ];
  tiles.innerHTML = tileData.map(([label, big, sub]) =>
    `<div class="usage-tile"><div class="usage-tile-label">${label}</div><div class="usage-tile-value">${big}</div><div class="usage-tile-sub">${sub}</div></div>`).join("");

  const vids = data.videos || [];
  empty.hidden = vids.length > 0;
  rows.innerHTML = vids.map(v => {
    const chips = (v.providers || []).map(p =>
      `<span class="chip ${["anthropic", "openrouter", "elevenlabs", "tavily"].includes(p) ? "chip-paid" : ""}">${escapeHtml(p)}</span>`).join("");
    const unpriced = v.has_unpriced ? ` <span class="chip chip-warn">unpriced</span>` : "";
    const cls = v.tracked ? "" : "usage-untracked";
    const cost = v.tracked ? fmtMoney(v.cost_usd) : `<span class="muted">not tracked</span>`;
    const toggle = v.tracked ? `<button class="btn-link usage-detail-btn" data-slug="${escapeHtml(v.slug)}">details ▾</button>` : "";
    return `<tr class="${cls}">
      <td class="mono">${escapeHtml(v.date || "")}</td>
      <td class="usage-title" title="${escapeHtml(v.title || "")}">${escapeHtml(v.title || v.slug)}</td>
      <td class="num">${fmtTok(v.input_tokens)}</td>
      <td class="num">${fmtTok(v.output_tokens)}</td>
      <td class="num">${v.llm_calls || 0}</td>
      <td>${chips}${unpriced}</td>
      <td class="num">${cost}</td>
      <td>${toggle}</td>
    </tr>
    <tr class="usage-detail-row" id="detail-${escapeHtml(v.slug)}" hidden><td colspan="8"></td></tr>`;
  }).join("");

  rows.querySelectorAll(".usage-detail-btn").forEach(btn =>
    btn.addEventListener("click", () => toggleUsageDetail(btn.dataset.slug, btn)));
}

async function toggleUsageDetail(slug, btn) {
  const row = document.getElementById("detail-" + slug);
  if (!row) return;
  if (!row.hidden) { row.hidden = true; btn.textContent = "details ▾"; return; }
  btn.textContent = "details ▴";
  const cell = row.querySelector("td");
  cell.innerHTML = `<div class="muted">Loading…</div>`;
  row.hidden = false;
  let d;
  try { d = await (await fetch("/api/usage/" + encodeURIComponent(slug))).json(); }
  catch { cell.innerHTML = `<div class="muted">Failed to load detail.</div>`; return; }
  const sessions = (d.sessions || []).map(s => {
    const stageRows = (s.stages || []).map(g => {
      const cost = g.unpriced ? `<span class="chip chip-warn">unpriced</span>` : (g.cost_usd ? fmtMoney(g.cost_usd) : "—");
      const extra = g.characters ? `${g.characters} chars` : g.requests ? `${g.requests} req` : "";
      return `<tr>
        <td>${escapeHtml(g.stage)}</td>
        <td class="num">${g.calls}</td>
        <td class="mono">${escapeHtml((g.models || []).join(", ") || g.providers.join(", "))}</td>
        <td class="num">${fmtTok(g.input_tokens)}</td>
        <td class="num">${fmtTok(g.output_tokens)}</td>
        <td class="num">${extra || cost}${extra ? " · " + cost : ""}</td>
      </tr>`;
    }).join("");
    return `<div class="usage-session">
      <div class="usage-session-head"><strong>${escapeHtml(s.phase || "")}</strong>
        <span class="muted">${escapeHtml((s.started_at || "").replace("T", " ").replace("Z", ""))}</span>
        <span class="usage-session-cost">${fmtMoney(s.cost_usd)}</span></div>
      <table class="usage-stage-table"><thead><tr>
        <th>Stage</th><th class="num">Calls</th><th>Model</th><th class="num">In</th><th class="num">Out</th><th class="num">Cost</th>
      </tr></thead><tbody>${stageRows}</tbody></table>
    </div>`;
  }).join("");
  const free = (d.free_stages || []).map(f => `<span class="chip">${escapeHtml(f)}</span>`).join(" ");
  cell.innerHTML = sessions + `<div class="usage-free"><span class="muted">Free · local ($0):</span> ${free}</div>`;
}

// ---------- evals ----------
const evalsList = $("#evals-list");
const evalsEmpty = $("#evals-empty");

function evalOutputPreview(opt) {
  if (!opt.ok) return `<span class="eval-err">failed: ${escapeHtml(opt.error || "")}</span>`;
  let text;
  try { text = JSON.stringify(opt.output, null, 2); }
  catch { text = String(opt.output); }
  return `<pre class="eval-output">${escapeHtml(text)}</pre>`;
}

function evalStationCard(slug, st) {
  const picked = st.pick;
  const wrap = document.createElement("div");
  wrap.className = "eval-station";
  const sides = ["A", "B"].map((lbl) => {
    const opt = st.options[lbl] || { ok: false, error: "missing" };
    const isWinner = picked && picked.choice === lbl;
    const providerTag = st.reveal ? `<span class="eval-provider">${escapeHtml(st.reveal[lbl])}</span>` : "";
    return `
      <div class="eval-side ${isWinner ? "winner" : ""}">
        <div class="eval-side-head">
          <span class="eval-label">${lbl}</span>
          ${providerTag}
          ${isWinner ? '<span class="chip good">winner</span>' : ""}
        </div>
        ${evalOutputPreview(opt)}
        ${picked ? "" : `<button class="btn eval-pick" data-slug="${slug}" data-station="${st.station}" data-choice="${lbl}">Pick ${lbl}</button>`}
      </div>`;
  }).join("");
  wrap.innerHTML = `
    <div class="eval-station-head">
      <h4>${escapeHtml(st.station)}</h4>
      ${picked ? `<span class="muted">picked ${st.reveal[picked.choice]}</span>` : `<span class="muted">choose blind</span>`}
    </div>
    <div class="eval-sides">${sides}</div>`;
  wrap.querySelectorAll(".eval-pick").forEach((b) => {
    b.addEventListener("click", () => pickEval(b.dataset.slug, b.dataset.station, b.dataset.choice));
  });
  return wrap;
}

async function loadEvals() {
  const res = await fetch("/api/evals");
  const { evals } = await res.json();
  evalsList.innerHTML = "";
  evalsEmpty.hidden = evals.length > 0;
  evals.forEach((run) => {
    const block = document.createElement("div");
    block.className = "eval-run";
    const head = document.createElement("div");
    head.className = "eval-run-head";
    head.innerHTML = `<div class="eval-run-title">${escapeHtml(run.story_title)}</div><span class="muted">${escapeHtml(run.slug)}</span>`;
    block.appendChild(head);
    run.stations.forEach((st) => block.appendChild(evalStationCard(run.slug, st)));
    evalsList.appendChild(block);
  });
}

async function pickEval(slug, station, choice) {
  await fetch(`/api/evals/${slug}/${station}/pick`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  loadEvals();
}

// ---------- config page ----------
const CHECKPOINT_LABELS = {
  story_pick: ["Story pick", "Strategist's top-3 stories → which one to make"],
  hook_pick: ["Hook pick", "3 hook variants → which one leads"],
  script_approval: ["Script approval", "Writer + Critic sign-off before voicing"],
  storyboard_approval: ["Storyboard approval", "Director's beat plan before rendering"],
  publish: ["Publish", "Post the finished video to YouTube / Instagram"],
};
const PROVIDER_LABELS = {
  scout: ["Scout / Strategist", "story ranking"],
  writer: ["Writer", "script + hooks"],
  reviewer: ["Reviewer", "vision QA gate"],
  voice: ["Voice", "narration TTS"],
  broll: ["B-roll", "visual sourcing"],
};
const PROVIDER_OPTION_LABELS = {
  ollama: "Ollama — local, free",
  openrouter: "OpenRouter — free API credits",
  anthropic: "Claude — paid API",
  skip: "Skip — no QA gate",
  kokoro: "Kokoro — local, free",
  elevenlabs: "ElevenLabs — paid API",
  say: "macOS say — local fallback",
  pexels: "Pexels — free stock",
};

let _configState = null;

function checkpointRow(key, value) {
  const [label, desc] = CHECKPOINT_LABELS[key] || [key, ""];
  const row = document.createElement("div");
  row.className = "config-row";
  row.innerHTML = `
    <div class="config-row-text">
      <div class="config-row-label">${escapeHtml(label)}</div>
      <div class="config-row-desc">${escapeHtml(desc)}</div>
    </div>
    <label class="switch">
      <input type="checkbox" data-group="checkpoints" data-key="${key}" ${value === "auto" ? "checked" : ""}>
      <span class="switch-track"></span>
      <span class="switch-label">${value === "auto" ? "Auto" : "Manual"}</span>
    </label>
  `;
  row.querySelector("input").addEventListener("change", (e) => {
    row.querySelector(".switch-label").textContent = e.target.checked ? "Auto" : "Manual";
  });
  return row;
}

function providerRow(key, value, options) {
  const [label, desc] = PROVIDER_LABELS[key] || [key, ""];
  const row = document.createElement("div");
  row.className = "config-row";
  row.innerHTML = `
    <div class="config-row-text">
      <div class="config-row-label">${escapeHtml(label)}</div>
      <div class="config-row-desc">${escapeHtml(desc)}</div>
    </div>
    <select data-group="providers" data-key="${key}">
      ${options.map((o) => `<option value="${o}" ${o === value ? "selected" : ""}>${escapeHtml(PROVIDER_OPTION_LABELS[o] || o)}</option>`).join("")}
    </select>
  `;
  return row;
}

async function loadConfig() {
  const res = await fetch("/api/config");
  const data = await res.json();
  _configState = data;
  const controls = data.controls || {};
  const options = data.control_options || {};

  const cpRows = $("#checkpoint-rows");
  cpRows.innerHTML = "";
  Object.keys(options.checkpoints || {}).forEach((key) => {
    cpRows.appendChild(checkpointRow(key, (controls.checkpoints || {})[key] || "auto"));
  });

  const pvRows = $("#provider-rows");
  pvRows.innerHTML = "";
  Object.entries(options.providers || {}).forEach(([key, opts]) => {
    pvRows.appendChild(providerRow(key, (controls.providers || {})[key] || opts[0], opts));
  });
}

async function saveConfig() {
  const body = { checkpoints: {}, providers: {} };
  document.querySelectorAll('#checkpoint-rows input[type="checkbox"]').forEach((el) => {
    body.checkpoints[el.dataset.key] = el.checked ? "auto" : "manual";
  });
  document.querySelectorAll("#provider-rows select").forEach((el) => {
    body.providers[el.dataset.key] = el.value;
  });
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const note = $("#config-saved-note");
  note.textContent = res.ok ? "Saved ✓" : "Save failed";
  note.hidden = false;
  setTimeout(() => { note.hidden = true; }, 2500);
}
$("#config-save").addEventListener("click", saveConfig);

// ---------- init ----------
loadRuns();
resumeAnyJob();
