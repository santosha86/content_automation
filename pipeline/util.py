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


def llm(prompt: str, system: str = "", max_tokens: int = 8000, station: str = "") -> str:
    # Provider ladder: per-station choice from controls.yaml, else env, else anthropic.
    # Missing keys fall through to the next rung so the pipeline never dead-ends.
    if station:
        provider = station_provider(station, os.getenv("LLM_PROVIDER", "anthropic"))
    else:
        provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.getenv("LLM_MODEL", "claude-sonnet-5"),
            max_tokens=max_tokens,
            system=system or "You are a precise assistant.",
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
    if provider == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={
                "model": os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3.1:free"),
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
    # local rung
    resp = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": os.getenv("OLLAMA_MODEL", "gpt-oss"),
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


def llm_json(prompt: str, system: str = "", station: str = "") -> dict | list:
    """Call the LLM and parse a JSON object/array out of the reply."""
    text = llm(prompt, system, station=station)
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=0)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    return json.loads(text[start:end])
