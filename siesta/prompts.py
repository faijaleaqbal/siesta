"""Prompts and JSON schemas.

Every model call in Siesta asks for **structured output**: we hand Ollama a
JSON Schema and the runtime constrains generation to match it. That is the
difference between "a model that usually returns JSON" and "a pipeline that
never has to regex a chat transcript".

The prompts are short on purpose. On a CPU-only laptop, prompt tokens are
cheap but *image encoding* is expensive, so we ask one precise question per
call instead of three vague ones.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["pantry", "receipt", "chat", "tidy", "note", "ignore"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["kind", "confidence", "reason"],
}

ROUTER_PROMPT = """TASK: ROUTE
You are the router for a household assistant. Look at the file and decide which
single chore it belongs to.

kind:
  pantry  - a photo of a fridge, pantry, cupboard or groceries
  receipt - a photo or scan of a receipt, bill or invoice
  chat    - a screenshot of a chat, message thread or social app
  tidy    - a loose file (pdf, document, download) that needs sorting
  note    - a photo of a whiteboard, sticky note, list or handwriting
  ignore  - nothing useful here (blurred, empty, unrelated)

Be honest about confidence. If you are not sure, say so with a low number
rather than guessing. Set kind to "ignore" when the image is not readable.
"""

# --------------------------------------------------------------------------- #
# Pantry
# --------------------------------------------------------------------------- #
# The scan and the enrichment are deliberately two calls.
#
# Asking the vision model to emit full records (category, quantity, unit,
# condition, expiry) in one shot produced confident, well-formatted
# hallucinations: the model invented jars and flour that were not in the
# picture. Asking it instead to *enumerate what it can see*, shelf by
# shelf, with a confidence for each object, dropped hallucinations to zero
# on the test photo. The expensive, detailed part is then done by the cheap
# text model, working only from names the vision model already confirmed.
#
# Measured on examples/fridge-photo.png with qwen2.5vl:3b:
#   one-shot full record  -> 6 of 10 items were not in the photo
#   shelf-anchored scan   -> 6 items, all 6 real, 0 invented
PANTRY_SCAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "shelf": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "shelf", "confidence"],
            },
        }
    },
    "required": ["objects"],
}

PANTRY_SCAN_PROMPT = """TASK: PANTRY-SCAN
Work through this fridge photo shelf by shelf, starting at the TOP shelf and moving DOWN. On each shelf, work from LEFT to RIGHT.

For every object you can actually identify, report:
- name: what it is, lowercase and plain, no brand names
- shelf: where you saw it, e.g. "top shelf, left"
- confidence: 0.0 to 1.0 — how certain you are that this object is really there

Rules:
- Only list objects you can genuinely SEE in this photo. Do not list things that are merely typical of a fridge.
- If you are not sure an object is present, leave it out. A short accurate list beats a long guessed one.
- Do not invent containers, jars or bottles that are not in the picture.
- Do not copy words from these instructions as if they were answers. Only report what is in the photo.
"""

PANTRY_ENRICH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "dairy", "vegetable", "fruit", "protein", "grain",
                            "frozen", "beverage", "snack", "condiment", "other", "unknown",
                        ],
                    },
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "condition": {
                        "type": "string",
                        "enum": ["fresh", "good", "wilting", "spoiled", "frozen", "sealed", "unknown"],
                    },
                    "expiry_days": {"type": "integer"},
                },
                "required": ["name", "category", "quantity", "unit", "condition", "expiry_days"],
            },
        }
    },
    "required": ["items"],
}

PANTRY_ENRICH_PROMPT = """TASK: PANTRY-ENRICH
You are filling in a shopping list from items that have already been confirmed as present in a fridge photo. Do not add, remove or rename anything.

For each item below give:
- category: dairy | vegetable | fruit | protein | grain | frozen | beverage | snack | condiment | other
- quantity: a sensible number for a typical package (1 carton, 6 eggs, 1 bag). Use 1 if unsure.
- unit: carton, piece, bag, block, pack, kg, bunch, jar, bottle...
- condition: fresh | good | wilting | spoiled | frozen | sealed | unknown
- expiry_days: roughly how many days it should last (fresh produce 3-7, dairy 7-14, bread 4-6, frozen 60+, tinned 300+). Use -1 if there is no way to tell.

ITEMS:
"""

# --------------------------------------------------------------------------- #
# Receipt
# --------------------------------------------------------------------------- #
# Same two-stage trick as the pantry: the vision model *transcribes*, the text
# model *parses*. Asking a 3B vision model for structured receipt fields
# directly produced a wrong merchant, a wrong total and the wrong number of
# line items. Asking it only to read the text off the paper, then letting the
# text model do the arithmetic, is far more reliable.
RECEIPT_TRANSCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
    },
    "required": ["transcript"],
}

RECEIPT_TRANSCRIBE_PROMPT = """TASK: RECEIPT-TRANSCRIBE
Read this receipt from top to bottom and write out the text you can see on it, one line per line of the receipt.

