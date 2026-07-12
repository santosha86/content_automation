"""Motion video-gen via fal.ai — the opt-in "paid tier" for the 1-2 action shots per video
that genuinely need real movement (the rest stay free realistic stills + Ken-Burns).

fal.ai is the "OpenRouter for media": one key, one recharge, many models (Kling, LTX, Wan).
GATED like the Publisher — nothing spends unless FAL_KEY is set AND VIDEOGEN_ENABLED=1.
With no key it returns None and the caller keeps the free still, so the pipeline never
hard-depends on it.

Default is IMAGE-to-video: we animate the realistic FLUX still we already generated (and
cached), so the motion inherits the "looks filmed, not AI" aesthetic instead of a fresh
text-to-video roll of the dice. Falls back to text-to-video when there's no still.

Cost is per clip (~$0.03-0.10) and recorded to the Usage dashboard automatically.
"""
import base64
import os
import time
from pathlib import Path

import requests

from . import util as _util  # noqa: F401 — importing util loads .env so FAL_KEY is present

FAL_QUEUE = "https://queue.fal.run"
# Configurable model slugs (verify/adjust at fal.ai/models). Kling standard is a good
# quality/price balance; LTX is cheaper/faster.
_IMG2VID = os.getenv("FAL_VIDEO_MODEL_I2V", "fal-ai/kling-video/v1.6/standard/image-to-video")
_TXT2VID = os.getenv("FAL_VIDEO_MODEL_T2V", "fal-ai/kling-video/v1.6/standard/text-to-video")


def available() -> bool:
    """On only when explicitly enabled AND a key exists — no accidental spend."""
    if os.getenv("VIDEOGEN_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False
    return bool(os.getenv("FAL_KEY"))


def status() -> str:
    if not os.getenv("FAL_KEY"):
        return "unavailable — no FAL_KEY (using realistic stills)"
    if os.getenv("VIDEOGEN_ENABLED", "").lower() not in ("1", "true", "yes"):
        return "key present but VIDEOGEN_ENABLED not set (using stills)"
    return f"fal.ai ({_IMG2VID})"


def _headers() -> dict:
    return {"Authorization": f"Key {os.environ['FAL_KEY']}", "Content-Type": "application/json"}


def _data_uri(png: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


def _submit(model: str, args: dict) -> dict | None:
    try:
        r = requests.post(f"{FAL_QUEUE}/{model}", headers=_headers(), json=args, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [videogen] submit failed: {str(e)[:160]}")
        return None


def _await_result(submitted: dict, timeout_s: int = 300) -> dict | None:
    """Poll the queue until COMPLETED, then fetch the result payload."""
    status_url = submitted.get("status_url")
    response_url = submitted.get("response_url")
    if not status_url or not response_url:
        return None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            s = requests.get(status_url, headers=_headers(), timeout=30).json()
        except Exception:
            time.sleep(4); continue
        st = s.get("status")
        if st == "COMPLETED":
            try:
                return requests.get(response_url, headers=_headers(), timeout=60).json()
            except Exception as e:
                print(f"  [videogen] result fetch failed: {str(e)[:120]}")
                return None
        if st in ("FAILED", "ERROR", "CANCELLED"):
            print(f"  [videogen] job {st}")
            return None
        time.sleep(5)
    print("  [videogen] timed out")
    return None


def _download(result: dict, out_mp4: Path) -> Path | None:
    # fal video models return {"video": {"url": ...}} (some return {"video": {"url"}, ...}).
    video = result.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else None
    if not url:
        print("  [videogen] no video url in result")
        return None
    try:
        data = requests.get(url, timeout=300).content
        out_mp4.write_bytes(data)
        return out_mp4
    except Exception as e:
        print(f"  [videogen] download failed: {str(e)[:120]}")
        return None


def _record_usage(model: str) -> None:
    try:
        from . import usage
        usage.record("videogen", station="visuals", stage="videogen.fal",
                     provider="fal", model=model, requests=1)
    except Exception:
        pass


def generate(shot: dict, still_png: Path | None, out_mp4: Path, seconds: float = 5.0) -> Path | None:
    """Animate a shot into a short clip. Prefers image-to-video from the realistic still;
    falls back to text-to-video from the prompt. Returns the mp4 path or None (caller then
    keeps the still). No-op-safe: any failure returns None."""
    if not available():
        return None
    prompt = (shot.get("prompt") or shot.get("must_show") or "").strip()
    dur = "10" if seconds > 6 else "5"  # Kling supports 5s or 10s
    if still_png and Path(still_png).exists():
        model = _IMG2VID
        args = {"prompt": prompt or "subtle natural camera motion, realistic",
                "image_url": _data_uri(Path(still_png)), "duration": dur}
    else:
        model = _TXT2VID
        args = {"prompt": prompt, "duration": dur}
    if not prompt and model == _TXT2VID:
        return None
    submitted = _submit(model, args)
    if not submitted:
        return None
    result = _await_result(submitted)
    if not result:
        return None
    out = _download(result, out_mp4)
    if out:
        _record_usage(model)
        print(f"  [videogen] motion clip generated ({model.split('/')[1]})")
    return out
