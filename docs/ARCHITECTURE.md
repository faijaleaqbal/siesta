# Architecture

Siesta is a single-process, local-first agent. There is no server component,
no queue, no cloud, and no third-party runtime dependency in the core.

```
        ┌───────────────────────────────────────────────────────────┐
        │  ~/Siesta-Inbox                                          │
        │    fridge/  receipts/  chats/  notes/  invoice-jan.pdf    │
        └──────────────────────┬────────────────────────────────────┘
                               │  watch (mtime + size fingerprint)
                               ▼
        ┌───────────────────────────────────────────────────────────┐
        │  agent.Siesta.run_once()                                 │
        │                                                           │
        │   1. discover()      hash check ─────────► still asleep?  │
        │   2. router.route()  metadata ─► cheap VLM ─► escalate   │
        │   3. chore.run()     vision model + embedding model      │
        │   4. compose()       reasoning model, one digest         │
        │   5. write()         ~/.siesta/digests/<ts>.md           │
        └──────────────────────┬────────────────────────────────────┘
                               │  HTTP to 127.0.0.1:11434 only
                               ▼
        ┌───────────────────────────────────────────────────────────┐
        │  Ollama (MIT) — open-weight models on your own machine   │
        │    qwen2.5vl:3b        vision   (Apache-2.0)              │
        │    qwen2.5:3b-instruct reasoning (Apache-2.0)             │
        │    nomic-embed-text    embeddings (Apache-2.0)            │
        └───────────────────────────────────────────────────────────┘
```

## The four stages, and why each one exists

### Stage 0 — the hash check (`agent.discover`)

A file is *new* only when its **bytes** changed.

The cheap check is `(size, mtime)`. If that matches what we recorded last
time, the file is skipped without even being hashed. If it differs, we hash
it — and if the hash matches what we recorded, the file was merely touched
or re-saved, and we update the fingerprint and stay asleep.

This is what makes `siesta watch` safe to run on a machine you also use:
reorganising your Downloads folder does not wake the agent.

### Stage 1 — the metadata gate (`router._metadata_route`)

Each chore exposes a `detect(path, config)` that returns a confidence from
filename and folder name alone. `receipts/receipt.png` scores 0.95 for the
receipt chore. This stage costs **zero tokens** and **zero milliseconds**.

If the best score clears `gate_threshold` (0.62), the file is routed and the
model ladder is skipped entirely.

### Stage 2 — the cheap vision gate (`router._gate_model_route`)

Optional, and off unless you configure `--gate-model`. A small vision model
(`smolvlm:256m`, ~250 MB) looks at the image and picks a chore. Useful when
your filenames are useless, e.g. `IMG_4821.jpg`.

### Stage 3 — escalation (`router._reason_model_route`)

Only if stages 1 and 2 were not confident does the reasoning model look at
the file and decide. This is the most expensive path and it is rare.

The router records which stage decided, and `report.routed_by_metadata` is
reported on every run. That number is the argument of the project.

### Stage 4 — one digest (`agent._compose`)

The reasoning model writes one page for the entire batch, not one per file.
Before it is written, `agent._is_duplicate` embeds the draft and compares it
with the last digest; above a cosine similarity of `0.965` the draft is
discarded as "already said".

## Data model

One SQLite file at `~/.siesta/data/siesta.sqlite3`.

| Table | Holds |
|---|---|
| `items` | the pantry: canonical name, quantity, category, expiry, embedding |
| `seen_files` | path → (fingerprint, sha256) — the nap bookkeeping |
| `events` | the cost ledger: one row per model call, with latency and tokens |
| `digests` | every digest Siesta has written |
| `expenses` | the local receipt ledger |
| `chores_state` | free-form key/value (shopping list, last digest embedding) |

The `events` table is what makes the write-up honest: every number quoted in
the README comes from a real row in it, produced by a real model call on a
CPU-only laptop.

## Structured output

Every model call passes a JSON Schema to Ollama's `format` field. Ollama
constrains generation to that schema, so a 3B model returns parseable
structure without the pipeline needing to regex prose.

`siesta/util.parse_json_lenient` is the safety net for the cases where even
that is not enough: fenced code blocks, a stray comma, prose wrapped around
the JSON. It recovers what it can rather than failing the run — a silent
failure at 2am is worse than a slightly malformed receipt.

## Cost model

| Call | Model | When |
|---|---|---|
| route | text model | only when the metadata and cheap gates are unsure |
| extract | vision model | once per image, structured extraction |
| embed | embedding model | once per batch of item names, once per digest |
| plan | text model | only when food is about to go off |
| summary | text model | once per chat |
| digest | text model | once per batch |

A typical fridge-only run is **one** vision call plus **one** digest call.
A chat-only run is **one** summary call plus **one** digest call.

## Swapping models

Nothing in `siesta/` imports a model name. The models are configuration:

```bash
python -m siesta scan --text-model llama3.2 --vision-model llava --embed-model bge-m3
```

The only requirement is that the model speaks the same protocol: vision
models take base64 images, text models take messages, and both honour a
JSON Schema through Ollama's `format` field.

## Extension: a new chore

1. Subclass `BaseChore` in `siesta/chores/`.
2. Implement `detect(path, config) -> (confidence, reason)` — metadata only,
   no model calls. This is your gate signal.
3. Implement `run(path, ctx) -> ChoreResult`. Use `call_structured` so the
   model is constrained to your schema and the call is logged to the ledger.
4. Register it in `siesta/chores/__init__.py`.

The agent will pick it up: routing, escalation, digesting and duplicate
suppression all work off the registry.
