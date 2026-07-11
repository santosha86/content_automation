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
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .util import ROOT, settings

# Generated stills are the slowest step (~90s each). Cache them keyed by
# prompt+negative+story_seed so re-rendering a video (new music/captions/voice) reuses the
# exact images instead of paying the 30-min gen again. The story_seed keeps the key
# per-video, so the SAME prompt in two different videos still generates two different
# images (no cross-video repetition) while a re-render of one video is a clean cache hit.
CACHE_DIR = ROOT / "state" / "img_cache"

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


def _looks_like_noise(png: Path) -> bool:
    """A degenerate (noise) render barely compresses, so its PNG is far larger than a
    real image at the same size. Cheap guard against a bad generation shipping silently
    (e.g. incomplete weights, transient memory pressure). ~2.2 bytes/px is well above
    real images (~1-1.5) and below noise (~4)."""
    try:
        return png.stat().st_size > int(_GEN_WIDTH * _GEN_HEIGHT * 2.2)
    except OSError:
        return True


def _flux_generate(prompt: str, negative: str, out_png: Path, seed: int) -> bool:
    args = [
        _flux_bin(), "--model", _FLUX_MODEL, "--prompt", prompt,
        "--steps", str(_FLUX_STEPS), "--seed", str(seed), "--quantize", "4", "--low-ram",
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


def _cache_path(prompt: str, neg: str, story_seed: str) -> Path:
    key = hashlib.sha1(f"{prompt}|{neg}|{story_seed}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"{key}.png"


def generate(shot: dict, out_png: Path, story_seed: str = "") -> Path | None:
    """Generate a still for a shot, or None if no local generator / it fails
    (caller then falls back to stock or a gradient). Seeds off prompt+story so shots
    differ across videos; retries with a new seed if the output looks like noise.
    Cached by prompt+negative+story_seed — a re-render is an instant cache hit."""
    prompt = (shot.get("prompt") or "").strip()
    if not prompt or not _flux_available():
        return None
    neg = (shot.get("negative_prompt") or "").strip()
    cached = _cache_path(prompt, neg, story_seed)
    if cached.exists() and not _looks_like_noise(cached):
        shutil.copyfile(cached, out_png)
        print("  [imagegen] cache hit — reused still (no re-gen)")
        return out_png
    # story_seed salts the generation seed so identical prompts in different videos diverge.
    salt = int(hashlib.sha1(f"{prompt}|{story_seed}".encode()).hexdigest(), 16) % 100000
    for attempt in range(3):
        if _flux_generate(prompt, neg, out_png, seed=salt + attempt) and not _looks_like_noise(out_png):
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out_png, cached)  # store for re-render reuse
            return out_png
        print(f"  [imagegen] attempt {attempt + 1} produced no/degenerate image, retrying with a new seed")
    return None  # give up -> caller falls back to stock/gradient


def status() -> str:
    return "flux_local (mflux)" if _flux_available() else "unavailable — using stock/gradient fallback"
