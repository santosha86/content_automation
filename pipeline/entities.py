"""Entity anchoring: make the frame show the SUBJECT, not the theme.

The failure this fixes: the script says "Meta" and the screen shows a generic
data-center hallway. A viewer's brain wants the actual thing — Meta's logo, Meta's
product, Meta's own page. Theme-shots read as stock filler and cost retention.

Given a story, we detect the named brands in it and resolve each to two real assets:

  * `official_url(name)`  — a clean, screenshot-safe page the brand OWNS (never a news
    site, never a paywall). The Director points `screen_capture` shots here, so a
    "proof" shot is genuinely that company's page.
  * `logo(name)`          — a real brand mark, cached as a transparent PNG.
    Ladder: Simple Icons SVG (crisp, rasterized via the headless Chrome we already run)
    -> Google's favicon service (PNG) -> None, in which case the caller falls back to a
    typographic wordmark. Some brands (OpenAI, Microsoft) are absent from Simple Icons
    on trademark grounds, which is exactly why the ladder exists.

Everything here is free, keyless, cached, and best-effort: any failure degrades to a
weaker anchor rather than breaking the render.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import requests

from .screencap import _chrome_bin

_CACHE = Path("state/logos")

# Canonical brand registry. `url` must be a page the brand OWNS and that screenshots
# cleanly (no paywall / no bot-wall). `icon` is the Simple Icons slug, None if absent.
BRANDS: dict[str, dict] = {
    "OpenAI":     {"domain": "openai.com",     "url": "https://openai.com/index/",              "icon": None,        "aliases": ["chatgpt", "gpt-4", "gpt-5", "sam altman", "sora"]},
    "Anthropic":  {"domain": "anthropic.com",  "url": "https://www.anthropic.com/news",         "icon": "anthropic", "aliases": ["claude", "dario amodei"]},
    "Meta":       {"domain": "meta.com",       "url": "https://ai.meta.com/blog/",              "icon": "meta",      "aliases": ["facebook", "llama", "zuckerberg", "instagram", "whatsapp"]},
    "Google":     {"domain": "google.com",     "url": "https://blog.google/technology/ai/",     "icon": "google",    "aliases": ["deepmind", "gemini", "sundar pichai", "alphabet"]},
    "NVIDIA":     {"domain": "nvidia.com",     "url": "https://blogs.nvidia.com/",              "icon": "nvidia",    "aliases": ["jensen huang", "cuda", "blackwell", "h100"]},
    "Microsoft":  {"domain": "microsoft.com",  "url": "https://blogs.microsoft.com/ai/",        "icon": None,        "aliases": ["copilot", "azure", "satya nadella"]},
    "Apple":      {"domain": "apple.com",      "url": "https://machinelearning.apple.com/",     "icon": "apple",     "aliases": ["siri", "tim cook", "iphone", "apple intelligence"]},
    "Amazon":     {"domain": "amazon.com",     "url": "https://www.aboutamazon.com/news/aws",   "icon": "amazon",    "aliases": ["aws", "bedrock", "alexa"]},
    "DeepSeek":   {"domain": "deepseek.com",   "url": "https://www.deepseek.com/",              "icon": "deepseek",  "aliases": []},
    "Mistral":    {"domain": "mistral.ai",     "url": "https://mistral.ai/news/",               "icon": None,        "aliases": ["mistral ai", "le chat"]},
    "xAI":        {"domain": "x.ai",           "url": "https://x.ai/news",                      "icon": None,        "aliases": ["grok", "elon musk"]},
    "Tesla":      {"domain": "tesla.com",      "url": "https://www.tesla.com/AI",               "icon": "tesla",     "aliases": ["optimus", "full self-driving"]},
    "GitHub":     {"domain": "github.com",     "url": "https://github.blog/",                   "icon": "github",    "aliases": ["copilot workspace"]},
    "Hugging Face": {"domain": "huggingface.co", "url": "https://huggingface.co/blog",          "icon": "huggingface", "aliases": ["huggingface"]},
    "Perplexity": {"domain": "perplexity.ai",  "url": "https://www.perplexity.ai/hub/blog",     "icon": "perplexity", "aliases": []},
    "Stability AI": {"domain": "stability.ai", "url": "https://stability.ai/news",              "icon": None,        "aliases": ["stable diffusion"]},
    "Intel":      {"domain": "intel.com",      "url": "https://www.intel.com/content/www/us/en/artificial-intelligence/overview.html", "icon": "intel", "aliases": ["gaudi"]},
    "AMD":        {"domain": "amd.com",        "url": "https://www.amd.com/en/solutions/ai",    "icon": "amd",       "aliases": ["instinct", "mi300"]},
    "Qualcomm":   {"domain": "qualcomm.com",   "url": "https://www.qualcomm.com/products/technology/artificial-intelligence", "icon": "qualcomm", "aliases": ["snapdragon"]},
    "Salesforce": {"domain": "salesforce.com", "url": "https://www.salesforce.com/news/",       "icon": "salesforce", "aliases": ["agentforce"]},
    "Cursor":     {"domain": "cursor.com",     "url": "https://cursor.com/blog",                "icon": None,        "aliases": ["anysphere"]},
    "Figma":      {"domain": "figma.com",      "url": "https://www.figma.com/blog/",            "icon": "figma",     "aliases": []},
    "Netflix":    {"domain": "netflix.com",    "url": "https://about.netflix.com/en/news",      "icon": "netflix",   "aliases": []},
    "Spotify":    {"domain": "spotify.com",    "url": "https://newsroom.spotify.com/",          "icon": "spotify",   "aliases": []},
    "Reddit":     {"domain": "reddit.com",     "url": "https://redditinc.com/blog",             "icon": "reddit",    "aliases": []},
}


def detect(*texts: str) -> list[str]:
    """Named brands present in the story, most-mentioned first.

    Matches the canonical name and every alias on a word boundary, so "Meta" hits but
    "metadata" does not. Order matters: the first entity is the story's protagonist and
    is what the hook and the opening shots must show.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return []
    scored: list[tuple[int, int, str]] = []
    for name, cfg in BRANDS.items():
        terms = [name.lower(), *[a.lower() for a in cfg["aliases"]]]
        hits = sum(len(re.findall(rf"\b{re.escape(t)}\b", blob)) for t in terms)
        if hits:
            first = min((m.start() for t in terms
                         for m in re.finditer(rf"\b{re.escape(t)}\b", blob)), default=10**6)
            scored.append((-hits, first, name))   # most hits, then earliest mention
    return [name for _, _, name in sorted(scored)]


