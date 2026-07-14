const $ = (sel) => document.querySelector(sel);

// ---------- toast ----------
function toast(msg, kind = "") {
  const wrap = $("#toast-wrap");
  if (!wrap) return;
  const ico = kind === "good" ? "✓" : kind === "bad" ? "✕" : "◆";
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<span class="toast-ico">${ico}</span><span>${msg}</span>`;
  wrap.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 260);
  }, 3200);
}

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

  const ytTitle = meta.youtube?.title || "";
  const ytDesc = meta.youtube?.description || "";
  const igCap = meta.instagram?.caption || "";
  const vScore = meta.virality?.score;
  const vBadge = vScore != null
    ? `<span class="chip ${vScore >= 70 ? "chip-good" : vScore >= 55 ? "" : "chip-warn"}" title="predicted virality">🔥 ${vScore}/100</span>` : "";

  detailPanel.innerHTML = `
    <button class="detail-close" id="detail-close-btn" aria-label="Close">✕</button>
    ${run.video_url ? `<div class="detail-video"><video src="${run.video_url}" controls playsinline></video></div>` : ""}
    <h3 class="detail-title">${escapeHtml(meta.title || meta.hook_text || slug)} ${vBadge}</h3>
    <div class="detail-source"><a href="${meta.source_article}" target="_blank" rel="noopener">${escapeHtml(meta.source_article || "")}</a></div>

    <div class="detail-quickbar">
      ${run.video_url ? `<a class="btn btn-ghost" href="${run.video_url}" download="${slug}.mp4">⬇ Download video</a>` : ""}
      <button class="btn btn-ghost copy-btn" data-copy="yt">Copy YouTube</button>
      <button class="btn btn-ghost copy-btn" data-copy="ig">Copy caption</button>
      <button class="btn btn-ghost" id="social-from-run">✍ Make LinkedIn/X posts</button>
    </div>

    <div class="detail-block">
      <div class="detail-block-head"><h4>YouTube</h4><button class="btn-link copy-btn" data-copy="yt">copy</button></div>
      <div class="detail-text" id="yt-text"><strong>${escapeHtml(ytTitle)}</strong>\n\n${escapeHtml(ytDesc)}</div>
    </div>
    <div class="detail-block">
      <div class="detail-block-head"><h4>Instagram caption</h4><button class="btn-link copy-btn" data-copy="ig">copy</button></div>
      <div class="detail-text" id="ig-text">${escapeHtml(igCap)}</div>
    </div>

    ${qaSection}

    <div class="detail-actions">
      <button class="btn btn-good" id="approve-btn">Approve</button>
      <button class="btn btn-bad" id="reject-btn">Reject</button>
      <button class="btn btn-primary" id="publish-btn">Publish…</button>
    </div>
    <div class="publish-result" id="publish-result" hidden></div>
    <div class="status-note">Current status: <strong>${meta.status}</strong></div>
  `;

  const copyMap = { yt: `${ytTitle}\n\n${ytDesc}`, ig: igCap };
  detailPanel.querySelectorAll(".copy-btn").forEach((b) =>
    b.addEventListener("click", () => copyText(copyMap[b.dataset.copy], b)));
  $("#detail-close-btn").addEventListener("click", closeDetail);
  $("#approve-btn").addEventListener("click", () => setStatus(slug, "approved"));
  $("#reject-btn").addEventListener("click", () => setStatus(slug, "rejected"));
  $("#publish-btn").addEventListener("click", () => publishRun(slug));
  $("#social-from-run").addEventListener("click", () => { closeDetail(); openSocialForSlug(slug, meta.title || slug); });

  overlay.hidden = false;
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text || "");
    const old = btn.textContent; btn.textContent = "copied ✓";
    setTimeout(() => (btn.textContent = old), 1400);
    toast("Copied to clipboard", "good");
  } catch { /* clipboard blocked */ }
}

async function publishRun(slug) {
  const box = $("#publish-result");
  const status = await (await fetch("/api/integrations")).json();
  const live = status.publish_live && (status.youtube || status.instagram);
  const label = live ? "Publish LIVE now?" : "No publish keys / PUBLISH_LIVE off — run a DRY RUN (shows what would post)?";
  if (!confirm(label)) return;
  box.hidden = false; box.innerHTML = `<span class="muted">Publishing…</span>`;
  try {
    const r = await (await fetch(`/api/publish/${slug}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ live }) })).json();
    box.innerHTML = (r.results || []).map((x) => {
      const ok = x.status === "published";
      const cls = ok ? "chip-good" : x.status === "dry_run" ? "" : "chip-warn";
      const detail = x.url ? ` → <a href="${x.url}" target="_blank">${x.url}</a>`
        : x.reason ? ` — ${escapeHtml(x.reason)}` : "";
      return `<div><span class="chip ${cls}">${x.platform}: ${x.status}</span>${detail}</div>`;
    }).join("");
  } catch { box.innerHTML = `<span class="chip chip-warn">publish failed</span>`; }
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
const views = { studio: $("#view-studio"), usage: $("#view-usage"), social: $("#view-social"), analytics: $("#view-analytics"), evals: $("#view-evals"), config: $("#view-config") };
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
    if (tab.dataset.view === "social") loadSocial();
  });
});

