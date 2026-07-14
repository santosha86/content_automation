# Usage Dashboard — Design Spec

Per-video token consumption and spend, with per-stage drill-down. Spec for implementation (Opus session); design session 2026-07-11.

## Problem

No token usage or cost is captured anywhere today. All text LLM calls funnel through `util.llm()` / `util.llm_json()` (`pipeline/util.py:73-137`) which return only the content string and discard the response's usage block on all three provider rungs (Anthropic `msg.usage`, OpenRouter `json["usage"]`, Ollama `prompt_eval_count`/`eval_count`). One call bypasses that helper: `reviewer.grade()` builds its own Anthropic client (`pipeline/reviewer.py:116-126`, vision QA with 7 base64 keyframes — the most expensive single call in the pipeline) and also discards `msg.usage`. Non-token paid usage: ElevenLabs TTS (billed per character, `pipeline/voice.py:85-91`) and Tavily search (billed per request, `pipeline/strategist.py:71-76`).

## Architecture

```
capture (usage.py collector, instrumented call sites)
  → persist (output/runs/<slug>/usage.json — raw counts only, no prices)
  → price (config/pricing.yaml, applied at READ time by the server)
  → serve (GET /api/usage, GET /api/usage/{slug})
  → UI (new "Usage" tab in the existing vanilla-JS dashboard)
```

Costs are computed at read time so a pricing correction retroactively fixes every historical video. usage.json stores only raw counts (tokens / characters / requests).

## 1. Collector — new module `pipeline/usage.py`

Module-level singleton; works because each pipeline invocation (`python -m pipeline.run`, `python -m pipeline.plan`) is one process (the dashboard spawns them as subprocesses, `pipeline/ui/server.py:43-46`).

API:

- `usage.record(kind, *, station, stage, provider, model=None, input_tokens=0, output_tokens=0, characters=0, requests=0, duration_ms=None)` — appends a record. `kind` ∈ `llm | tts | search`. Timestamp added automatically (ISO 8601).
- `usage.bind(run_dir, phase)` — called by `run.py` / `plan.py` as soon as the slug is known (the Scout/Strategist call happens *before* the slug exists — records are buffered in memory until bind, then flushed). `phase` ∈ `plan | render`.
- Every record after bind triggers an atomic write (tmp + `os.replace`) of `<run_dir>/usage.json`, so a crashed run still has partial usage.
- If the process exits without `bind()` (e.g. scout failed before picking a story), buffered records are dropped — acceptable.

### usage.json schema

```json
{
  "slug": "2026-07-11-apple-sues-openai-...",
  "sessions": [
    {
      "phase": "plan",
      "started_at": "2026-07-11T09:12:03Z",
      "records": [
        {"ts": "...", "kind": "llm", "station": "writer", "stage": "scriptwriter.draft",
         "provider": "anthropic", "model": "claude-sonnet-5",
         "input_tokens": 1834, "output_tokens": 612, "duration_ms": 4100},
        {"ts": "...", "kind": "search", "station": "scout", "stage": "strategist.tavily",
         "provider": "tavily", "requests": 3},
        {"ts": "...", "kind": "tts", "station": "voice", "stage": "voice.synthesize",
         "provider": "elevenlabs", "characters": 912}
      ]
    },
    {"phase": "render", "started_at": "...", "records": ["..."]}
  ]
}
```

`plan` and a later `--storyboard` render append separate sessions to the same file (both paths derive the same slug). Multiple renders of the same slug append additional sessions — the dashboard sums them (that IS the real spend).

## 2. Instrumentation points

### `util.llm()` — the chokepoint (covers 9 call sites)

Capture per rung, then `usage.record(...)` before returning the string:

| Rung | Where usage lives |
|---|---|
| Anthropic (`util.py:87-94`) | `msg.usage.input_tokens`, `msg.usage.output_tokens` (+ `cache_read_input_tokens`/`cache_creation_input_tokens` if present — store them, priced at 0 for now) |
| OpenRouter (`util.py:96-110`) | response JSON `["usage"]["prompt_tokens"]` / `["completion_tokens"]` |
| Ollama (`util.py:112-125`) | `["prompt_eval_count"]` / `["eval_count"]` (tokens tracked, cost is $0) |

Signature change: `llm(..., station=..., stage=None)` — `stage` defaults to `station`. Update call sites to pass a distinguishing stage label:

| Call site | stage |
|---|---|
| `scout.py:63` | `scout.pick` |
| `strategist.py:125` | `strategist.rank` |
| `hooksmith.py:23` | `hooksmith.variants` |
| `scriptwriter.py:33` | `scriptwriter.draft` (up to 3× per run) |
| `scriptwriter.py:75` | `scriptwriter.critique` (up to 3×) |
| `director.py:68` | `director.storyboard` (up to 3 retries) |
| `storyboard_adapter.py:32` | `adapter.metadata` |
| `writer.py:7` | `writer.script` (legacy path) |
| `evalharness.py:76` | `eval.<station>` — **excluded from the video dashboard** (eval slugs live in `output/evals/`, not per-video spend; still recorded for completeness, filtered out server-side) |

Recording failures must never break a run: wrap capture in try/except and proceed.

### `reviewer.grade()` — second capture point

After `client.messages.create` (`reviewer.py:121-125`): `usage.record("llm", station="reviewer", stage="reviewer.grade", provider="anthropic", model=<resolved model>, ...)`.

### Non-LLM paid usage

