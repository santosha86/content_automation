"""Checkpoint pause/resume: let a running plan stop and ask a human to choose.

Protocol (one active run at a time — the dashboard enforces that):
  - A manual checkpoint publishes `state/checkpoints/pending.json` with the choices,
    then BLOCKS polling for `state/checkpoints/decision.json`.
  - The dashboard shows the choices and POSTs a decision, which writes decision.json.
  - The run reads its choice, clears both files, and continues.

Modes come from controls.yaml (checkpoints.<name>: auto|manual). `auto` takes the
agent's own ranked pick with no pause. Outside the dashboard: a TTY prompts on the
console; a non-interactive run falls back to auto so batch jobs never hang.
"""
import json
import os
import sys
import time

from .util import ROOT, checkpoint_mode

CKPT_DIR = ROOT / "state" / "checkpoints"
PENDING = CKPT_DIR / "pending.json"
DECISION = CKPT_DIR / "decision.json"


def clear() -> None:
    """Drop any stale pending/decision files (called at the start of every run)."""
    for p in (PENDING, DECISION):
        p.unlink(missing_ok=True)


def resolve(name: str, choices: list[dict], *, prompt: str = "",
            auto_index: int = 0, log=print, poll: float = 1.5) -> int:
    """Resolve a checkpoint to a chosen index into `choices`.

    `choices` is a list of {"label", "detail"} dicts describing each option.
    Returns the selected index (auto_index when auto/fallback).
    """
    if not choices:
        return auto_index
    auto_index = max(0, min(auto_index, len(choices) - 1))
    mode = checkpoint_mode(name)

    if mode != "manual":
        log(f"      [checkpoint:{name}] auto -> {choices[auto_index]['label']}")
        return auto_index

    # Manual. In the dashboard, hand the choice to the UI and block for the answer.
    if os.getenv("DASHBOARD_RUN"):
        return _await_dashboard(name, choices, prompt, auto_index, log, poll)
    # On a terminal, ask right here.
    if sys.stdin and sys.stdin.isatty():
        return _ask_console(name, choices, prompt, auto_index)
    # Headless batch run with no UI — don't hang; take the ranked pick.
    log(f"      [checkpoint:{name}] manual but no UI/TTY — falling back to auto -> {choices[auto_index]['label']}")
    return auto_index


def _await_dashboard(name, choices, prompt, auto_index, log, poll) -> int:
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    DECISION.unlink(missing_ok=True)
    PENDING.write_text(json.dumps({
        "name": name, "prompt": prompt, "auto_index": auto_index, "choices": choices,
    }))
    log(f"      [checkpoint:{name}] awaiting your choice in the dashboard ({len(choices)} options)...")
    while True:
        if DECISION.exists():
            try:
                d = json.loads(DECISION.read_text())
            except (json.JSONDecodeError, OSError):
                d = {}
            if d.get("name") == name:
                idx = max(0, min(int(d.get("choice", auto_index)), len(choices) - 1))
                PENDING.unlink(missing_ok=True)
                DECISION.unlink(missing_ok=True)
                log(f"      [checkpoint:{name}] you chose -> {choices[idx]['label']}")
                return idx
        time.sleep(poll)


def _ask_console(name, choices, prompt, auto_index) -> int:
    print(f"\n[checkpoint:{name}] {prompt}")
    for i, c in enumerate(choices):
        mark = " (default)" if i == auto_index else ""
        print(f"  {i}. {c['label']}{mark}")
        if c.get("detail"):
            print(f"       {c['detail']}")
    try:
        raw = input(f"Choose [0-{len(choices) - 1}, Enter={auto_index}]: ").strip()
    except EOFError:
        return auto_index
    if not raw:
        return auto_index
    try:
        return max(0, min(int(raw), len(choices) - 1))
    except ValueError:
        return auto_index
