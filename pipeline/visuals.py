"""Visuals: portrait b-roll, one clip PER SHOT so cuts sync with the narration.

Each segment carries a shot list (Director-planned or a single fallback). For every
shot we fetch a clip: a FLUX-generated still (generated_image), else Pexels stock, else
a generated gradient. Returns shot clips grouped per segment; the Editor lays them out
across the segment's narration and applies each shot's Ken-Burns move.
"""
import os
from pathlib import Path

import requests

from . import imagegen, screencap, videogen
from .util import ffmpeg_bin, run_cmd, settings

FALLBACK_COLORS = ["0x1a1a2e", "0x16213e", "0x0f3460", "0x1f1d36", "0x222831", "0x27374d"]


def _pexels(query: str, out: Path) -> bool:
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": os.environ["PEXELS_API_KEY"]},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 3},
        timeout=60,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        return False
    files = videos[0]["video_files"]
    # smallest file that is still tall enough
    files = sorted((f for f in files if f.get("height", 0) >= 1280), key=lambda f: f.get("height", 0))
    url = (files[0] if files else videos[0]["video_files"][0])["link"]
    data = requests.get(url, timeout=300)
    out.write_bytes(data.content)
    return True


def _gradient(index: int, seconds: float, out: Path) -> None:
    cfg = settings()["video"]
    color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
    run_cmd([
        ffmpeg_bin(), "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={cfg['width']}x{cfg['height']}:d={seconds:.2f}:r={cfg['fps']}",
        "-vf", "vignette=PI/5,noise=alls=6:allf=t",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ])


def _still_to_clip(img: Path, seconds: float, out: Path) -> None:
    """Wrap a generated still into a video clip the Editor can loop/trim/Ken-Burns."""
    v = settings()["video"]
    fit = (f"scale={v['width']}:{v['height']}:force_original_aspect_ratio=increase,"
           f"crop={v['width']}:{v['height']},setsar=1,fps={v['fps']}")
    run_cmd([ffmpeg_bin(), "-y", "-loop", "1", "-i", str(img), "-t", f"{max(seconds, 2.0):.2f}",
             "-vf", fit, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def _realistic_shot_from(shot: dict) -> dict:
    """Build a generated_image shot (realistic photo) from a shot whose primary source
    (a screenshot) was unavailable — so a proof beat degrades to a believable still, not
    generic stock. Reuses the adapter's realism prefix + baseline negatives."""
    from .storyboard_adapter import _realism_prompt, _merge_neg
    subject = (shot.get("must_show") or shot.get("phrase") or "").strip() or "a modern software workspace"
    return {
        "source": "generated_image",
        "prompt": _realism_prompt(f"a real photo showing {subject}"),
        "negative_prompt": _merge_neg(""),
    }


def _shot_clip(shot: dict, seed: int, seconds: float, out: Path, use_pexels: bool,
               story_seed: str = "", motion_budget: list = None) -> None:
    """Fetch one clip for a shot: screenshot -> FLUX still -> Pexels stock -> gradient."""
    # Type-A "real proof": screenshot the actual page the Director pointed at.
    if shot.get("source") == "screen_capture":
        shot_url = (shot.get("query") or "").strip()
        img = screencap.capture(shot_url, out.with_suffix(".png"))
        if img:
            _still_to_clip(img, seconds, out)
            return
        print(f"  [visuals] screen_capture missed ('{shot_url}') — trying realistic still")
        # A missed proof shot must NOT drop to generic abstract stock (the "looks generic"
        # failure). Synthesize a realistic FLUX still from what the shot needed to show.
        fallback = _realistic_shot_from(shot)
        img = imagegen.generate(fallback, out.with_suffix(".png"), story_seed=story_seed)
        if img:
            _still_to_clip(img, seconds, out)
            return
    if shot.get("source") == "generated_image":
        img = imagegen.generate(shot, out.with_suffix(".png"), story_seed=story_seed)
        if img:
            # Motion tier (opt-in, paid): animate the realistic still for the 1-2 shots the
            # Director flagged, within the per-video budget. Falls back to the still on any
            # failure, so nothing breaks if fal.ai is off/errors.
            if shot.get("motion") and motion_budget and motion_budget[0] > 0 and videogen.available():
                clip = videogen.generate(shot, img, out, seconds)
                if clip:
                    motion_budget[0] -= 1
                    return
            _still_to_clip(img, seconds, out)
            return
    # A screen_capture shot's `query` is a URL — never search stock with it; use must_show.
    if shot.get("source") == "screen_capture":
        query = (shot.get("must_show") or "").strip()
    else:
        query = (shot.get("query") or shot.get("must_show") or "").strip()
    if use_pexels and query:
        try:
            if _pexels(query, out):
                return
        except Exception as e:
            print(f"  [visuals] pexels failed for '{query}': {e}")
    _gradient(seed, seconds, out)


def gather(script: dict, seg_durations: list[float], run_dir: Path) -> list[list[Path]]:
    """One clip PER SHOT, grouped per segment: returns [[shot clips], ...] in order."""
    use_pexels = bool(os.getenv("PEXELS_API_KEY"))
    if not use_pexels:
        print("  [visuals] no PEXELS_API_KEY — using generated backgrounds")
    print(f"  [visuals] image-gen: {imagegen.status()}")
    print(f"  [visuals] screenshots: {screencap.status()}")
    print(f"  [visuals] motion video-gen: {videogen.status()}")
    # Stable per-video salt so cached stills stay unique across videos (no repetition).
    story_seed = (script.get("topic", {}).get("title", "") or script.get("hook_text", ""))[:80]
    # Hard cap on paid motion clips per video (0 when video-gen is off => never spends).
    max_motion = int(settings().get("videogen", {}).get("max_shots", 2)) if videogen.available() else 0
    motion_budget = [max_motion]
    per_seg = []
    for i, seg in enumerate(script["segments"]):
        shots = seg.get("shots") or [{"source": "broll_video", "query": seg.get("broll_query", ""),
                                       "camera": "none"}]
        clips = []
        for j, shot in enumerate(shots):
            out = run_dir / f"shot_{i:02d}_{j:02d}.mp4"
            _shot_clip(shot, seed=i * 7 + j, seconds=seg_durations[i] + 0.5, out=out,
                       use_pexels=use_pexels, story_seed=story_seed, motion_budget=motion_budget)
            clips.append(out)
        per_seg.append(clips)
        print(f"  [visuals] segment {i}: {len(clips)} shot(s)")
    return per_seg
