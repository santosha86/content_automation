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

## Dashboard

A local control panel — no terminal needed day-to-day.

```bash
make dashboard        # http://localhost:8420
```

- **Generate** — trigger a new video (Scout picks the topic, or type one in), watch the run's log live
- **Runs** — every video as a card: thumbnail, QA gate result, approval status
- **Review** — click a card to play the video, read the YouTube/Instagram copy, see the QA checklist gap-by-gap, and Approve/Reject
- **Config** — auto/manual switch per checkpoint (default: auto) and provider ladder per station
  (local free → free API credits → paid). Persists to `config/controls.yaml`.

## Roadmap

See the [Project Scope](https://claude.ai/code/artifact/46a0f7dc-6f98-4ebc-949b-8873beab5591) and [Delivery Plan](https://claude.ai/code/artifact/970c5149-11c0-4847-84f5-37c05b1eaddf) documents for the full picture. The Director's contract lives in `config/storyboard.schema.json`; content judgment lives in `.claude/skills/viral-shorts-strategy/`.

- **Done**: repo + env + config-as-brain · one-command QA-gated video · dashboard · Config page + provider ladder + storyboard schema + strategy skill
- **Done — Phase A (Director core)**: Strategist (Tavily + GitHub-trending + ai_news lanes, top-3 ranked) · Hook Smith (3 distinct-formula variants) · Writer+Critic loop (graded against the retention structure) · Director (storyboard validated against the schema, retry-until-valid) · checkpoint pause/resume plumbing + dashboard choice UI · eval harness + blind-A/B Evals tab (ollama vs anthropic per station). Run `make plan` for a storyboard, `make eval` for a benchmark.
- **Phase B — in progress**: storyboard now renders end-to-end via `python -m pipeline.run --storyboard PATH` (adapter maps beats→segments + generates platform metadata). Still to craft: `must_show` proof b-roll relevance, FLUX local image gen for `generated_image` beats, split-screen/zoom layouts, background music by mood, branded end-card (the three Gate B gaps a storyboard render currently flags).
- **Phase C**: publisher — YouTube Data API + Instagram Graph API, scheduled daily run
- **Phase D**: your cloned voice, local-only (Chatterbox, per-emotion reference clips); avatar evaluation
- **Phase E**: analytics loop — Analyst agent (Fable 5) reads YT/IG metrics, proposes `style_guide.md` edits, A/B tests hooks
