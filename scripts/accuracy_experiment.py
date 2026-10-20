"""How accurately can the local open-weight vision model read a fridge photo?

This is the evaluation behind the pantry chore's design. It is also the
script that caught the worst bug in the project.

Run it with a local Ollama:

    python scripts/accuracy_experiment.py

Ground truth for examples/fridge-photo.png was annotated by hand:

    top shelf    milk, eggs, cheddar cheese
    middle shelf spinach, chicken thighs, yoghurt
    bottom shelf bananas, olive oil

Two things this script is careful about:

* **The prompt contains no real item names.** An earlier version of the
  prompt listed examples like "milk, eggs, spinach" and the 3B model simply
  copied them back. The result looked like a perfect 8/8 score while the
  model had never seen the image at all.
* **It checks that the image arrived.** Ollama's ``/api/chat`` accepts a
  request-level ``images`` field and silently ignores it, so the model
  answers from the text alone and it is impossible to tell by eye. An
  attached image costs roughly a thousand prompt tokens, so the script
  asserts on the prompt token count before trusting any answer.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from siesta.backends.ollama import OllamaBackend  # noqa: E402
from siesta.config import Config  # noqa: E402
from siesta.prompts import PANTRY_SCAN_PROMPT, PANTRY_SCAN_SCHEMA  # noqa: E402
from siesta.util import parse_json_lenient  # noqa: E402

TRUTH = {
    "milk",
    "eggs",
    "cheddar cheese",
    "spinach",
    "chicken thighs",
    "yogurt",
    "bananas",
    "olive oil",
}

# The prompt must not contain any of the ground truth, or the experiment
# measures the model's ability to parrot instructions rather than to see.
def assert_prompt_is_neutral(prompt: str) -> None:
    lowered = prompt.lower()
    leaked = [name for name in TRUTH if name in lowered]
    if leaked:
        raise SystemExit(
            f"the prompt leaks ground-truth names {leaked} - the model can copy "
            "them instead of looking at the photo"
        )


# "egg carton" and "eggs" are the same thing; "chicken" and "chicken thighs"
# are the same thing; "cheese" and "cheddar cheese" are the same thing.
PACKAGING = {"carton", "box", "bag", "tub", "bottle", "pack", "jar", "can", "container", "bunch"}


def normalise(name: str) -> str:
    words = [w for w in name.lower().strip().split() if w not in PACKAGING]
    if not words:
        words = name.lower().strip().split()
    text = " ".join(words)
    if text.endswith("ies"):
        text = text[:-3] + "y"
    elif text.endswith("es") and len(text) > 4:
        text = text[:-2]
    elif text.endswith("s") and len(text) > 3:
        text = text[:-1]
    return text


def matches(name: str) -> bool:
    """Is a reported name the same thing as a ground-truth item?"""
    name = name.lower().strip()
    for truth in TRUTH:
        if name == truth:
            return True
        if name in truth or truth in name:
            return True
        a, b = normalise(name), normalise(truth)
        if a == b or a in b or b in a:
            return True
    return False


def score(names: list[str]) -> dict:
    unique = sorted({n.lower().strip() for n in names if n.strip()})
    hits = [n for n in unique if matches(n)]
    precision = len(hits) / len(unique) if unique else 0.0
    recall = len(hits) / len(TRUTH)
    return {"found": unique, "hits": hits, "precision": precision, "recall": recall}


def main() -> int:
    assert_prompt_is_neutral(PANTRY_SCAN_PROMPT)

    config = Config.load()
    backend = OllamaBackend(config)
    photo = ROOT / "examples" / "fridge-photo.png"
    if not photo.exists():
        print(f"missing {photo}")
        return 1

    image = base64.b64encode(photo.read_bytes()).decode("ascii")
    print(f"model: {config.vision_model}")
    print(f"photo: {photo} ({photo.stat().st_size // 1024} KB)")

    start = time.time()
    response = backend.chat(
        config.vision_model,
        [{"role": "user", "content": PANTRY_SCAN_PROMPT}],
        images=[image],
        json_schema=PANTRY_SCAN_SCHEMA,
        temperature=0.0,
        num_predict=400,
    )
    elapsed = time.time() - start

    print(f"\nlatency        {elapsed:.1f}s")
    print(f"prompt tokens  {response.prompt_tokens}")
    print(f"eval tokens    {response.eval_tokens}")

    if not response.saw_the_image():
        print(
            "\n!! The image did not reach the model.\n"
            "   The prompt token count is far too low for an attached image, so "
            "this\n   result would be the model answering from the instructions "
            "alone.\n   Check that images are placed inside the message object."
        )
        return 2

    parsed = parse_json_lenient(response.text) or {}
    objects = parsed.get("objects") or []
    names = [str(o.get("name", "")) for o in objects if o.get("name")]

    print("\nraw:", json.dumps(parsed, ensure_ascii=False)[:1200])

    for threshold in (0.0, 0.5, 0.55, 0.7):
        keep = [o for o in objects if float(o.get("confidence") or 0) >= threshold]
        kept_names = [str(o.get("name", "")) for o in keep if o.get("name")]
        result = score(kept_names)
        print(
            f"\nconfidence >= {threshold}: {len(result['found'])} item(s)  "
            f"precision {result['precision']:.0%}  recall {result['recall']:.0%}"
        )
        print(f"  found: {result['found']}")
        print(f"  hits:  {result['hits']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
