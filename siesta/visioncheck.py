"""A self-check that the vision model is really seeing the pictures.

This exists because of a bug that was genuinely hard to see. Ollama's
``/api/chat`` accepts a request-level ``images`` field and silently ignores
it. The model then answers from the text of the prompt alone - and because
the prompt happened to mention plausible fridge items, the output looked
exactly like a correct reading. Nothing errored. Nothing warned. The scores
were fake.

So: send a picture whose contents are unambiguous - a red rectangle over a
green one - and ask what colours are in it. If the model says "red and
green", images are being delivered. If it says anything else, they are not.

The test image is drawn with a tiny pure-Python PNG writer, so this check
needs no image library at all.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

RED = (220, 30, 30)
GREEN = (30, 160, 60)

PROMPT = "What colours do you see in this image? Answer with the colour names only."


def _png_bytes(width: int, height: int) -> bytes:
    """A red top half over a green bottom half, as PNG bytes."""
    import struct
    import zlib

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        colour = RED if y < height // 2 else GREEN
        for _ in range(width):
            raw.extend(colour)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def run_vision_check(backend: Any, model: str, timeout: int = 180) -> dict[str, Any]:
    """Ask the model to describe a picture with known contents.

    Returns a dict with ``ok`` and the reason, so a caller can report it
    without having to parse the answer.
    """
    image = base64.b64encode(_png_bytes(128, 80)).decode("ascii")
    try:
        response = backend.chat(
            model,
            [{"role": "user", "content": PROMPT}],
            images=[image],
            temperature=0.0,
            num_predict=40,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"the model call failed: {exc}", "answer": ""}

    answer = (response.text or "").lower()
    saw_red = "red" in answer
    saw_green = "green" in answer
    tokens = response.prompt_tokens

    if not response.saw_the_image():
        return {
            "ok": False,
            "reason": (
                f"the model only received {tokens} prompt tokens - an attached "
                "image costs about a thousand, so the picture never arrived"
            ),
            "answer": response.text,
        }
    if saw_red and saw_green:
        return {"ok": True, "reason": "the model sees images", "answer": response.text}
    return {
        "ok": False,
        "reason": f"the model could not identify a red/green test image (said: {response.text!r})",
        "answer": response.text,
    }


__all__ = ["run_vision_check", "PROMPT"]
