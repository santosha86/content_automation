"""Signal dashboard: local control panel for the content pipeline.

Run: uvicorn pipeline.ui.server:app --port 8420
(or `make dashboard`)
"""
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..util import ROOT

app = FastAPI(title="Signal Dashboard")

REVIEW_DIR = ROOT / "output" / "review"
STATIC_DIR = Path(__file__).parent / "static"

_job_id_counter = itertools.count(1)
_jobs: dict[int, dict] = {}
_jobs_lock = threading.Lock()


def _run_env() -> dict:
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
    # Tells checkpoints.py to pause manual stages for a dashboard decision (vs TTY/auto).
    env["DASHBOARD_RUN"] = "1"
    return env


def _run_job(job_id: int, args: list[str], module: str = "pipeline.run") -> None:
    job = _jobs[job_id]
    proc = subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=str(ROOT), env=_run_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    for line in proc.stdout:
        with _jobs_lock:
            job["log"].append(line.rstrip("\n"))
    proc.wait()
    with _jobs_lock:
        job["status"] = "done" if proc.returncode == 0 else "error"
        job["finished_at"] = time.time()


@app.post("/api/generate")
def generate(body: dict = None):
    body = body or {}
    # mode: "video" = full render (pipeline.run) · "director" = plan a storyboard (pipeline.plan)
    module = "pipeline.plan" if body.get("mode") == "director" else "pipeline.run"
    args = []
    if body.get("topic"):
        args += ["--topic", body["topic"]]
        if body.get("article_url"):
            args += ["--article-url", body["article_url"]]

    with _jobs_lock:
        running = [j for j in _jobs.values() if j["status"] == "running"]
        if running:
            raise HTTPException(409, "A generation job is already running.")
        job_id = next(_job_id_counter)
        _jobs[job_id] = {"id": job_id, "status": "running", "log": [], "started_at": time.time(), "finished_at": None}

    threading.Thread(target=_run_job, args=(job_id, args, module), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/latest")
def latest_job():
    with _jobs_lock:
        if not _jobs:
            return {"job": None}
        job = max(_jobs.values(), key=lambda j: j["started_at"])
        return {"job": job}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: int):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        return job


def _load_run(slug: str) -> dict:
    folder = REVIEW_DIR / slug
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, "run not found")
    meta = json.loads(meta_path.read_text())
    report_path = folder / "review_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    has_video = (folder / f"{slug}.mp4").exists()
    has_thumb = (folder / "thumb.jpg").exists()
    return {
        "slug": slug,
        "metadata": meta,
        "review_report": report,
        "video_url": f"/media/{slug}/video" if has_video else None,
        "thumb_url": f"/media/{slug}/thumb" if has_thumb else None,
    }


@app.get("/api/runs")
def list_runs():
    if not REVIEW_DIR.exists():
        return {"runs": []}
    slugs = sorted((p.name for p in REVIEW_DIR.iterdir() if p.is_dir()), reverse=True)
    return {"runs": [_load_run(s) for s in slugs]}


@app.get("/api/runs/{slug}")
def get_run(slug: str):
    return _load_run(slug)


@app.post("/api/runs/{slug}/status")
def set_run_status(slug: str, body: dict):
    status = body.get("status")
    if status not in ("approved", "rejected", "pending_review"):
        raise HTTPException(400, "invalid status")
    meta_path = REVIEW_DIR / slug / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, "run not found")
    meta = json.loads(meta_path.read_text())
    meta["status"] = status
    meta_path.write_text(json.dumps(meta, indent=2))
    return {"ok": True}


RUNS_DIR = ROOT / "output" / "runs"

# Free/local stages that never cost anything — listed in the detail view as "$0 · local"
# so the drill-down accounts for the whole pipeline, not just the paid calls.
FREE_STAGES = ["strategist.github_scrape", "visuals.flux", "visuals.pexels",
               "voice.kokoro", "editor.assemble", "editor.transcribe", "packager", "screencap"]