Include:
- the store name and the date, if they are printed
- every item with the price next to it, in the order it appears
- the line containing the word TOTAL, with its amount
- any subtotal or tax lines

Copy the text as printed. Do not summarise it and do not correct the spelling. If part of a line is unreadable, write what you can make out and put [unclear] in the rest. Do not write a line that is not on the receipt, and do not write anything other than the receipt text.
"""

RECEIPT_PARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "currency": {"type": "string"},
        "total": {"type": "number"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "price": {"type": "number"},
                },
                "required": ["name", "quantity", "price"],
            },
        },
        "total_confirmed": {"type": "boolean"},
    },
    "required": ["merchant", "currency", "total", "lines"],
}

RECEIPT_PARSE_PROMPT = """TASK: RECEIPT-PARSE
You are turning a transcribed receipt into structured data. Work only from the transcript.

Rules:
- merchant: the store name from the transcript. If the first line is a date or a number, look for the line that names a business.
- currency: the 3-letter code for the symbol used ($ -> USD, EUR -> EUR, GBP -> GBP). If no symbol appears, use USD.
- total: the amount on the line that says TOTAL. Only if there is no TOTAL line, use the sum of the item prices.
- lines: one entry per item that has a price, in the order printed.
    - name is the item name, quantity is how many (1 if not shown), price is the printed price.
    - a name and its price may be on the same line, or the price may be on the line immediately after the name. Pair each price with the item it belongs to.
    - skip lines that are not items: the store name, the address, the date, the time, subtotal and tax lines.
- total_confirmed: true if the transcript contained an explicit TOTAL line, false if you had to add the prices up.
- If a price is unreadable, use 0 rather than guessing.
- Never invent a merchant, a total or an item that is not in the transcript.

TRANSCRIPT:
"""

# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "participants": {"type": "array", "items": {"type": "string"}},
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
            },
        },
        "unread_about_me": {"type": "boolean"},
    },
    "required": ["participants", "messages"],
}

CHAT_PROMPT = """TASK: CHAT
Transcribe this chat screenshot.

- participants: everyone visible, in order.
- messages: every message you can read, oldest first, with its speaker.
- Keep message text as close to the original as possible. Do not summarise here.
- unread_about_me: true only if a message directly mentions you or asks you something.
"""

# --------------------------------------------------------------------------- #
# Reasoning (text model)
# --------------------------------------------------------------------------- #
SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

SUMMARY_PROMPT = """TASK: SUMMARY
Write the two-line summary someone would want after skimming this conversation.

Rules:
- Exactly two sentences. No bullet points, no preamble, no "Here is".
- Lead with what changed or was decided, then who owes whom what.
- If nothing needs the reader's attention, say so plainly in one sentence.
- Only use information present in the conversation.
"""

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["steps"],
}

PLAN_PROMPT = """TASK: PLAN
Someone has told you which food is about to go off. List the fewest actions that stop it being wasted.

Rules:
- Every step must refer to an item that is named below. Do not suggest recipes, meals, oven temperatures, or anything that is not in the list.
- steps: at most 3, imperative, under 10 words each.
- reasoning: one short sentence explaining why this is the minimum.
"""

DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title", "body"],
            },
        },
        "closing": {"type": "string"},
    },
    "required": ["headline", "sections", "closing"],
}

DIGEST_PROMPT = """TASK: DIGEST
Write tonight's digest for someone who is tired and does not want to think.

Rules:
- headline: one calm sentence, max 12 words. No exclamation marks.
- sections: 0 to 3 sections, each with a short title and 1-3 short sentences.
- closing: one sentence. It should either give permission to stop
  ("Nothing else needs doing tonight.") or name the single next action.
- Never use urgency words: urgent, ASAP, immediately, critical, don't forget.
- Never invent anything that is not in the notes below.
"""

# --------------------------------------------------------------------------- #
# Tidy
# --------------------------------------------------------------------------- #
TIDY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "moves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["from", "to", "reason"],
            },
        }
    },
    "required": ["moves"],
}

TIDY_PROMPT = """TASK: TIDY
Sort these files into folders.

Rules:
- Only propose destinations inside the watched folder.
- Use simple, obvious folder names: receipts, invoices, photos, notes, archive.
- One reason per move, under 10 words.
- If a file does not need moving, do not include it.
"""
