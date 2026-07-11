"""Shared helpers: config, paths, LLM calls, ffmpeg resolution."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def settings() -> dict:
    with open(ROOT / "config" / "settings.yaml") as f:
        return yaml.safe_load(f)


def controls() -> dict:
    path = ROOT / "config" / "controls.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def station_provider(station: str, default: str) -> str:
    return controls().get("providers", {}).get(station, default)


def style_guide() -> str:
    return (ROOT / "config" / "style_guide.md").read_text()


def strategy_skill() -> str:
    """The viral-shorts-strategy skill — house judgment injected into Director prompts."""
    path = ROOT / ".claude" / "skills" / "viral-shorts-strategy" / "SKILL.md"
    return path.read_text() if path.exists() else ""


def checkpoint_mode(name: str, default: str = "auto") -> str:
    """auto | manual for a pipeline checkpoint, read from controls.yaml."""
    return controls().get("checkpoints", {}).get(name, default)


def ffmpeg_bin(tool: str = "ffmpeg") -> str:
    found = shutil.which(tool)
    if found:
        return found
    local = Path.home() / ".local" / "bin" / tool
    if local.exists():
        return str(local)
    raise RuntimeError(f"{tool} not found — install it or put it in ~/.local/bin")


def run_cmd(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args[:3])}...\n{proc.stderr[-2000:]}")


def media_duration(path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def _openrouter_headers() -> dict:
    """Auth + the optional attribution headers OpenRouter recommends (rankings/limits)."""
    h = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    ref = os.getenv("OPENROUTER_REFERER", "https://github.com/local/content-automation")
    title = os.getenv("OPENROUTER_TITLE", "content-automation")
    if ref:
        h["HTTP-Referer"] = ref
    if title:
        h["X-Title"] = title
    return h


def _effective_provider(provider: str) -> str:
    """Degrade to a provider whose key is actually present, so flipping a station to
    'openrouter' before you've added OPENROUTER_API_KEY keeps working on your existing
    Anthropic key, and everything falls back to local ollama as the last free rung."""
    has_or = bool(os.getenv("OPENROUTER_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "openrouter" and not has_or:
        return "anthropic" if has_anthropic else "ollama"
    if provider == "anthropic" and not has_anthropic:
        return "openrouter" if has_or else "ollama"
    return provider


def llm(prompt: str, system: str = "", max_tokens: int = 8000, station: str = "",
        provider: str = "", model: str = "") -> str:
    # Provider ladder: per-station choice from controls.yaml, else env, else anthropic.
    # Missing keys degrade to a provider that has one (see _effective_provider) so the
    # pipeline never dead-ends. `provider`/`model` force a specific rung — the eval
    # harness uses this to benchmark the same station across providers.
    if not provider:
        if station:
            provider = station_provider(station, os.getenv("LLM_PROVIDER", "openrouter"))
        else:
            provider = os.getenv("LLM_PROVIDER", "openrouter")
    provider = _effective_provider(provider)
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model or os.getenv("LLM_MODEL", "claude-sonnet-5"),
            max_tokens=max_tokens,
            system=system or "You are a precise assistant.",
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
    if provider == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=_openrouter_headers(),
            json={
                "model": model or os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5"),
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system or "You are a precise assistant."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    # local rung (ollama)
    resp = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": model or os.getenv("OLLAMA_MODEL", "gpt-oss"),
            "messages": [
                {"role": "system", "content": system or "You are a precise assistant."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def llm_json(prompt: str, system: str = "", station: str = "",
             provider: str = "", model: str = "") -> dict | list:
    """Call the LLM and parse a JSON object/array out of the reply."""
    text = llm(prompt, system, station=station, provider=provider, model=model)
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=0)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    return json.loads(text[start:end])
