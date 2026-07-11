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
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .util import settings

# Local text-to-image model for generated_image beats. `schnell` is best-known but its
# HF repo is gated (needs `huggingface-cli login` + license accept). `z-image-turbo` and
# other mflux base models are open. Override with MFLUX_MODEL / MFLUX_STEPS in .env.
_FLUX_MODEL = os.getenv("MFLUX_MODEL", "schnell")
_FLUX_STEPS = int(os.getenv("MFLUX_STEPS", "3"))

# Generate at a memory-safe 9:16 size (full 1080x1920 peaks ~27GB and blows past a 24GB
# Mac's RAM -> garbage output). The Editor upscales the still to the video's 1080x1920.
# Must be multiples of 16. Override with MFLUX_GEN_WIDTH / MFLUX_GEN_HEIGHT.
_GEN_WIDTH = int(os.getenv("MFLUX_GEN_WIDTH", "576"))
_GEN_HEIGHT = int(os.getenv("MFLUX_GEN_HEIGHT", "1024"))


def _flux_bin() -> str | None:
    """Locate mflux-generate. Prefer the interpreter's own bin/ (the conda env may not
    be 'activated' when we invoke python by full path), then fall back to PATH."""
    sibling = Path(sys.executable).parent / "mflux-generate"
    if sibling.exists():
        return str(sibling)
    return shutil.which("mflux-generate")


def _flux_available() -> bool:
    # Gated behind an explicit opt-in: mflux being *installed* is not enough — an
    # incomplete/partial model download generates pure noise but still exits 0, which
    # would silently poison every generated_image shot. Only activate once the model is
    # verified working and MFLUX_ENABLED=1 is set in .env.
    if os.getenv("MFLUX_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False
    return _flux_bin() is not None


def _flux_generate(prompt: str, negative: str, out_png: Path) -> bool:
    args = [
        _flux_bin(), "--model", _FLUX_MODEL, "--prompt", prompt,
        "--steps", str(_FLUX_STEPS), "--seed", "42", "--quantize", "4", "--low-ram",
        "--height", str(_GEN_HEIGHT), "--width", str(_GEN_WIDTH),
        "--output", str(out_png),
    ]
    if negative:
        args += ["--negative-prompt", negative]
    # HF's Xet transfer backend errors on some repos ("Unable to parse string as hex
    # hash value"); force the standard downloader. HF_TOKEN (from .env via util) is
    # inherited for the gated schnell repo.
    env = {**os.environ, "HF_HUB_DISABLE_XET": "1",
           "HF_HUB_DOWNLOAD_TIMEOUT": os.getenv("HF_HUB_DOWNLOAD_TIMEOUT", "120")}
    env.pop("HF_HUB_ENABLE_HF_TRANSFER", None)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=900, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        print(f"  [imagegen] mflux failed: {proc.stderr.strip()[-300:]}")
    return proc.returncode == 0 and out_png.exists()


def generate(shot: dict, out_png: Path) -> Path | None:
    """Generate a still for a shot, or None if no local generator / it fails
    (caller then falls back to stock or a gradient)."""
    prompt = (shot.get("prompt") or "").strip()
    if not prompt or not _flux_available():
        return None
    neg = (shot.get("negative_prompt") or "").strip()
    return out_png if _flux_generate(prompt, neg, out_png) else None


def status() -> str:
    return "flux_local (mflux)" if _flux_available() else "unavailable — using stock/gradient fallback"
