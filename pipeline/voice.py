"""Voice: per-segment TTS. Kokoro (free, local) by default; ElevenLabs when
voice.provider: elevenlabs is set; macOS `say` as last-resort fallback."""
import os
import subprocess
import time
from pathlib import Path

import requests

from .util import ROOT, ffmpeg_bin, run_cmd, settings, station_provider

MODELS_DIR = ROOT / "assets" / "models"
_KOKORO = None  # lazy singleton — loading the ONNX model is slow

# Kokoro has no emotion tags; approximate emotional arc via delivery speed.
KOKORO_SPEED = {
    "excited": 1.12,
    "urgent": 1.15,
    "amazed": 1.08,
    "curious": 1.0,
    "confident": 1.0,
    "serious": 0.92,
}

# ElevenLabs v3 audio tags per script emotion
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


def _kokoro():
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro
        onnx = MODELS_DIR / "kokoro-v1.0.onnx"
        voices = MODELS_DIR / "voices-v1.0.bin"
        if not (onnx.exists() and voices.exists()):
            raise RuntimeError(
                f"Kokoro model files missing in {MODELS_DIR} — "
                "download kokoro-v1.0.onnx and voices-v1.0.bin from the kokoro-onnx releases page."
            )
        _KOKORO = Kokoro(str(onnx), str(voices))
    return _KOKORO


def _kokoro_tts(text: str, emotion: str, out_mp3: Path) -> None:
    import soundfile as sf
    voice = settings().get("voice", {}).get("kokoro_voice", "am_michael")
    speed = KOKORO_SPEED.get(emotion, 1.0)
    samples, sample_rate = _kokoro().create(text, voice=voice, speed=speed, lang="en-us")
    wav = out_mp3.with_suffix(".wav")
    sf.write(str(wav), samples, sample_rate)
    run_cmd([ffmpeg_bin(), "-y", "-i", str(wav), "-ar", "44100", str(out_mp3)])
    wav.unlink()


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
    for attempt in range(3):
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json=body,
            params={"output_format": "mp3_44100_128"},
            timeout=120,
        )
        if resp.ok:
            out_mp3.write_bytes(resp.content)
            try:  # ElevenLabs bills per character — record what we sent (best-effort)
                from . import usage
                usage.record("tts", station="voice", stage="voice.synthesize",
                             provider="elevenlabs", model=model, characters=len(text))
            except Exception:
                pass
            return
        # Don't retry client errors (401 quota, 403, 400 bad model) — they won't fix
        # themselves and just waste time. Only retry rate-limits (429) and 5xx.
        if resp.status_code not in (429,) and resp.status_code < 500:
            resp.raise_for_status()
        if attempt < 2:
            print(f"  [voice] elevenlabs {resp.status_code}, retrying...")
            time.sleep(3 * (attempt + 1))
    resp.raise_for_status()


def _trim_silence(mp3: Path) -> None:
    """Cut dead air from edges AND mid-sentence pauses (SOP: trim blank spaces from the voiceover)."""
    edge = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08"
    interior = "silenceremove=stop_periods=-1:stop_threshold=-45dB:stop_silence=0.35"
    tmp = mp3.with_suffix(".trim.mp3")
    run_cmd([ffmpeg_bin(), "-y", "-i", str(mp3),
             "-af", f"{edge},areverse,{edge},areverse,{interior}", str(tmp)])
    tmp.replace(mp3)


def _macos_say(text: str, out_mp3: Path) -> None:
    aiff = out_mp3.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    run_cmd([ffmpeg_bin(), "-y", "-i", str(aiff), "-ar", "44100", str(out_mp3)])
    aiff.unlink()


import hashlib
import shutil

CACHE_DIR = ROOT / "state" / "tts_cache"


def _cache_key(provider: str, voice: str, model: str, emotion: str, text: str) -> str:
    """Identity of a synthesized clip. Re-renders with the SAME text/voice reuse the
    cached audio instead of re-synthesizing — critical for paid ElevenLabs, so iterating
    on visuals never re-bills the voiceover."""
    raw = f"{provider}|{voice}|{model}|{emotion}|{text}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _voice_id(provider: str) -> str:
    cfg = settings().get("voice", {})
    if provider == "elevenlabs":
        return os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb")
    if provider == "kokoro":
        return cfg.get("kokoro_voice", "am_michael")
    return "say"


def synthesize(script: dict, run_dir: Path) -> list[Path]:
    """One audio file per segment; returns paths in order. Cached by text+voice so
    re-renders don't re-synthesize (and don't re-bill paid providers)."""
    provider = station_provider("voice", settings().get("voice", {}).get("provider", "kokoro"))
    if provider == "elevenlabs" and not os.getenv("ELEVENLABS_API_KEY"):
        print("  [voice] provider=elevenlabs but no ELEVENLABS_API_KEY — falling back to kokoro")
        provider = "kokoro"
    model = settings().get("voice", {}).get("model", "") if provider == "elevenlabs" else ""
    voice = _voice_id(provider)
    print(f"  [voice] provider: {provider} (voice {voice})")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    hits = 0
    for i, seg in enumerate(script["segments"]):
        out = run_dir / f"seg_{i:02d}.mp3"
        emotion = seg.get("emotion", "")
        cached = CACHE_DIR / f"{_cache_key(provider, voice, model, emotion, seg['voiceover'])}.mp3"
        if cached.exists():
            shutil.copyfile(cached, out)
            hits += 1
            paths.append(out)
            continue
        if provider == "elevenlabs":
            try:
                _elevenlabs(seg["voiceover"], emotion, out)
            except Exception as e:
                # e.g. the API key's per-key character cap is exhausted (quota_exceeded).
                # Don't crash the render — drop to free local Kokoro for the rest of it.
                print(f"  [voice] elevenlabs failed ({str(e)[:120]}) — falling back to kokoro for this run")
                provider, voice, model = "kokoro", _voice_id("kokoro"), ""
                cached = CACHE_DIR / f"{_cache_key(provider, voice, model, emotion, seg['voiceover'])}.mp3"
                if cached.exists():
                    shutil.copyfile(cached, out); paths.append(out); continue
                _kokoro_tts(seg["voiceover"], emotion, out)
        elif provider == "kokoro":
            try:
                _kokoro_tts(seg["voiceover"], emotion, out)
            except Exception as e:
                print(f"  [voice] kokoro failed ({e}), falling back to macOS say")
                _macos_say(seg["voiceover"], out)
        else:
            _macos_say(seg["voiceover"], out)
        _trim_silence(out)
        shutil.copyfile(out, cached)  # store the finished (trimmed) clip for reuse
        paths.append(out)
    if hits:
        print(f"  [voice] {hits}/{len(paths)} segments served from cache (no re-synthesis)")
    return paths
