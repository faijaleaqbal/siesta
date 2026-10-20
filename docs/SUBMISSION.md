# Submission checklist — Week 3 "Slow and Steady"

Everything needed to turn this repo into a live DEV entry.

## Where things are

| | |
|---|---|
| Challenge | [Hacktoberfest Open-Source AI Challenge: Week 3](https://dev.to/events/81) — theme *Slow and Steady* |
| Deadline | **25 October 2026, 11:59 PM PDT** |
| Required tag | `#hf26challenge` (the post also carries `#devchallenge`) |
| Repo | `github.com/faijaleaqbal/siesta` — **not created yet**, see below |
| DEV draft | [Edit the draft](https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-2d2n-temp-slug-163183/edit) (article id `4885250`) |
| Agent session | [siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy](https://dev.to/agent_sessions/siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy) (id `1073`, unpublished) |
| Post source | `docs/DEV_POST.md` — the exact text that is in the draft |
| Benchmark data | `docs/benchmark.json` |
| UI screenshot | `docs/siesta-ui.png` |

## Before you publish

1. **Create the GitHub repo and push.** The post links to
   `github.com/faijaleaqbal/siesta`, and the screenshot is referenced as
   `raw.githubusercontent.com/faijaleaqbal/siesta/main/docs/siesta-ui.png`, so
   both the link and the image need the repo to exist.

   ```bash
   cd siesta
   git remote add origin https://github.com/faijaleaqbal/siesta.git
   git push -u origin main
   ```

2. **Check the screenshot renders** in the draft. The raw GitHub URL only
   resolves once the repo is pushed.

3. **Confirm the AI disclosure badge.** The draft was updated with
   `ai_disclosure_level: some_ai`, but the API does not expose that field for
   unpublished drafts, so verify it in the editor before publishing.

4. **Read it once more in the editor.** The post is long, and the DEV editor
   renders Liquid — the `{% agent_session 1073 %}` embed only renders for the
   article's own author while the session is unpublished, so publish the
   session too if you want the transcript visible to readers.

5. **Publish the session** at
   `dev.to/agent_sessions/siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy`
   so the embed works for everyone.

6. **Publish the post.** It is staged as a draft, not published. DEV's
   submission rule for this challenge is a published post with the required
   tag, so publishing it is what submits the entry.

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
