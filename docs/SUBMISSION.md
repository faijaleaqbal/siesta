# Submission status — Week 3 "Slow and Steady"

Everything needed to turn this repo into a live DEV entry, and where each
piece currently stands.

## Where things are

| | |
|---|---|
| Challenge | [Hacktoberfest Open-Source AI Challenge: Week 3](https://dev.to/events/81) — theme *Slow and Steady* |
| Deadline | **25 October 2026, 11:59 PM PDT** |
| Required tag | `#hf26challenge` (the post also carries `#devchallenge`, `ollama`, `opensource`) |
| Repo | **live** — https://github.com/faijaleaqbal/siesta (public, MIT, 2 commits, main branch) |
| DEV post | **live** — https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-4gfd (article id `4885250`, published 2026-10-21T04:18:16Z) |
| Agent session | id `1073`, 39 messages, embedded in the post |
| Post source | `docs/DEV_POST.md` — the exact text that is in the published post |
| Benchmark data | `docs/benchmark.json` |
| UI screenshot | `docs/siesta-ui.png` (the post's image resolves through DEV's own image proxy) |

## What has been verified on the live post

- The mermaid diagram renders.
- The screenshot renders — DEV fetched `raw.githubusercontent.com/faijaleaqbal/siesta/main/docs/siesta-ui.png`
  and re-hosted it, so the image does not depend on GitHub staying up.
- The agent session embed renders, showing "39 of 39 messages" and a *Show more*
  control, with all 39 messages in the post's public HTML.
- The GitHub link and the `#hf26challenge` tag are present.
- The em-dashes and the sloth emoji survived the round trip — no mojibake.
- There are no broken links: a standalone "Open the session on DEV" link was
  removed because the session is a private draft and its page 404s for
  non-authors. The transcript is embedded in full instead.

## One small thing left, in the DEV web UI

The DevRelay gateway exposes no write route for the agent session, so
publishing it needs the editor.

1. **The AI disclosure badge reads "Not Disclosed".**
   `ai_disclosure_level` is only settable at creation time — the API accepts
   the field on an update and then silently keeps the old value, and a
   replacement article created through the MCP tool comes back with an API
   record that cannot be read. Open the post's editor and set the AI
   disclosure to **Some AI**, which is the honest level for a post an agent
   drafted.

2. **The agent session is still an unpublished private draft.**
   The embed inside the post already renders for readers, so the submission
   requirement is met either way. But if you publish the session at
   https://dev.to/agent_sessions/siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy
   you can add a link to it back in the "Show your work" section. There is no
   API route for it — `PUT`/`PATCH`/`POST .../publish` on
   `/api/agent_sessions/<slug>` all 404.

## Housekeeping

Two stray unpublished drafts are on the profile and can be deleted in the DEV
UI: the two throwaway sessions named `probe` and `probe2`, and one duplicate
draft of this post (id `4886839`, created while testing the disclosure
field — it is unpublished, and the live post is id `4885250`).

## If a judge wants to run it

```bash
git clone https://github.com/faijaleaqbal/siesta.git
cd siesta
bash setup.sh              # or: powershell -ExecutionPolicy Bypass -File setup.ps1
python -m siesta demo      # no models needed - uses the deterministic stub
python -m siesta serve     # http://127.0.0.1:8765
```

`setup.sh` installs a portable Ollama runtime (no admin rights, no system
service) and pulls the three open-weight models. `siesta demo` and the test
suite work with no models at all.

## Numbers quoted in the post

All of them come from a real run on a CPU-only laptop (AMD integrated
graphics, 12 cores, 15 GB RAM) and are reproducible with
`python scripts/demo_real.py` and `python scripts/accuracy_experiment.py`.

| Claim | Value |
|---|---|
| Two nights, naive pipeline | 12 model calls, 8,611 tokens, 6 pages |
| Two nights, the cascade | 5 model calls, 5,182 tokens, 1 page |
| Second night, the cascade | 0 model calls, 0 tokens |
| Tokens saved | 3,429 (39.8%) |
| Files routed without a model | 3 / 3 |
| Fridge photo precision / recall | 100% / 100% (8 of 8) |
| Prompt tokens with the image | 1,587 (198 when the image was not arriving) |
| Receipt total read | $32.24, matching the printed total |
| Tests | 61 passing, no model download required |
