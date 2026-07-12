"""Daily autopilot — hands-off factory: pick a topic, plan, render, land it in review.

Pulls the next item from the content queue (queue.py); if the queue is empty it auto-scouts
the day's best story. Runs the resilient planner in-process, then renders in a subprocess
(isolation — a render crash can't take down the dashboard's scheduler thread).

Config lives in controls.yaml -> autopilot (dashboard-writable, no code changes):
  enabled: true|false     master switch for the daily schedule
  time: "09:00"           local 24h time for the daily run
Manual "run now" ignores enabled/time and just runs once.
"""
import datetime
import json
import subprocess
import sys

from . import plan as planner
from . import queue as content_queue
from .util import ROOT, controls

STATE_FILE = ROOT / "state" / "autopilot.json"


def _state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, indent=2))


def config() -> dict:
    cfg = controls().get("autopilot", {}) or {}
    return {"enabled": bool(cfg.get("enabled", False)), "time": cfg.get("time", "09:00")}


def run_once(log=print) -> dict:
    """One full autopilot cycle: topic -> plan -> render. Returns a small result dict."""
    item = content_queue.pop_next()
    topic = item["topic"] if item else ""
    url = item.get("url", "") if item else ""
    log(f"[autopilot] topic: {topic or '(auto-scout the best story)'}")
    try:
        storyboard = planner.plan(topic, url, log=log)
    except Exception as e:
        log(f"[autopilot] planning failed: {str(e)[:160]}")
        _save_state({**_state(), "last_run_date": str(datetime.date.today()),
                     "last_ok": False, "last_error": str(e)[:200], "last_topic": topic or "auto"})
        return {"ok": False, "error": str(e)[:200]}
    slug = f"{datetime.date.today()}-{planner._slugify(storyboard['topic']['title'])}"
    sb_path = ROOT / "output" / "runs" / slug / "storyboard.json"
    log(f"[autopilot] rendering {slug} ...")
    proc = subprocess.run([sys.executable, "-m", "pipeline.run", "--storyboard", str(sb_path)], cwd=str(ROOT))
    ok = proc.returncode == 0
    _save_state({**_state(), "last_run_date": str(datetime.date.today()), "last_slug": slug,
                 "last_ok": ok, "last_topic": topic or "auto", "last_error": ""})
    log(f"[autopilot] {'done' if ok else 'render failed'} -> {slug}")
    return {"ok": ok, "slug": slug, "topic": topic or "auto"}


def due_now() -> bool:
    """True if the scheduler should fire now: enabled, matches the configured time, and it
    hasn't already run today. Checked once a minute by the server's scheduler thread."""
    cfg = config()
    if not cfg["enabled"]:
        return False
    if datetime.datetime.now().strftime("%H:%M") != cfg["time"]:
        return False
    return _state().get("last_run_date") != str(datetime.date.today())


def status() -> dict:
    cfg = config()
    st = _state()
    nxt = content_queue.peek_next()
    return {
        "enabled": cfg["enabled"], "time": cfg["time"],
        "last_run_date": st.get("last_run_date", ""), "last_slug": st.get("last_slug", ""),
        "last_ok": st.get("last_ok"), "last_topic": st.get("last_topic", ""),
        "last_error": st.get("last_error", ""),
        "next_queued": nxt["topic"] if nxt else "(auto-scout)",
        "queued_count": len(content_queue.list_items("queued")),
    }


if __name__ == "__main__":
    print(json.dumps(run_once(), indent=2))
