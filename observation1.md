# Content Automation Research Notes
> Compiled for feeding into Claude Code. Goal: extract repeatable editing techniques,
> verification checklists, and AI-agent-automatable skills for a solo short-form video pipeline.
> Note: YouTube transcript data was auto-generated (ASR) — a few tool names were mis-transcribed
> and have been corrected (11 Labs = ElevenLabs, "Hunen" = HeyGen).

---

## VIDEO 1 — Reference Short (editing-style teardown)

- **Title:** "China Just Released a FREE Claude Alternative!"
- **Creator:** @vaibhavsisinty
- **Link:** https://www.youtube.com/shorts/Sd12VHQac94
- **Format:** Vertical Short, 36 seconds, fast-paced AI-news roundup
- **Why it matters:** This is the *target editing style* to reproduce.

### Timeline map (verified frame-by-frame)
| Time | What's on screen |
|------|------------------|
| 0.0s | Static surreal AI image (two people composited as monks in a temple). NO text yet — the image alone is the scroll-stopper. |
| 0.5–2.0s | Kinetic headline builds word-by-word every ~0.5s: "CHINA" → "just dropped" → "CLAUDE'S" → "FREE / alternative". |
| ~4.0s | Full-frame color/gradient FLASH transition (whip-cut card) bridging hook → main content. |
| 5–30s | Talking-head monologue. Screen-recording B-roll hard-cropped to top ~55–80% of frame; face-cam at bottom. Captions change every 0.5–1s. |
| 23s | Jump-cut between two filming locations (brick-wall set ↔ home-studio set) mid-sentence, purely for visual texture. |
| 30–33s | Full-frame talking head + big kinetic CTA text ("the full BREAKDOWN", "comment FREE", "I'll SHARE") — same style as the hook (bookend). |
| 34–36s | Static branded end-card (WhatsApp community promo) with subtle particle animation. |

### Technique breakdown
- **Hook:** absurd/high-contrast image with zero text on frame 0, then a headline assembled 1 word at a time. Two hooks stacked (visual confusion + text payoff).
- **Pacing:** two rhythms — captions every 0.5–1s (speech-driven), B-roll swaps every 2–4s, location cuts every 5–10s. One flash transition. No punch-in zooms.
- **Layering:** max 3 simultaneous layers — (1) face-cam base, (2) screen-recording B-roll (hard-edge full-bleed crop, NO rounded corners/border), (3) dark rounded caption chip with white monospace text. Hook/CTA drop to 2 layers (image + big bold sans-serif with translucent "ghost" duplicate of the word).
- **B-roll:** always REAL product footage (tweet screenshots, AI-chat UI recording, code editor, finished game demo) — used as proof, not filler. Doubles as pacing device.
- **Style label:** "premium social / creator-tech." Polish comes from *consistency + restraint*, not complexity.

### Usable skills / rules to codify
```
RULE_HOOK: first frame = strong image, no text; headline builds 1 word/~0.5s; 4–6 words total.
RULE_LAYERS: never exceed 3 visual layers at once.
RULE_COMPOSITION: face-cam bottom, B-roll top ~60–80%, hard-edge stacked crop.
RULE_CAPTIONS: 2–4 word chunks, synced to speech, consistent dark chip style throughout.
RULE_BROLL: use real product/demo footage as proof; never generic stock filler.
RULE_TRANSITIONS: mask hard cuts with a 1–3 frame color flash + whoosh SFX.
RULE_BOOKEND: CTA uses identical kinetic-text treatment as the hook.
RULE_ENDCARD: one reusable branded end-card, identical every video.
```

---

## VIDEO 2 — "VM Onboarding" (App 02) — the SOP/checklist blueprint

- **Title:** "5 Apps I Built With AI to Run My 500-Person Company"
- **Creator:** Varun Mayya (1.14M subs)
- **Link (jumps to App 02):** https://www.youtube.com/watch?v=M1E4ZzdpOco&t=433s
- **Segment analyzed:** 7:00–14:03 (chapter "App 02")
- **Tool shown:** "VM Onboarding" — a vibe-coded app (built on Lovable) that turns their written editing SOP into an interactive, self-verifying training course.

### Core insight
Nothing in their editing is improvised. Every style on the channel is **codified as a repeatable procedure** so they can publish a reel **within 10–20 minutes** of a big announcement (Apple/Google). They fed an existing SOP *document* into Lovable → it became interactive modules with MCQs + skill-checks.