// ---------- integration status strip ----------
const INTEGRATION_LABELS = {
  openrouter: "OpenRouter", anthropic: "Anthropic", elevenlabs: "Voice", pexels: "Pexels",
  tavily: "Tavily", flux: "FLUX", youtube: "YouTube", instagram: "Instagram", typefully: "Typefully",
};
async function loadIntegrations() {
  const strip = $("#integration-strip");
  if (!strip) return;
  let s;
  try { s = await (await fetch("/api/integrations")).json(); } catch { return; }
  const order = ["openrouter", "anthropic", "elevenlabs", "flux", "pexels", "tavily", "youtube", "instagram", "typefully"];
  strip.innerHTML = order.map((k) => {
    const on = s[k];
    return `<span class="int-chip ${on ? "int-on" : "int-off"}" title="${on ? "configured" : "not configured — add key in .env"}">
      <span class="int-dot"></span>${INTEGRATION_LABELS[k]}</span>`;
  }).join("") + (s.publish_live ? `<span class="int-chip int-live">● PUBLISH LIVE</span>` : "");
}

// ---------- social posts ----------
async function loadSocial() {
  const sel = $("#social-run-select");
  if (sel && sel.options.length <= 1) {
    try {
      const d = await (await fetch("/api/runs")).json();
      (d.runs || []).forEach((r) => {
        const o = document.createElement("option");
        o.value = r.slug; o.textContent = r.metadata?.title || r.slug;
        sel.appendChild(o);
      });
    } catch { /* ignore */ }
  }
}
function openSocialForSlug(slug, title) {
  document.querySelector('.tab[data-view="social"]').click();
  const sel = $("#social-run-select");
  const set = () => { sel.value = slug; generateSocial(); };
  if (sel.options.length <= 1) setTimeout(set, 300); else set();
}
async function generateSocial() {
  const out = $("#social-output");
  const slug = $("#social-run-select").value;
  const topic = $("#social-topic").value.trim();
  const platforms = [];
  if ($("#social-li").checked) platforms.push("linkedin");
  if ($("#social-tw").checked) platforms.push("twitter");
  if (!slug && !topic) { out.innerHTML = `<div class="muted">Pick a video or type a topic first.</div>`; return; }
  if (!platforms.length) { out.innerHTML = `<div class="muted">Select at least one platform.</div>`; return; }
  out.innerHTML = `<div class="muted">Writing on-brand posts…</div>`;
  let r;
  try {
    r = await (await fetch("/api/social/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: slug || undefined, topic: topic || undefined, platforms }) })).json();
  } catch { out.innerHTML = `<div class="muted">Generation failed.</div>`; return; }
  let html = "";
  if (r.linkedin) {
    html += `<div class="social-card"><div class="social-card-head"><h4>LinkedIn</h4>
      <div><span class="muted">${r.linkedin.length} chars</span>
      <button class="btn-link" onclick="copyText(${JSON.stringify(r.linkedin).replace(/"/g, "&quot;")}, this)">copy</button>
      <button class="btn-link" onclick="scheduleSocial(this)" data-content="${encodeURIComponent(r.linkedin)}">schedule</button></div></div>
      <div class="social-text">${escapeHtml(r.linkedin)}</div></div>`;
  }
  if (r.twitter && r.twitter.length) {
    const thread = r.twitter.map((t, i) => `<div class="tweet"><span class="tweet-n">${i + 1}</span><span>${escapeHtml(t)}</span><span class="tweet-len">${t.length}</span></div>`).join("");
    const full = r.twitter.join("\n\n");
    html += `<div class="social-card"><div class="social-card-head"><h4>X / Twitter thread</h4>
      <div><button class="btn-link" onclick="copyText(${JSON.stringify(full).replace(/"/g, "&quot;")}, this)">copy all</button>
      <button class="btn-link" onclick="scheduleSocial(this)" data-content="${encodeURIComponent(full)}">schedule</button></div></div>
      <div class="thread">${thread}</div></div>`;
  }
  out.innerHTML = html || `<div class="muted">No posts generated.</div>`;
}
async function scheduleSocial(btn) {
  const content = decodeURIComponent(btn.dataset.content);
  btn.textContent = "scheduling…";
  const r = await (await fetch("/api/social/schedule", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, publish_at: "next-free-slot" }) })).json();
  btn.textContent = r.status === "scheduled" ? "scheduled ✓" : (r.status === "not_configured" ? "add TYPEFULLY_API_KEY" : "failed");
  toast(r.status === "scheduled" ? "Scheduled to Typefully" : (r.status === "not_configured" ? "Add TYPEFULLY_API_KEY to .env" : "Schedule failed"),
    r.status === "scheduled" ? "good" : "bad");
  setTimeout(() => (btn.textContent = "schedule"), 2500);
}

