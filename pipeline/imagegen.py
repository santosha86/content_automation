"""Local image generation for `generated_image` shots — FLUX on Apple Silicon.

Provider ladder (local-first cost policy): FLUX-local (mflux, MLX) -> None. When no
local generator is installed the caller falls back to stock/gradient, so the pipeline
never hard-depends on a multi-GB model. Enable FLUX once with:

    pip install mflux            # into the conda env
    # first generate downloads the quantized schnell model (~a few GB), then it's cached

FLUX is what makes generated beats actually depict the narration (the Director writes the
prompt; concept.continuity + negative_prompt are prepended by the adapter), instead of
falling back to generic stock that doesn't match the words.
"""
import shutil
import subprocess
from pathlib import Path

from .util import settings

# steps: schnell is a few-step model; 2-4 is the sweet spot for speed on-device.
_FLUX_STEPS = 3
_FLUX_MODEL = "schnell"


def _flux_available() -> bool:
    return shutil.which("mflux-generate") is not None


def _flux_generate(prompt: str, out_png: Path) -> bool:
    v = settings()["video"]
    args = [
        "mflux-generate", "--model", _FLUX_MODEL, "--prompt", prompt,
        "--steps", str(_FLUX_STEPS), "--seed", "42", "-q", "4",
        "--height", str(v["height"]), "--width", str(v["width"]),
        "--output", str(out_png),
    ]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and out_png.exists()


def generate(shot: dict, out_png: Path) -> Path | None:
    """Generate a still for a shot, or None if no local generator / it fails
    (caller then falls back to stock or a gradient)."""
    prompt = (shot.get("prompt") or "").strip()
    if not prompt or not _flux_available():
        return None
    neg = (shot.get("negative_prompt") or "").strip()
    full = f"{prompt}. Avoid: {neg}" if neg else prompt
    return out_png if _flux_generate(full, out_png) else None


def status() -> str:
    return "flux_local (mflux)" if _flux_available() else "unavailable — using stock/gradient fallback"
