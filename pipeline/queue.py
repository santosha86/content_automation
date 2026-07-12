"""Content queue — a persistent list of topics to make, in order.

Autopilot pulls the next queued item each run; if the queue is empty it auto-scouts. You
can also queue a week of ideas and let it work through them. Plain JSON at state/queue.json
so it survives restarts and is easy to inspect/edit.
"""
import json
import time
import uuid
from pathlib import Path

from .util import ROOT

QUEUE_FILE = ROOT / "state" / "queue.json"


def _load() -> dict:
    if not QUEUE_FILE.exists():
        return {"items": []}
    try:
        return json.loads(QUEUE_FILE.read_text())
    except Exception:
        return {"items": []}


def _save(doc: dict) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(QUEUE_FILE)


def add(topic: str, url: str = "", note: str = "") -> dict:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("empty topic")
    doc = _load()
    item = {"id": uuid.uuid4().hex[:8], "topic": topic, "url": url.strip(),
            "note": note.strip(), "added": time.strftime("%Y-%m-%d %H:%M"), "status": "queued"}
    doc["items"].append(item)
    _save(doc)
    return item


def list_items(status: str = None) -> list[dict]:
    items = _load()["items"]
    return [i for i in items if not status or i.get("status") == status]


def remove(item_id: str) -> bool:
    doc = _load()
    before = len(doc["items"])
    doc["items"] = [i for i in doc["items"] if i.get("id") != item_id]
    _save(doc)
    return len(doc["items"]) < before


def promote(item_id: str) -> bool:
    """Move an item to the front of the queued list (make it next)."""
    doc = _load()
    idx = next((k for k, i in enumerate(doc["items"]) if i.get("id") == item_id), None)
    if idx is None:
        return False
    doc["items"].insert(0, doc["items"].pop(idx))
    _save(doc)
    return True


def pop_next() -> dict | None:
    """Return the first queued item and mark it done (so autopilot won't repeat it).
    Returns None when the queue has nothing queued (caller then auto-scouts)."""
    doc = _load()
    for i in doc["items"]:
        if i.get("status") == "queued":
            i["status"] = "done"
            i["done_at"] = time.strftime("%Y-%m-%d %H:%M")
            _save(doc)
            return i
    return None


def peek_next() -> dict | None:
    for i in _load()["items"]:
        if i.get("status") == "queued":
            return i
    return None