// ---------- analytics ----------
function fmtNum(n) { return !n ? "0" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }

const TARGET_LABEL = { style_guide: "Style guide", hook_formulas: "Hook formulas",
  virality_rubric: "Virality rubric", director_realism: "Director realism", scouting: "Scouting" };

function renderInsights(r) {
  const body = $("#insights-body"), meta = $("#insights-meta");
  if (!r || r.exists === false) { body.innerHTML = `<div class="muted">No insights yet — click Generate.</div>`; return; }
  meta.textContent = `— ${r.videos_analyzed || 0} videos · ${r.data_source === "live" ? "live data" : "sample data (illustrative)"}${r.generated_on ? " · " + r.generated_on : ""}`;
  const patterns = (r.winning_patterns || []).map((p) => `<li>${escapeHtml(p)}</li>`).join("");
  const gaps = (r.recurring_qa_gaps || []).map((g) =>
    `<li><span class="chip chip-warn">${escapeHtml(g.gate)} ×${g.count}</span> ${escapeHtml(g.fix || "")}</li>`).join("");
  const props = (r.proposals || []).map((p) => {
    const cc = p.confidence === "high" ? "chip-good" : p.confidence === "low" ? "chip-warn" : "";
    const canApply = ["style_guide", "hook_formulas", "virality_rubric", "director_realism", "scouting"].includes(p.target);
    const applyBtn = canApply
      ? `<button class="btn-link" data-proposal="${encodeURIComponent(JSON.stringify(p))}" onclick="applyProposal(this)" title="append to config/learnings.md — steers the next run">apply →</button>` : "";
    return `<div class="proposal">
      <div class="proposal-head"><span class="chip">${escapeHtml(TARGET_LABEL[p.target] || p.target)}</span>
        <span class="chip ${cc}">${escapeHtml(p.confidence || "")}</span><span style="margin-left:auto">${applyBtn}</span></div>
      <div class="proposal-change">${escapeHtml(p.change || "")}</div>
      <div class="proposal-why muted">${escapeHtml(p.rationale || "")}</div></div>`;
  }).join("");
  body.innerHTML = `
    <div class="insight-headline">${escapeHtml(r.headline || "")}</div>
    ${r.calibration ? `<div class="insight-cal"><strong>Calibration:</strong> ${escapeHtml(r.calibration)}</div>` : ""}
    <div class="insight-grid">
      <div class="insight-col"><h5>Winning patterns</h5><ul>${patterns || "<li class='muted'>—</li>"}</ul></div>
      <div class="insight-col"><h5>Recurring QA gaps</h5><ul>${gaps || "<li class='muted'>—</li>"}</ul></div>
    </div>
    ${r.cost_note ? `<div class="insight-cal"><strong>Cost:</strong> ${escapeHtml(r.cost_note)}</div>` : ""}
    <h5 class="proposals-title">Proposed brain edits (review before applying)</h5>
    <div class="proposals">${props || "<div class='muted'>No proposals.</div>"}</div>`;
}