def official_url(name: str) -> str:
    """A page the brand owns — safe to screenshot (no paywall, no bot-wall)."""
    return (BRANDS.get(name) or {}).get("url", "")


def _rasterize_svg(svg: bytes, out_png: Path, size: int = 512) -> bool:
    """Render a Simple Icons SVG to a transparent PNG using the headless Chrome we
    already depend on for screenshots — avoids pulling in a cairo/SVG stack."""
    chrome = _chrome_bin()
    if not chrome:
        return False
    # Simple Icons ships a monochrome path with no fill; force white so the mark reads
    # on the dark footage these videos use.
    markup = svg.decode("utf-8", "ignore").replace("<svg", '<svg fill="white"', 1)
    html = out_png.with_suffix(".html")
    html.write_text(
        f'<body style="margin:0;background:transparent;display:grid;place-items:center;'
        f'width:{size}px;height:{size}px">{markup}</body>'
    )
    try:
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--default-background-color=00000000",          # transparent, not white
             f"--window-size={size},{size}",
             f"--screenshot={out_png}", f"file://{html.resolve()}"],
            capture_output=True, timeout=40, check=False,
        )
    except Exception:
        return False
    finally:
        html.unlink(missing_ok=True)
    return out_png.exists() and out_png.stat().st_size > 0


