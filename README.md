# Content Automation — Shorts/Reels Factory

Automated pipeline: AI news (RSS) → script → voiceover → b-roll → karaoke captions → finished 9:16 video in a review folder. One command per video, one manual step (your approval).

## Pipeline

```
scout → writer → voice → visuals → editor  → packager → reviewer → output/review/
 RSS     LLM    Kokoro   Pexels    ffmpeg    metadata    vision QA    YOU approve
                (local)            +whisper  (gate B checklist)
```

The **brain** lives in `config/`:
- `style_guide.md` — hook rules, emotional arc, structure (the Analyst agent will tune this in Phase 4)
- `feeds.yaml` — news sources
- `settings.yaml` — video/caption/voice/timing knobs
- `checklist.schema.json` + `reviewer-agent.prompt.md` — the QA gate contract graded by `pipeline/reviewer.py`

## Setup (one time)

Uses a **conda** environment (Python 3.11) at
`/Users/santosh_work/Work/Development/Environments/content_automation_env`, with
dependencies pinned in `requirements.txt`.

```bash
make setup          # creates the conda env, installs requirements.txt
cp .env.example .env
# edit .env: ANTHROPIC_API_KEY (required for quality), PEXELS_API_KEY
```

Then download the free local voice model (one-time, ~340MB, no account needed):

```bash
mkdir -p assets/models && cd assets/models
curl -sL -o kokoro-v1.0.onnx  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -sL -o voices-v1.0.bin   https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

**Voice cost: $0.** Kokoro (open-source TTS) runs locally on your Mac and is the default —
no ElevenLabs subscription needed. `config/settings.yaml` → `voice.provider: kokoro`.
Switch to `elevenlabs` there (+ `ELEVENLABS_API_KEY` in `.env`) only if you later want
emotional audio-tag delivery via their paid API ($5/mo Starter tier is enough for 1/day).

Keyless fallbacks exist for every paid station: Ollama for scripts, macOS `say` for voice,
generated backgrounds for b-roll — the pipeline runs end-to-end with just `ANTHROPIC_API_KEY`
+ the free Kokoro model, no other spend required.

## Daily use

```bash
make video                          # scout picks today's best AI story
make video-topic TOPIC="..."        # you choose the topic
```

Output lands in `output/review/<date>-<slug>/` with the .mp4 and platform-ready `metadata.json` (YouTube title/description, IG caption, hashtags).

Optional: drop royalty-free .mp3 tracks in `assets/music/` for an automatic background bed.

## Roadmap

- **Phase 1 (this)**: one-command video → review folder
- **Phase 2**: AI avatar station (HeyGen), Telegram approval bot, auto-publish (YouTube Data API + Instagram Graph API)
- **Phase 3**: cloned voice + avatar, multiple formats, batch weekly production
- **Phase 4**: analytics loop — Analyst agent reads YT/IG metrics, rewrites `style_guide.md`, A/B tests hooks