def _pricing() -> dict:
    path = ROOT / "config" / "pricing.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _price_record(rec: dict, pricing: dict):
    """(cost_usd, priced) for one usage record. priced=False => 'unpriced' (unknown model),
    distinct from a real $0 (local/free). Ollama is always a real $0."""
    kind = rec.get("kind")
    if kind == "llm":
        if rec.get("provider") == "ollama":
            return 0.0, True
        row = (pricing.get("llm") or {}).get(rec.get("model", ""))
        if not row:
            return None, False
        cost = (rec.get("input_tokens", 0) / 1e6) * row.get("input", 0) \
             + (rec.get("output_tokens", 0) / 1e6) * row.get("output", 0)
        return cost, True
    if kind == "tts":
        row = (pricing.get("tts") or {}).get(rec.get("provider", ""))
        if not row:
            return None, False
        return (rec.get("characters", 0) / 1000.0) * row.get("per_1k_chars", 0), True
    if kind == "search":
        row = (pricing.get("search") or {}).get(rec.get("provider", ""))
        if not row:
            return None, False
        return rec.get("requests", 0) * row.get("per_request", 0), True
    return None, False


def _iter_records(doc: dict):
    for session in doc.get("sessions", []):
        for rec in session.get("records", []):
            yield session, rec


def _summarize_usage(doc: dict, pricing: dict) -> dict:
    cost, in_tok, out_tok, llm_calls, unpriced = 0.0, 0, 0, 0, False
    providers = set()
    for _, rec in _iter_records(doc):
        providers.add(rec.get("provider", "?"))
        if rec.get("kind") == "llm":
            llm_calls += 1
            in_tok += rec.get("input_tokens", 0)
            out_tok += rec.get("output_tokens", 0)
        c, priced = _price_record(rec, pricing)
        if not priced:
            unpriced = True
        elif c:
            cost += c
    return {"cost_usd": round(cost, 4), "input_tokens": in_tok, "output_tokens": out_tok,
            "llm_calls": llm_calls, "providers": sorted(providers), "has_unpriced": unpriced}


def _run_title_status(slug: str) -> tuple[str, str]:
    """Best-effort title + review status for a slug (review metadata, else storyboard, else slug)."""
    meta_path = REVIEW_DIR / slug / "metadata.json"
    if meta_path.exists():
        try:
            m = json.loads(meta_path.read_text())
            title = (m.get("youtube") or {}).get("title") or (m.get("topic") or {}).get("title") or slug
            return title, m.get("status", "pending_review")
        except Exception:
            pass
    sb = RUNS_DIR / slug / "storyboard.json"
    if sb.exists():
        try:
            return json.loads(sb.read_text()).get("topic", {}).get("title", slug), "no_render"
        except Exception:
            pass
    return slug, "no_render"


@app.get("/api/usage")
def usage_overview():
    """All tracked videos with tokens + computed spend, plus untracked (pre-instrumentation)."""
    pricing = _pricing()
    videos, tot_cost, tot_in, tot_out = [], 0.0, 0, 0
    tracked_slugs = set()
    if RUNS_DIR.exists():
        for run in sorted(RUNS_DIR.iterdir(), reverse=True):
            uj = run / "usage.json"
            if not uj.exists():
                continue
            try:
                doc = json.loads(uj.read_text())
            except Exception:
                continue
            slug = doc.get("slug", run.name)
            tracked_slugs.add(slug)
            s = _summarize_usage(doc, pricing)
            title, status = _run_title_status(slug)
            tot_cost += s["cost_usd"]; tot_in += s["input_tokens"]; tot_out += s["output_tokens"]
            videos.append({"slug": slug, "title": title, "date": slug[:10], "status": status,
                           "tracked": True, **s})
    # untracked: rendered videos with no usage.json (predate instrumentation)
    untracked = 0
    if REVIEW_DIR.exists():
        for folder in sorted(REVIEW_DIR.iterdir(), reverse=True):
            if folder.is_dir() and folder.name not in tracked_slugs:
                title, status = _run_title_status(folder.name)
                videos.append({"slug": folder.name, "title": title, "date": folder.name[:10],
                               "status": status, "tracked": False, "cost_usd": None,
                               "input_tokens": 0, "output_tokens": 0, "llm_calls": 0,
                               "providers": [], "has_unpriced": False})
                untracked += 1
    videos.sort(key=lambda v: v["slug"], reverse=True)
    return {"totals": {"cost_usd": round(tot_cost, 3), "input_tokens": tot_in,
                       "output_tokens": tot_out, "videos_tracked": len(tracked_slugs),
                       "videos_untracked": untracked}, "videos": videos}


