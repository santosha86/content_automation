"""Usage collector — per-video token/character/request counts, no prices.

All spend flows through a few call sites (util.llm, reviewer.grade, voice elevenlabs,
strategist tavily). Each records here; on bind() the buffer flushes to
<run_dir>/usage.json and every later record triggers an atomic re-write. Prices are NOT
stored — the server applies config/pricing.yaml at read time so a pricing fix retro-
corrects history.

Module-level singleton: each pipeline invocation is one process, so a global is safe.
Capture must NEVER break a run — every public function swallows its own errors.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

_buffer: list[dict] = []      # records seen before the slug/run_dir is known
_run_dir: Path | None = None
_phase: str = ""
_session: dict | None = None  # the session dict inside usage.json we append to


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(kind: str, *, station: str, stage: str, provider: str, model: str = None,
           input_tokens: int = 0, output_tokens: int = 0, characters: int = 0,
           requests: int = 0, duration_ms: int = None) -> None:
    """Append one usage record. kind ∈ llm | tts | search. No-op-safe on any error."""
    try:
        rec = {"ts": _now(), "kind": kind, "station": station, "stage": stage,
               "provider": provider}
        if model:
            rec["model"] = model
        if input_tokens:
            rec["input_tokens"] = int(input_tokens)
        if output_tokens:
            rec["output_tokens"] = int(output_tokens)
        if characters:
            rec["characters"] = int(characters)
        if requests:
            rec["requests"] = int(requests)
        if duration_ms is not None:
            rec["duration_ms"] = int(duration_ms)
        if _session is None:
            _buffer.append(rec)          # before bind — hold in memory
        else:
            _session["records"].append(rec)
            _flush()
    except Exception:
        pass  # usage capture must never fail a run


def bind(run_dir: Path, phase: str) -> None:
    """Attach the collector to a run once the slug exists. Opens a new session in
    <run_dir>/usage.json (appending to any existing sessions from a prior phase), and
    flushes anything buffered before the slug was known."""
    global _run_dir, _phase, _session
    try:
        _run_dir = Path(run_dir)
        _phase = phase
        _session = {"phase": phase, "started_at": _now(), "records": list(_buffer)}
        _buffer.clear()
        _flush()
    except Exception:
        _session = None  # stay in buffering mode rather than crash


def _flush() -> None:
    """Atomically write usage.json (tmp + os.replace), so a killed run keeps partial data."""
    if _run_dir is None or _session is None:
        return
    try:
        path = _run_dir / "usage.json"
        doc = {"slug": _run_dir.name, "sessions": []}
        if path.exists():
            try:
                doc = json.loads(path.read_text())
            except Exception:
                doc = {"slug": _run_dir.name, "sessions": []}
        # Replace-or-append THIS session (identified by object identity via started_at).
        sessions = [s for s in doc.get("sessions", []) if s.get("started_at") != _session["started_at"]]
        sessions.append(_session)
        doc["slug"] = _run_dir.name
        doc["sessions"] = sessions
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, path)
    except Exception:
        pass
