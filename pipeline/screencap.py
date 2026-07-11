"""Screenshot the official source for concrete (Type-A) stories — real proof beats
generated imagery. Uses headless Chrome (already installed on macOS), so there's no new
Python dependency. A screenshot of the actual GitHub repo / product page / launch post is
the most credible frame we can put on screen.

Provider ladder (local-first): Chrome headless -> None. On failure the caller falls back to
FLUX/stock/gradient, so the pipeline never hard-depends on the browser.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

# Common install locations; override with CHROME_BIN in .env.
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

_URL_RE = re.compile(r"^https?://", re.I)


def _chrome_bin() -> str | None:
    override = os.getenv("CHROME_BIN")
    if override and Path(override).exists():
        return override
    for c in _CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")


def _available() -> bool:
    # Opt-out via SCREENCAP_ENABLED=0; on by default when a browser is present.
    if os.getenv("SCREENCAP_ENABLED", "1").lower() in ("0", "false", "no"):
        return False
    return _chrome_bin() is not None


def is_url(s: str) -> bool:
    return bool(s and _URL_RE.match(s.strip()))


# A realistic desktop UA cuts down (not eliminates) bot challenges on protected sites.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def _looks_blank(png: Path) -> bool:
    """True if the shot is near-uniform — a Cloudflare 'Verifying...' interstitial, a
    cookie/consent wall, or a blank error page (mostly one background color). Those are
    worse than a fallback still, so reject them."""
    try:
        from PIL import Image
        im = Image.open(png).convert("RGB").resize((64, 114))
        px = list(im.getdata())
        # modal-ish color: quantize to buckets, find the dominant bucket's share
        from collections import Counter
        buckets = Counter((r // 24, g // 24, b // 24) for r, g, b in px)
        dominant = buckets.most_common(1)[0][1] / len(px)
        return dominant > 0.90
    except Exception:
        return False  # if PIL/analysis fails, don't block a usable screenshot


def capture(url: str, out_png: Path, width: int = 1080, height: int = 1920) -> Path | None:
    """Screenshot `url` into a portrait PNG, or None if not a URL / browser missing /
    fails / the page is a bot-challenge or blank wall (caller then falls back)."""
    url = (url or "").strip()
    if not is_url(url) or not _available():
        return None
    args = [
        _chrome_bin(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-sandbox", "--force-device-scale-factor=1", f"--user-agent={_UA}",
        f"--window-size={width},{height}",
        "--virtual-time-budget=6000",  # let the page's JS/render settle before the shot
        f"--screenshot={out_png}", url,
    ]
    try:
        # 30s hard cap: paywalled/heavy-JS pages that never finish loading fail fast to
        # the fallback instead of stalling the whole render.
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  [screencap] failed for {url}: {str(e)[:100]}")
        return None
    if not (out_png.exists() and out_png.stat().st_size > 5000):
        print(f"  [screencap] no usable screenshot for {url} (rc={proc.returncode})")
        return None
    if _looks_blank(out_png):
        print(f"  [screencap] {url} looked like a bot-challenge/blank wall — rejecting")
        out_png.unlink(missing_ok=True)
        return None
    return out_png


def status() -> str:
    return f"chrome_headless ({_chrome_bin()})" if _available() else "unavailable — using generated/stock fallback"
