"""Voice: per-segment TTS. ElevenLabs when key present, macOS `say` fallback for testing."""
import os
import subprocess
from pathlib import Path

import requests

from .util import ffmpeg_bin, run_cmd, settings

# v3 audio tags per script emotion
EMOTION_TAGS = {
    "excited": "[excited]",
    "curious": "[curious]",
    "serious": "[serious]",
    "amazed": "[amazed]",
    "urgent": "[rushed]",
    "confident": "[confident]",
}
# v2 has no tags — approximate emotion with voice settings (lower stability = more expressive)
V2_SETTINGS = {
    "excited":   {"stability": 0.30, "style": 0.65},
    "amazed":    {"stability": 0.30, "style": 0.60},
    "urgent":    {"stability": 0.35, "style": 0.55},
    "curious":   {"stability": 0.40, "style": 0.45},
    "confident": {"stability": 0.50, "style": 0.35},
    "serious":   {"stability": 0.60, "style": 0.25},
}


def _elevenlabs(text: str, emotion: str, out_mp3: Path) -> None:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb")
    model = settings().get("voice", {}).get("model", "eleven_v3")
    if model.startswith("eleven_v3"):
        tag = EMOTION_TAGS.get(emotion, "")
        body = {"text": f"{tag} {text}".strip(), "model_id": model}
    else:
        vs = V2_SETTINGS.get(emotion, {"stability": 0.5, "style": 0.4})
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": {**vs, "similarity_boost": 0.75, "speed": 1.05},
        }
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json=body,
        params={"output_format": "mp3_44100_128"},
        timeout=120,
    )
    resp.raise_for_status()
    out_mp3.write_bytes(resp.content)


def _macos_say(text: str, out_mp3: Path) -> None:
    aiff = out_mp3.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    run_cmd([ffmpeg_bin(), "-y", "-i", str(aiff), "-ar", "44100", str(out_mp3)])
    aiff.unlink()


def synthesize(script: dict, run_dir: Path) -> list[Path]:
    """One audio file per segment; returns paths in order."""
    use_eleven = bool(os.getenv("ELEVENLABS_API_KEY"))
    if not use_eleven:
        print("  [voice] no ELEVENLABS_API_KEY — using macOS `say` (test quality)")
    paths = []
    for i, seg in enumerate(script["segments"]):
        out = run_dir / f"seg_{i:02d}.mp3"
        if use_eleven:
            _elevenlabs(seg["voiceover"], seg.get("emotion", ""), out)
        else:
            _macos_say(seg["voiceover"], out)
        paths.append(out)
    return paths
