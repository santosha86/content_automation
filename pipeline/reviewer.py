"""Reviewer Agent: vision QA of the finished video against Gate B of checklist.schema.json.

Contract: checklist.schema.json (grading items) + reviewer-agent.prompt.md (system prompt).
Gap-only feedback; runs only when ANTHROPIC_API_KEY is set.
"""
import base64
import json
import os
import re
import subprocess
from pathlib import Path

import requests

from .util import (ROOT, ffmpeg_bin, media_duration, run_cmd, station_provider,
                   _effective_provider, _openrouter_headers)

FALLBACK_MODEL = "claude-sonnet-5"


def _keyframes(video: Path, run_dir: Path) -> list[tuple[str, Path]]:
    dur = media_duration(video)
    marks = [
        ("frame_0", 0.05),
        ("frames_0_2s_a", 0.9),
        ("frames_0_2s_b", 1.8),
        ("sampled_mid1", dur * 0.35),
        ("broll", dur * 0.55),
        ("outro", dur * 0.85),
        ("last", max(dur - 0.3, 0)),
    ]
    frames = []
    for label, t in marks:
        out = run_dir / f"qa_{label}.jpg"
        run_cmd([ffmpeg_bin(), "-y", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(out)])
        frames.append((label, out))
    return frames


def _silence_report(video: Path) -> str:
    proc = subprocess.run(
        [ffmpeg_bin(), "-i", str(video), "-af", "silencedetect=noise=-40dB:d=0.4",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    gaps = re.findall(r"silence_(?:start|end): ([\d.]+)", proc.stderr)
    return f"silence gaps >0.4s at (start/end pairs, seconds): {gaps}" if gaps else "no dead-air gaps > 0.4s detected"


def _export_metadata(video: Path, slug: str) -> dict:
    proc = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "quiet", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    info = json.loads(proc.stdout)
    stream = next(s for s in info["streams"] if s.get("width"))
    return {
        "width": stream["width"], "height": stream["height"],
        "aspect": f"{stream['width']}:{stream['height']}",
        "duration_s": round(float(info["format"]["duration"]), 1),
        "filename": video.name,
        "filename_convention": f"{slug}.mp4",
    }


def _parse_caption_cues(subs: Path) -> list[dict]:
    """One entry per Caption-style dialogue line, with an explicit word_count
    so B3 grading doesn't have to eyeball adjacent short cues in raw ASS text."""
    cues = []
    for line in subs.read_text().splitlines():
        if not line.startswith("Dialogue: 0,") or ",Caption,,0,0,0,," not in line:
            continue
        head, text = line.split(",Caption,,0,0,0,,", 1)
        _, start, end, *_ = head.split(",")
        clean = re.sub(r"\{[^}]*\}", "", text).strip()
        cues.append({"start": start, "end": end, "text": clean, "word_count": len(clean.split())})
    return cues


def _grade_openrouter(system: str, frames: list, payload_text: str) -> dict | None:
    """Vision grade via OpenRouter (OpenAI-style image_url blocks) so the whole pipeline
    can run on a single OpenRouter recharge. Returns None to let the caller fall back."""
    user_content = []
    for label, frame in frames:
        b64 = base64.b64encode(frame.read_bytes()).decode()
        user_content.append({"type": "text", "text": f"keyframe: {label}"})
        user_content.append({"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    user_content.append({"type": "text", "text": payload_text})
    model = os.getenv("OPENROUTER_VISION_MODEL", "anthropic/claude-sonnet-4.5")
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=_openrouter_headers(),
            json={"model": model, "max_tokens": 4096,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user_content}]},
            timeout=600,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0))
    except Exception as e:
        print(f"  [reviewer] openrouter vision failed: {str(e)[:160]}")
        return None


def grade(video: Path, run_dir: Path, review_dir: Path, script: dict, slug: str) -> dict | None:
    provider = station_provider("reviewer", os.getenv("LLM_PROVIDER", "openrouter"))
    if provider == "skip":
        print("  [reviewer] provider=skip — QA gate disabled in config")
        return None
    provider = _effective_provider(provider)
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        provider = "anthropic"  # _effective_provider already tried; be explicit for vision
    if provider != "openrouter" and not os.getenv("ANTHROPIC_API_KEY"):
        print("  [reviewer] no vision-capable key (OPENROUTER_API_KEY / ANTHROPIC_API_KEY) — skipping QA gate")
        return None

    checklist = json.loads((ROOT / "checklist.schema.json").read_text())
    gate_b = [i for i in checklist["gates"]["gate_b_pre_publish"] if i["auto_checkable"]]
    system = (ROOT / "reviewer-agent.prompt.md").read_text()

    subs = run_dir / "subs.ass"
    caption_cues = _parse_caption_cues(subs) if subs.exists() else "caption file missing"
    payload = {
        "checklist": gate_b,
        "caption_file": caption_cues,
        "audio_meta": _silence_report(video),
        "export_metadata": _export_metadata(video, slug),
        "script_context": {
            "topic": script["topic"]["title"],
            "hook_text": script.get("hook_text", ""),
            "broll_queries": [s.get("broll_query", "") for s in script["segments"]],
            "note": "Pipeline renders a branded end-card in the last ~2s (grade B8 on the final frames). The brief silence UNDER that end-card is the intentional end_with_silence bookend (music bed arrives later) — grade B5 only for dead-air gaps WITHIN the narration, not the trailing end-card. Face-cam layout still arrives later — grade B4 factually.",
        },
    }
    frames = _keyframes(video, run_dir)
    payload_text = json.dumps(payload, indent=1)
    report = None

    if provider == "openrouter":
        report = _grade_openrouter(system, frames, payload_text)

    # Anthropic path (primary when reviewer=anthropic, or fallback if OpenRouter vision failed).
    if report is None and os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        content = []
        for label, frame in frames:
            content.append({"type": "text", "text": f"keyframe: {label}"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.b64encode(frame.read_bytes()).decode()},
            })
        content.append({"type": "text", "text": payload_text})
        client = anthropic.Anthropic()
        model = os.getenv("REVIEWER_MODEL", os.getenv("LLM_MODEL", FALLBACK_MODEL))
        for attempt_model in [model, FALLBACK_MODEL]:
            try:
                msg = client.messages.create(
                    model=attempt_model, max_tokens=4096, system=system,
                    output_config={"effort": "low"},
                    messages=[{"role": "user", "content": content}],
                )
                if msg.stop_reason == "refusal":
                    continue  # refusal -> fall back to next model per reviewer prompt
                text = "".join(b.text for b in msg.content if b.type == "text")
                m = re.search(r"\{.*\}", text, re.DOTALL)
                report = json.loads(m.group(0))
                break
            except Exception as e:
                print(f"  [reviewer] {attempt_model} failed: {e}")
    if report is None:
        report = {"overall": "fail", "items": [],
                  "summary": "reviewer_unavailable_fallback"}

    (review_dir / "review_report.json").write_text(json.dumps(report, indent=2))
    gaps = [i for i in report.get("items", []) if i.get("result") == "fail"]
    print(f"  [reviewer] overall: {report.get('overall', '?').upper()}")
    for g in gaps:
        print(f"    GAP {g['id']}: {g.get('gap_note', '')}")
    return report
