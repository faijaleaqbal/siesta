# Submission status — Week 3 "Slow and Steady"

Everything needed to turn this repo into a live DEV entry, and where each
piece currently stands.

## Where things are

| | |
|---|---|
| Challenge | [Hacktoberfest Open-Source AI Challenge: Week 3](https://dev.to/events/81) — theme *Slow and Steady* |
| Deadline | **25 October 2026, 11:59 PM PDT** |
| Required tag | `#hf26challenge` (the post also carries `#devchallenge`, `opensource`, `ollama`) |
| Repo | **live** — https://github.com/faijaleaqbal/siesta (public, MIT, 8 commits, 54 files, 61 passing tests) |
| DEV post | **live** — https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-4gfd (article id `4885250`, published 2026-10-21T04:18:16Z) |
| AI disclosure | **some_ai / AI-assisted** — set on the article |
| Agent session | **public** — https://dev.to/agent_sessions/siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy (id `1073`, 39 messages), embedded in the post |
| Post source | `docs/DEV_POST.md` — the exact text that is published |
| Screenshots | `docs/screenshots/` — regenerate with `python scripts/capture_screenshots.py` |
| Benchmark data | `docs/benchmark.json` |

## Verified on the live pages

- The mermaid diagram renders.
- The screenshot renders — DEV fetched
  `raw.githubusercontent.com/faijaleaqbal/siesta/main/docs/siesta-ui.png` and
  re-hosted it, so the image does not depend on GitHub staying up.
- The agent session embed renders, showing "39 of 39 messages" and a
  *Show more* control, with all 39 messages in the post's public HTML.
- The session's own page returns HTTP 200 to a logged-out visitor, so the
  "Open the session on DEV" link works for judges.
- The GitHub link and the `#hf26challenge` tag are present.
- The em-dashes and the sloth emoji survived the round trip — no mojibake.
- There are no broken links.

## Housekeeping

Nothing left over. The profile has exactly one agent session (the published
one) and one article (the published one). The scratch drafts and probe
sessions created while working out the publishing API were cleaned up.

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
