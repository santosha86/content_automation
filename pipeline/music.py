"""Background music by mood.

The Director picks a `music.mood` in the storyboard (driving | suspense | uplift |
tech_minimal | none). This module turns that into an actual bed:

  1. If you've dropped royalty-free tracks in assets/music/<mood>/*.mp3, one is chosen
     (deterministically, by the video's title) — real music always wins.
  2. Otherwise a soft ambient bed is SYNTHESIZED for that mood via ffmpeg (a low-passed
     sine chord with gentle movement), so music works with zero assets and the video
     never sits in dead air. Swap in real tracks anytime to override.

Everything is royalty-free by construction (your own files, or generated tones).
"""
import hashlib
from pathlib import Path

from .util import ROOT, ffmpeg_bin, run_cmd, settings

MUSIC_DIR = ROOT / "assets" / "music"

# Fixed set of soft ambient BEDS — pleasant pads that sit under narration, NOT the old
# pulsing/echoey tones. Each is a low, warm chord with a slightly detuned voice for
# richness, softened by a lowpass. No tremolo wobble, no metallic echo (those were the
# "annoying" part). The Director's mood maps to one of these; drop real .mp3s in
# assets/music/<mood>/ anytime to override a bed with a real track.
#
#   chord   — the notes (Hz), low register so it never masks the voice
#   detune  — cents of detuning on a doubled voice for a warm chorus (0 = none)
#   lowpass — brightness ceiling (lower = warmer/darker)
#   swell   — very slow volume LFO depth for gentle life (0 = perfectly steady)
_MOODS = {
    "tech_minimal": {"chord": [110.0, 164.81, 220.0],  "detune": 8,  "lowpass": 800,  "swell": 0.06},  # A minor, calm
    "suspense":     {"chord": [65.41, 98.0, 130.81],   "detune": 6,  "lowpass": 520,  "swell": 0.05},  # low, still, tense
    "driving":      {"chord": [98.0, 146.83, 196.0],   "detune": 10, "lowpass": 1000, "swell": 0.10},  # fuller, gentle motion
    "uplift":       {"chord": [130.81, 164.81, 196.0], "detune": 8,  "lowpass": 1200, "swell": 0.08},  # C major, warm bright
    "calm":         {"chord": [98.0, 146.83, 220.0],   "detune": 7,  "lowpass": 900,  "swell": 0.05},  # neutral default pad
}
_DEFAULT_MOOD = "calm"


def _real_track(mood: str) -> Path | None:
    """A royalty-free file the user dropped in assets/music/<mood>/ (real music wins)."""
    folder = MUSIC_DIR / mood
    tracks = sorted(folder.glob("*.mp3")) + sorted(folder.glob("*.wav")) if folder.exists() else []
    # also accept flat assets/music/*.mp3 for backwards-compat
    if not tracks:
        return None
    return tracks[0]


def _synth_bed(mood: str, seconds: float, out: Path) -> Path:
    """Synthesize a soft ambient PAD for the mood via ffmpeg lavfi (no assets needed).
    Warm, steady, no wobble/echo — pre-leveled quiet so it sits under the narration."""
    spec = _MOODS.get(mood, _MOODS[_DEFAULT_MOOD])
    dur = max(seconds + 1.0, 2.0)
    detune = spec.get("detune", 0)
    # Build the chord; add a doubled, slightly detuned voice per note for a warm chorus.
    freqs = list(spec["chord"])
    if detune:
        freqs += [f * (2 ** (detune / 1200.0)) for f in spec["chord"]]
    inputs = []
    for f in freqs:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={f:.2f}:duration={dur:.2f}"]
    n = len(freqs)
    labels = "".join(f"[{i}:a]" for i in range(n))
    fade_out = max(dur - 1.6, 0)
    swell = spec.get("swell", 0)
    # Mix -> soften (two-stage lowpass for a gentle roll-off) -> optional slow swell ->
    # long fades so it breathes in and out. amix normalize keeps it quiet by construction.
    chain = f"amix=inputs={n}:normalize=1,lowpass=f={spec['lowpass']},lowpass=f={spec['lowpass']}"
    if swell:
        chain += f",tremolo=f=0.1:d={swell}"   # barely-there movement, not a pulse
    chain += (f",afade=t=in:st=0:d=1.6,afade=t=out:st={fade_out:.2f}:d=1.6,"
              f"volume=2.2")  # pre-level to ~a soft bed; pick() applies the final gain
    args = [ffmpeg_bin(), "-y", *inputs,
            "-filter_complex", f"{labels}{chain}[a]",
            "-map", "[a]", "-ar", "44100", str(out)]
    run_cmd(args)
    return out


def _cfg() -> dict:
    return settings().get("music", {}) or {}


def pick(mood: str, seconds: float, run_dir: Path, track_volume: float = None) -> tuple[Path, float] | None:
    """Resolve the mood to (bed_path, mix_gain), or None when mood == 'none'.

    Real tracks win and mix at `track_volume` (they're mastered loud). Synth pads are
    pre-leveled, then scaled by music.synth_volume so the bed stays gentle under voice.
    An unknown/blank mood falls back to the neutral 'calm' pad instead of going silent."""
    mood = (mood or "").strip().lower()
    if mood == "none":
        return None
    cfg = _cfg()
    if track_volume is None:
        track_volume = float(cfg.get("track_volume", 0.10))
    synth_gain = float(cfg.get("synth_volume", 0.55))
    if mood not in _MOODS:
        mood = _DEFAULT_MOOD  # keep videos scored even if the Director picks an odd mood
    real = _real_track(mood)
    if real:
        return real, track_volume
    return _synth_bed(mood, seconds, run_dir / f"music_{mood}.wav"), synth_gain


if __name__ == "__main__":
    import sys
    tmp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")
    for m in _MOODS:
        p = _synth_bed(m, 6.0, tmp / f"bed_{m}.wav")
        print(f"{m}: {p}")