async function loadInsights() {
  try { renderInsights(await (await fetch("/api/analyst")).json()); }
  catch { $("#insights-body").innerHTML = `<div class="muted">Failed to load insights.</div>`; }
}
async function runInsights() {
  const btn = $("#insights-run"), body = $("#insights-body");
  btn.disabled = true; btn.textContent = "Analyzing…";
  body.innerHTML = `<div class="muted">Reading performance across all videos and correlating…</div>`;
  try { renderInsights(await (await fetch("/api/analyst/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json()); }
  catch { body.innerHTML = `<div class="muted">Analysis failed.</div>`; }
  btn.disabled = false; btn.textContent = "Regenerate insights";
}

async function loadAnalytics() {
  const tiles = $("#analytics-tiles"), rows = $("#analytics-rows"), empty = $("#analytics-empty");
  const banner = $("#analytics-banner"), src = $("#analytics-source");
  loadInsights();
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
  toast(res.ok ? "Configuration saved" : "Save failed", res.ok ? "good" : "bad");
}
$("#config-save").addEventListener("click", saveConfig);

// ---------- autopilot + queue ----------
async function loadAutopilot() {
  let s;
  try { s = await (await fetch("/api/autopilot")).json(); } catch { return; }
  $("#ap-enabled").checked = !!s.enabled;
  if (s.time) $("#ap-time").value = s.time;
  const last = s.last_run_date
    ? `last run ${s.last_run_date} — ${s.last_ok ? "✓ " + (s.last_slug || "") : "✗ " + (s.last_error || "failed")}`
    : "never run yet";
  $("#ap-status").innerHTML = `${last}<br>next: <strong>${escapeHtml(s.next_queued || "auto-scout")}</strong> · ${s.queued_count || 0} queued`;
}
async function saveAutopilot() {
  await fetch("/api/autopilot/config", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: $("#ap-enabled").checked, time: $("#ap-time").value }) });
  loadAutopilot();
  toast($("#ap-enabled").checked ? `Autopilot on — daily at ${$("#ap-time").value}` : "Autopilot off", "good");
}
async function runAutopilotNow() {
  const btn = $("#ap-run-now"); btn.disabled = true; btn.textContent = "Starting…";
  try {
    const r = await (await fetch("/api/autopilot/run", { method: "POST" })).json();
    if (r.job_id) watchJob(r.job_id);   // stream into the existing job log
  } catch {}
  setTimeout(() => { btn.disabled = false; btn.textContent = "Run once now"; loadRuns(); }, 1500);
}
async function loadQueue() {
  let d;
  try { d = await (await fetch("/api/queue")).json(); } catch { return; }
  const list = $("#queue-list");
  const items = d.items || [];
  if (!items.length) { list.innerHTML = `<div class="muted queue-empty">Queue empty — autopilot will auto-scout.</div>`; return; }
  list.innerHTML = items.map((i) => {
    const done = i.status === "done";
    return `<div class="queue-item ${done ? "queue-done" : ""}">
      <span class="queue-status">${done ? "✓" : "•"}</span>
      <span class="queue-topic" title="${escapeHtml(i.note || "")}">${escapeHtml(i.topic)}</span>
      ${done ? "" : `<button class="btn-link" onclick="promoteQueue('${i.id}')">↑ next</button>`}
      <button class="btn-link queue-x" onclick="removeQueue('${i.id}')">✕</button>
    </div>`;
  }).join("");
}
async function addQueue() {
  const inp = $("#queue-topic"); const topic = inp.value.trim();
  if (!topic) return;
  await fetch("/api/queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic }) });
  inp.value = ""; loadQueue(); loadAutopilot();
  toast("Added to queue", "good");
}
async function promoteQueue(id) { await fetch(`/api/queue/${id}/promote`, { method: "POST" }); loadQueue(); loadAutopilot(); }
async function removeQueue(id) { await fetch(`/api/queue/${id}`, { method: "DELETE" }); loadQueue(); loadAutopilot(); }

async function applyProposal(btn) {
  const p = JSON.parse(decodeURIComponent(btn.dataset.proposal));
  btn.disabled = true; btn.textContent = "applying…";
  try {
    const r = await (await fetch("/api/analyst/apply", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal: p }) })).json();
    btn.textContent = r.ok ? "applied ✓" : "failed";
    toast(r.ok ? "Proposal applied to the pipeline brain" : "Apply failed", r.ok ? "good" : "bad");
  } catch { btn.textContent = "failed"; toast("Apply failed", "bad"); }
}

// ---------- init ----------
loadRuns();
resumeAnyJob();
loadIntegrations();
loadAutopilot();
loadQueue();
{
  $("#ap-enabled") && $("#ap-enabled").addEventListener("change", saveAutopilot);
  $("#ap-time") && $("#ap-time").addEventListener("change", saveAutopilot);
  $("#ap-run-now") && $("#ap-run-now").addEventListener("click", runAutopilotNow);
  $("#queue-add") && $("#queue-add").addEventListener("click", addQueue);
  $("#queue-topic") && $("#queue-topic").addEventListener("keydown", (e) => { if (e.key === "Enter") addQueue(); });
}
document.addEventListener("DOMContentLoaded", () => {
  const sg = $("#social-generate");
  if (sg) sg.addEventListener("click", generateSocial);
});
// DOMContentLoaded may have already fired (script at end of body) — wire directly too.
{
  const sg = $("#social-generate");
  if (sg) sg.addEventListener("click", generateSocial);
  const ir = $("#insights-run");
  if (ir) ir.addEventListener("click", runInsights);
}
