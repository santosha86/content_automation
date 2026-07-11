"""Voice: per-segment TTS. ElevenLabs when key present, macOS `say` fallback for testing."""
import os
import subprocess
from pathlib import Path

import requests

from .util import ffmpeg_bin, run_cmd


def _elevenlabs(text: str, out_mp3: Path) -> None:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb")
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.05},
        },
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
            _elevenlabs(seg["voiceover"], out)
        else:
            _macos_say(seg["voiceover"], out)
        paths.append(out)
    return paths