@app.get("/api/usage/{slug}")
def usage_detail(slug: str):
    """Per-session, per-stage breakdown for one video."""
    uj = RUNS_DIR / slug / "usage.json"
    if not uj.exists():
        raise HTTPException(404, "no usage recorded for this run")
    doc = json.loads(uj.read_text())
    pricing = _pricing()
    sessions_out = []
    for session in doc.get("sessions", []):
        groups: dict[str, dict] = {}
        sess_cost = 0.0
        for rec in session.get("records", []):
            g = groups.setdefault(rec.get("stage", "?"), {
                "stage": rec.get("stage", "?"), "kind": rec.get("kind"), "calls": 0,
                "models": set(), "providers": set(), "input_tokens": 0, "output_tokens": 0,
                "characters": 0, "requests": 0, "cost_usd": 0.0, "unpriced": False})
            g["calls"] += 1
            if rec.get("model"): g["models"].add(rec["model"])
            g["providers"].add(rec.get("provider", "?"))
            g["input_tokens"] += rec.get("input_tokens", 0)
            g["output_tokens"] += rec.get("output_tokens", 0)
            g["characters"] += rec.get("characters", 0)
            g["requests"] += rec.get("requests", 0)
            c, priced = _price_record(rec, pricing)
            if not priced:
                g["unpriced"] = True
            elif c:
                g["cost_usd"] += c; sess_cost += c
        stages = []
        for g in groups.values():
            g["models"] = sorted(g["models"]); g["providers"] = sorted(g["providers"])
            g["cost_usd"] = round(g["cost_usd"], 4)
            stages.append(g)
        stages.sort(key=lambda x: x["cost_usd"] or 0, reverse=True)
        sessions_out.append({"phase": session.get("phase"), "started_at": session.get("started_at"),
                             "stages": stages, "cost_usd": round(sess_cost, 4)})
    return {"slug": slug, "sessions": sessions_out, "free_stages": FREE_STAGES}


@app.get("/api/checklist")
def get_checklist():
    checklist = json.loads((ROOT / "checklist.schema.json").read_text())
    return {"gate_b": checklist["gates"]["gate_b_pre_publish"]}


CONTROLS_PATH = ROOT / "config" / "controls.yaml"

CONTROL_OPTIONS = {
    "checkpoints": {
        "story_pick": ["auto", "manual"],
        "hook_pick": ["auto", "manual"],
        "script_approval": ["auto", "manual"],
        "storyboard_approval": ["auto", "manual"],
        "publish": ["auto", "manual"],
    },
    "providers": {
        "scout": ["ollama", "openrouter", "anthropic"],
        "writer": ["ollama", "openrouter", "anthropic"],
        "reviewer": ["openrouter", "anthropic", "skip"],
        "voice": ["kokoro", "elevenlabs", "say"],
        "broll": ["pexels"],
    },
}

CONTROLS_HEADER = (
    "# Machine-writable control surface — the dashboard Config page reads/writes this file.\n"
    "# (settings.yaml stays hand-edited; nothing in the UI touches it.)\n"
)