def logo(name: str) -> Path | None:
    """A real brand mark as a transparent PNG, cached. None if every rung fails."""
    cfg = BRANDS.get(name)
    if not cfg:
        return None
    _CACHE.mkdir(parents=True, exist_ok=True)
    out = _CACHE / f"{name.lower().replace(' ', '-')}.png"
    if out.exists() and out.stat().st_size > 0:
        return out

    # Rung 1 — Simple Icons: a crisp vector mark.
    if cfg.get("icon"):
        try:
            r = requests.get(f"https://cdn.simpleicons.org/{cfg['icon']}", timeout=15)
            if r.ok and r.content.lstrip().startswith(b"<svg") and _rasterize_svg(r.content, out):
                return out
        except Exception:
            pass

    # Rung 2 — favicon: lower quality, but it exists for everything.
    try:
        r = requests.get("https://www.google.com/s2/favicons",
                         params={"domain": cfg["domain"], "sz": "256"}, timeout=15)
        if r.ok and len(r.content) > 500:      # a 16px placeholder is tiny; reject it
            out.write_bytes(r.content)
            return out
    except Exception:
        pass

    return None   # caller falls back to a typographic wordmark


def brand_of_url(url: str) -> str:
    """Which brand owns this URL, if any."""
    u = (url or "").lower()
    if not u:
        return ""
    for name, cfg in BRANDS.items():
        if cfg["domain"] in u:
            return name
    return ""


def normalize(storyboard: dict) -> int:
    """Enforce entity anchoring deterministically. Returns the number of shots corrected.

    The Director gets the rule right most of the time, but "most of the time" is not an
    invariant — and the failure mode is exactly the one we set out to kill (a brand on
    screen that the voice never mentions, or a named brand with no frame). Observed misses:
    a CTA shot ("Drop your take below") anchored to OpenAI, and a phrase naming Meta
    anchored to NVIDIA. So the model proposes and this function decides:

      * A phrase that NAMES a brand is anchored to the FIRST brand it names — no argument.
      * A phrase that names none keeps its entity only if it is the story's protagonist
        (pronoun continuity: "They're building their own chip" is still Meta). Any other
        brand is a hallucinated anchor and is dropped.
      * A screen_capture whose URL belongs to a DIFFERENT brand than its entity is
        repointed at the entity's own page — never screenshot Nvidia to illustrate Meta.
    """
    beats = storyboard.get("beats", [])
    protagonist = (detect(
        storyboard.get("topic", {}).get("title", ""),
        storyboard.get("hook", {}).get("text", ""),
        *[b.get("narration", "") for b in beats],
    ) or [""])[0]

    fixed = 0
    for beat in beats:
        for shot in beat.get("visual", {}).get("shots", []) or []:
            current = (shot.get("entity") or "").strip()
            named = detect(shot.get("phrase", ""))
            if named:
                wanted = named[0]                      # the phrase decides
            elif current and current == protagonist:
                wanted = current                       # pronoun continuity — keep
            else:
                wanted = ""                            # hallucinated anchor — drop
            if wanted != current:
                shot["entity"] = wanted
                fixed += 1
            # Keep a proof shot pointed at the brand it claims to show.
            if shot.get("source") == "screen_capture":
                url = (shot.get("query") or "").strip()
                owner = brand_of_url(url)
                if wanted and owner != wanted:
                    shot["query"] = official_url(wanted)
                    fixed += 1
                elif not wanted and owner:
                    # A brand page under a phrase that names no brand — the CTA bug. Don't
                    # relabel it (that just legitimises showing an unrelated company);
                    # blank the URL so visuals degrades it to a realistic still instead.
                    shot["query"] = ""
                    fixed += 1
    return fixed


def brief(names: list[str]) -> str:
    """The entity block injected into the Director prompt."""
    if not names:
        return "(no famous brand in this story — anchor shots to the concrete objects instead)"
    lines = []
    for n in names[:4]:
        lines.append(f'  - {n} — official page (screenshot-safe): {official_url(n)}')
    return "\n".join(lines)
