"""Visuals: portrait b-roll per segment. Pexels when key present, generated gradient fallback."""
import os
from pathlib import Path

import requests

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


def gather(script: dict, seg_durations: list[float], run_dir: Path) -> list[Path]:
    """One b-roll clip per segment; returns paths in order."""
    use_pexels = bool(os.getenv("PEXELS_API_KEY"))
    if not use_pexels:
        print("  [visuals] no PEXELS_API_KEY — using generated backgrounds")
    paths = []
    for i, seg in enumerate(script["segments"]):
        out = run_dir / f"broll_{i:02d}.mp4"
        got = False
        if use_pexels:
            try:
                got = _pexels(seg["broll_query"], out)
            except Exception as e:
                print(f"  [visuals] pexels failed for '{seg['broll_query']}': {e}")
        if not got:
            _gradient(i, seg_durations[i] + 0.5, out)
        paths.append(out)
    return paths