def _load_controls() -> dict:
    if not CONTROLS_PATH.exists():
        return {}
    return yaml.safe_load(CONTROLS_PATH.read_text()) or {}


@app.get("/api/config")
def get_config():
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    feeds = yaml.safe_load((ROOT / "config" / "feeds.yaml").read_text())
    style_guide = (ROOT / "config" / "style_guide.md").read_text()
    return {
        "settings": settings,
        "feeds": feeds["feeds"],
        "style_guide": style_guide,
        "controls": _load_controls(),
        "control_options": CONTROL_OPTIONS,
    }


@app.post("/api/config")
def set_config(body: dict):
    controls = _load_controls()
    for group, allowed in CONTROL_OPTIONS.items():
        for key, value in (body.get(group) or {}).items():
            if key not in allowed or value not in allowed[key]:
                raise HTTPException(400, f"invalid {group}.{key} = {value!r}")
            controls.setdefault(group, {})[key] = value
    CONTROLS_PATH.write_text(CONTROLS_HEADER + yaml.safe_dump(controls, sort_keys=False))
    return {"ok": True, "controls": controls}


from ..checkpoints import PENDING, DECISION  # noqa: E402
from .. import evalharness  # noqa: E402


@app.get("/api/evals")
def list_evals():
    """Every eval run's blind A/B records. Provider names are stripped from options
    so the pick stays blind; `_reveal` is only exposed once a pick is recorded."""
    if not evalharness.EVAL_DIR.exists():
        return {"evals": []}
    out = []
    for run in sorted(evalharness.EVAL_DIR.iterdir(), reverse=True):
        idx_path = run / "index.json"
        if not idx_path.exists():
            continue
        idx = json.loads(idx_path.read_text())
        stations = []
        for station in idx.get("stations", []):
            rec = json.loads((run / f"{station}.json").read_text())
            picked = rec.get("pick")
            stations.append({
                "station": station,
                "options": {k: {"ok": v["ok"], "output": v.get("output"), "error": v.get("error")}
                            for k, v in rec["options"].items()},
                "pick": picked,
                # reveal only after a pick is recorded
                "reveal": rec["_reveal"] if picked else None,
            })
        out.append({"slug": idx["slug"], "story_title": idx["story_title"], "stations": stations})
    return {"evals": out}


@app.post("/api/evals/{slug}/{station}/pick")
def pick_eval(slug: str, station: str, body: dict):
    choice = body.get("choice")
    if choice not in ("A", "B"):
        raise HTTPException(400, "choice must be 'A' or 'B'")
    try:
        return evalharness.record_pick(slug, station, choice)
    except FileNotFoundError:
        raise HTTPException(404, "eval not found")


@app.get("/api/checkpoint")
def get_checkpoint():
    """The choice a paused run is waiting on, or null when nothing is pending."""
    if not PENDING.exists():
        return {"pending": None}
    try:
        return {"pending": json.loads(PENDING.read_text())}
    except (json.JSONDecodeError, OSError):
        return {"pending": None}


@app.post("/api/checkpoint/decide")
def decide_checkpoint(body: dict):
    """Answer the pending checkpoint; the paused run picks this up and continues."""
    if not PENDING.exists():
        raise HTTPException(409, "No checkpoint is pending.")
    pending = json.loads(PENDING.read_text())
    choice = int(body.get("choice", pending.get("auto_index", 0)))
    n = len(pending.get("choices", []))
    if not (0 <= choice < n):
        raise HTTPException(400, "choice out of range")
    DECISION.parent.mkdir(parents=True, exist_ok=True)
    DECISION.write_text(json.dumps({"name": pending["name"], "choice": choice}))
    return {"ok": True}


@app.get("/media/{slug}/video")
def media_video(slug: str):
    path = REVIEW_DIR / slug / f"{slug}.mp4"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@app.get("/media/{slug}/thumb")
def media_thumb(slug: str):
    path = REVIEW_DIR / slug / "thumb.jpg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