### The verification mechanism (the key idea to steal)
- **Gated modules:** cannot advance to the next module until you finish the current one AND pass its skill-check (MCQ).
- **End-of-day proof:** the new editor must produce a real video and **self-check it against the checklist** before it counts.
- **Gap-only feedback:** the tool identifies exactly where you fell short and gives feedback ONLY on that gap (doesn't re-teach everything). Saves ~8 hours → ~30 min.
- Meta-lesson: *any process you've written down once can become an interactive, self-checking tool.*

### The production checklist he codified (extracted from the segment)
- Hook + intro structure defined in advance.
- Talking-head reference + "collage hook" composition = **presenter in bottom, collage of supporting visuals on top** (identical to Video 1's layout).
- Guides & rulers for alignment; slides-based layout reference.
- All editing-style variants named + documented (not improvised).
- Audio: **cut blank/silent spaces out of the ElevenLabs voiceover.**
- Export the caption/paste file.
- Generate the **HeyGen** avatar (where used).
- Pacing rules specified explicitly.

### Usable skills / how to replicate solo (no team)
```
BLUEPRINT: replace the human trainee + human reviewer with agents.
STEP_1: write your full editing checklist as ONE structured doc (each item = a yes/no gradeable question).
STEP_2: build a "Reviewer Agent" (Claude Fable 5 vision): input = exported key-frames + caption file + export metadata;
        output = pass/fail per checklist item + GAP-ONLY feedback note. (digital version of his end-of-day skill-check)
STEP_3: gate publishing on Reviewer Agent = all-pass; else route back with gap list.
STEP_4 (later): "Coach Agent" (cheap, local Ollama) tracks repeated failures and warns you BEFORE editing.
```

---

## REFERENCE DOC — Claude Fable 5 (the "brain" model for the pipeline)

- **Type:** Official Anthropic docs page (not a video — user-provided link).
- **Link:** https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
- **Released:** June 9, 2026.

### Facts relevant to a content pipeline
- Most capable widely-released model; built for demanding reasoning + long-horizon agentic work.
- **1M-token context window**, up to **128k output tokens** per request.
- **Vision** (can grade exported video frames), **code execution**, **programmatic tool calling**, **memory tool**.
- Adaptive thinking always on; control depth via `effort` parameter. Raw chain-of-thought never returned.
- **Pricing:** $10 / M input tokens, $50 / M output tokens (premium — use selectively).
- **Refusals/fallback (important for automation):** Fable can decline a request and returns `stop_reason: "refusal"` as a normal HTTP 200 (not an error). Build a fallback branch to another model. Not billed for a pre-output refusal; fallback credit refunds the prompt-cache switch cost.
- Mythos 5 = same capabilities without safety classifiers (limited release via Project Glasswing) — likely N/A to this user.

### Role in pipeline
```
Fable 5   = the BRAIN: script, hook variants, caption SRT chunking, shot list, vision-based QA/Reviewer Agent.
Ollama    = cheap local BULK: idea generation, draft chunking, transcription cleanup, Coach Agent.
n8n       = GLUE: triggers, data routing, publish + logging, refusal/fallback handling.
CapCut    = FINISHER: manual assembly on a locked template (not meaningfully API-automatable).
HUMAN     = topic choice, hook pick, recording face-cam + real B-roll.
```

---

## CONSOLIDATED PRE-POST CHECKLIST (the deliverable to grade against)

### Gate A — before creating
1. Topic/angle chosen.
2. Hook written as 4–6 words (builds word-by-word).
3. Script approved.
4. Shot list + which REAL B-roll to screen-record identified.

### Gate B — after editing / before posting
1. First frame stops the scroll on its own (no text needed).
2. Hook headline fully readable within first 2 seconds.
3. Captions chunked to 2–4 words and synced.
4. Composition follows face-bottom / B-roll-top rule AND ≤3 layers.
5. Silences trimmed from the voiceover (ElevenLabs blank-space cut).
6. B-roll is real proof footage, not filler.
7. CTA uses the same kinetic-text style as the hook.
8. Branded end-card present.
9. Export correct: 9:16, correct resolution, correct filename.

### Delegation map
| Item | Owner |
|------|-------|
| Topic/angle, hook pick, recording face-cam, capturing real B-roll | **Human-only** |
| Script draft, hook variants, caption SRT, silence-trim, shot list | **Agent-monitored (human approves)** |
| QA grading vs checklist (gap-only), format/filename/end-card/caption-length checks, logging | **Agent-automatable (Fable 5 vision)** |

---

## NEXT ACTIONS FOR CLAUDE CODE
1. Turn `Gate A` + `Gate B` into a machine-readable JSON schema (each item: id, question, pass_criteria, owner).
2. Draft the Reviewer Agent prompt for Claude Fable 5 (inputs: key-frames + caption file + metadata → per-item pass/fail + gap notes).
3. Scaffold the n8n flow: idea → Fable script/hook → [human approve] → record → caption SRT → CapCut → Reviewer Agent → [publish or return gaps]. Include the `stop_reason: "refusal"` fallback branch.