- ElevenLabs (`voice.py:85-91`): `usage.record("tts", station="voice", stage="voice.synthesize", provider="elevenlabs", characters=len(text))`. Kokoro/`say` are free-local — record nothing.
- Tavily (`strategist.py:71-76`): `usage.record("search", station="scout", stage="strategist.tavily", provider="tavily", requests=1)` per call.
- Free/local stages (editor, packager, kokoro, FLUX, Pexels, ffmpeg, GitHub scrape) record nothing; the UI lists them as `$0 · local` for completeness from a static stage list.

### bind() wiring

- `pipeline/run.py`: after the slug is computed (`run.py:36/52`), `usage.bind(run_dir, phase="render")`.
- `pipeline/plan.py`: after slug (`plan.py:91`), `usage.bind(run_dir, phase="plan")`.

## 3. Pricing — new `config/pricing.yaml`

```yaml
# Prices applied at read time. Raw counts live in usage.json; edit here to
# retro-correct all historical videos. Unknown model => cost shown as "unpriced".
llm:  # USD per 1M tokens
  claude-sonnet-5:            {input: 3.00, output: 15.00}   # intro pricing 2.00/10.00 through 2026-08-31
  claude-opus-4-8:            {input: 5.00, output: 25.00}
  claude-haiku-4-5:           {input: 1.00, output: 5.00}
  "deepseek/deepseek-chat-v3.1:free": {input: 0, output: 0}  # OpenRouter free tier
  gpt-oss:                    {input: 0, output: 0}          # Ollama local
tts:  # USD per 1K characters
  elevenlabs: {per_1k_chars: 0.30}   # adjust to actual plan
search:  # USD per request
  tavily: {per_request: 0.008}       # adjust to actual plan
```

Rules: provider `ollama` always $0 regardless of model name. A model missing from the table → `cost: null`, surfaced as an "unpriced" badge (never silently $0). Anthropic model prices above verified 2026-07-11.

## 4. Server — `pipeline/ui/server.py`

- `GET /api/usage` → scan `output/runs/*/usage.json` (skip `output/evals/`), join titles/status from `_load_run` (`server.py:97`) by slug. Returns:

```json
{
  "totals": {"cost_usd": 1.84, "input_tokens": 812000, "output_tokens": 96000,
             "videos_tracked": 9, "videos_untracked": 4},
  "videos": [
    {"slug": "...", "title": "...", "date": "2026-07-11", "status": "approved",
     "cost_usd": 0.214, "input_tokens": 91000, "output_tokens": 12000,
     "llm_calls": 11, "providers": ["anthropic", "ollama", "tavily"],
     "has_unpriced": false, "tracked": true}
  ]
}
```

Videos found in `output/review/` with no usage.json are listed with `tracked: false` (runs that predate instrumentation).

- `GET /api/usage/{slug}` → the detail view: records grouped by `stage` within each session, each group with call count, models used, summed input/output tokens, characters/requests, and computed cost; plus the static free-stage list. Pricing loaded from `config/pricing.yaml` on each request (it's tiny; no caching needed).

## 5. UI — Usage tab

Frontend is vanilla JS (`pipeline/ui/static/`): add `<button class="tab" data-view="usage">` (index.html:19-23), a `<main class="page" id="view-usage">`, a `loadUsage()` branch in the tab switch (app.js:326-338). Reuse `.config-panel`, `.chip`, `.muted`, `escapeHtml`, existing light/dark CSS vars.

Layout (see design mockup artifact for visuals):

1. **Four stat tiles**: Total spend (all time), Spend this month, Avg cost / video, Tokens this month (in+out). Money to 2–3 decimals (`$0.214`); tokens abbreviated (`103k`).
2. **Videos table**: one row per video, newest first — date, title, tokens in, tokens out, LLM calls, provider chips (`anthropic` paid-tinted, `ollama`/local plain), cost, and a **View details** toggle. Untracked videos render dimmed with "not tracked". Rows with `has_unpriced` get a warning chip.
3. **Detail panel** (accordion row expansion, no modal): per-session (`plan` / `render`) stage table — stage, calls, model, in-tokens, out-tokens, cost — followed by non-LLM lines (voice characters, tavily requests) and free stages listed at `$0 · local`. A per-stage cost bar (single-hue) shows where the money goes. Footer line: session totals.

Numbers use `font-variant-numeric: tabular-nums`. Cost column shows `—` for $0-local and an "unpriced" badge for null.

## 6. Edge cases & decisions

- **Retry loops are visible, not hidden**: `scriptwriter.draft × 3` renders as calls=3 with summed tokens — that's the point of the drill-down.
- **Regenerate / re-render**: extra sessions append; totals sum across sessions. Detail view shows sessions separately.
- **Cache tokens** (Anthropic): stored if present, priced 0 in v1 (pipeline sends no cache_control today).
- **Eval harness spend**: recorded to `output/evals/<slug>/usage.json` but excluded from `/api/usage` (not a video). Future "Eval spend" tile is out of scope.
- **Old runs**: no backfill possible; shown as "not tracked".
- **Failure isolation**: usage capture must never fail a run — try/except around all recording and writing.

## 7. Acceptance criteria

1. `make plan` then `python -m pipeline.run --storyboard ...` produces one `usage.json` with two sessions; every LLM call in the log has a matching record with nonzero token counts (Anthropic and Ollama rungs both).
2. `make video` (legacy path) records scout/writer/voice/reviewer records.
3. Dashboard Usage tab: totals match sum of rows; View details expands per-stage breakdown; an old run shows "not tracked"; deleting a model from pricing.yaml flips its rows to "unpriced" (not $0).
4. Killing a run mid-way leaves a valid (partial) usage.json.
5. No run fails because of usage capture (test with pricing.yaml deleted, unwritable run dir).

## Out of scope (v1)

Cost chip on Runs cards, eval-spend view, budget alerts, cache-token pricing, per-day spend chart. All are straightforward extensions once usage.json exists.
