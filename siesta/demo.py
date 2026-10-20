"""Generate a sample inbox so ``siesta demo`` works on a fresh machine.

The chat transcript is real text and will genuinely exercise the text model.
The images are synthetic placeholders drawn with a tiny pure-Python PNG
writer — no Pillow, no downloads — so the demo never depends on anything
being installed beyond Python itself.

Swap in your own photos and the same pipeline handles them.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

CHAT_TRANSCRIPT = """Ana: Are we still on for Saturday?
Ben: Yes, 6pm at the usual place. I'll bring the projector.
Ana: Perfect. Can you also send the slides to Priya before then?
Ben: Will do. I need the final numbers from accounting first though.
Ana: Take your time, just don't forget about the projector adaptor.
"""

NOTES_TODO = """shopping
- oat milk
- coffee beans
- washing up liquid

fix
- bike light (rear)
- bookshelf
"""


def write_png(path: Path, width: int, height: int, pixels: list[list[tuple[int, int, int]]]) -> Path:
    """Write a minimal truecolour PNG. Pure standard library."""
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0
        for r, g, b in row:
            raw.extend((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def _fridge_placeholder(width: int = 384, height: int = 512) -> list[list[tuple[int, int, int]]]:
    """A crude shelf-like image: cold background, a few coloured rectangles."""
    pixels: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        for x in range(width):
            colour = (222, 232, 238)  # fridge interior
            if x < 14 or x > width - 14 or y < 14 or y > height - 14:
                colour = (150, 165, 175)  # walls
            # three shelves
            for shelf_y in (150, 260, 370):
                if abs(y - shelf_y) < 6 and 14 < x < width - 14:
                    colour = (120, 132, 140)
            # a few "items" on the shelves
            for idx, (sx, sy, sw, sh, colour) in enumerate(
                [
                    (40, 70, 46, 74, (250, 250, 245)),
                    (100, 84, 38, 60, (240, 235, 210)),
                    (160, 66, 52, 78, (214, 226, 238)),
                    (230, 90, 44, 54, (236, 214, 190)),
                    (50, 186, 60, 66, (200, 226, 200)),
                    (130, 200, 52, 52, (244, 238, 210)),
                    (210, 176, 56, 74, (238, 226, 238)),
                    (60, 300, 70, 60, (222, 236, 220)),
                    (160, 296, 66, 64, (240, 232, 214)),
                    (70, 410, 56, 56, (226, 240, 244)),
                    (150, 404, 62, 62, (240, 238, 230)),
                ]
            ):
                if sx <= x < sx + sw and sy <= y < sy + sh:
                    row.append(_shade(colour, x, y, sx, sy))
                    break
            else:
                row.append(colour)
        pixels.append(row)
    return pixels


def _shade(colour, x: int, y: int, sx: int, sy: int) -> tuple[int, int, int]:
    """Add a little fake shading so the placeholder is not completely flat."""
    factor = 1.0 - 0.18 * ((x - sx) / 40.0 + (y - sy) / 60.0) / 2.0
    factor = max(0.65, min(1.15, factor))
    return (
        max(0, min(255, int(colour[0] * factor))),
        max(0, min(255, int(colour[1] * factor))),
        max(0, min(255, int(colour[2] * factor))),
    )


def _receipt_placeholder(width: int = 320, height: int = 460) -> list[list[tuple[int, int, int]]]:
    """A white slip with grey bars where the line items would be."""
    pixels: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        for x in range(width):
            colour = (250, 249, 245)
            if x < 8 or x > width - 8:
                colour = (225, 222, 214)
            # header bar
            if 30 <= y < 50 and 40 <= x < 40 + int((width - 80) * 0.55):
                colour = (70, 70, 74)
            # line items
            for i in range(7):
                ly = 80 + i * 34
                if ly <= y < ly + 10 and 40 <= x < 40 + int((width - 80) * (0.62 - i * 0.05)):
                    colour = (120, 120, 126)
            # total
            if 330 <= y < 350 and 40 <= x < 40 + int((width - 80) * 0.4):
                colour = (40, 40, 44)
            row.append(colour)
        pixels.append(row)
    return pixels


def build_demo_inbox(target: Path) -> list[Path]:
    """Create a small, realistic-looking inbox and return the files created."""
    target = Path(target)
    created: list[Path] = []

    chat_dir = target / "chats"
    chat_dir.mkdir(parents=True, exist_ok=True)
    chat = chat_dir / "weekend-chat.txt"
    chat.write_text(CHAT_TRANSCRIPT, encoding="utf-8")
    created.append(chat)

    notes_dir = target / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes = notes_dir / "todo.txt"
    notes.write_text(NOTES_TODO, encoding="utf-8")
    created.append(notes)

    fridge_dir = target / "fridge"
    fridge_dir.mkdir(parents=True, exist_ok=True)
    fridge = fridge_dir / "fridge-photo.png"
    write_png(fridge, 384, 512, _fridge_placeholder())
    created.append(fridge)

    receipt_dir = target / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / "receipt.png"
    write_png(receipt, 320, 460, _receipt_placeholder())
    created.append(receipt)

    return created


__all__ = ["build_demo_inbox", "write_png"]
