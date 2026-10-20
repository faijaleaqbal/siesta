"""Small helpers shared across Siesta.

Deliberately dependency-free: everything here is standard library only, so the
agent can run on a bare Python install.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("siesta")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".tif", ".tiff"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log", ".yaml", ".yml",
    ".eml", ".html", ".htm", ".xml", ".srt", ".vtt",
}
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".doc", ".xlsx", ".pptx"}


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """UTC timestamp, second precision, ISO-8601 with a trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp() -> str:
    """Filesystem-safe timestamp used for digest filenames."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def file_fingerprint(path: Path) -> str:
    """Cheap fingerprint: size + mtime. Used to avoid hashing big files twice."""
    st = path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, content: str) -> Path:
    """Write a file without ever leaving a half-written artifact behind.

    Matters here: the digest is the agent's only output, and a crash midway
    through writing it should not destroy the previous night's digest.
    """
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".siesta-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def slugify(text: str, fallback: str = "item") -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


# Words that describe the packaging rather than the thing itself.
PACKAGING_WORDS = {
    "carton", "box", "bag", "tub", "bottle", "pack", "jar", "can",
    "container", "bunch", "packet", "tin", "tube", "block", "loaf", "piece",
}

# Words that mean the same thing.
SYNONYMS = {
    "yoghurt": "yogurt",
    "cereal": "breakfast",
    "veg": "vegetable",
    "aubergine": "eggplant",
}


def canonical_name(name: str) -> str:
    """Reduce a detected item to a comparable name.

    The vision model says "milk carton" and "egg carton"; the shopping list
    knows "milk" and "eggs". Without this, a fridge full of milk makes the
    agent tell you to buy milk.
    """
    name = (name or "").strip().lower()
    if not name:
        return ""
    words = [w for w in name.split() if w not in PACKAGING_WORDS and w not in ("of", "the")]
    if not words:
        words = name.split()
    text = " ".join(words)
    if text.endswith("ies") and len(text) > 4:
        text = text[:-3] + "y"
    elif text.endswith("es") and len(text) > 4:
        text = text[:-2]
    elif text.endswith("s") and len(text) > 3:
        text = text[:-1]
    return SYNONYMS.get(text, text)


def same_item(a: str, b: str) -> bool:
    """Are two item names the same thing, once packaging and plurals are gone?"""
    ca, cb = canonical_name(a), canonical_name(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    return ca in cb or cb in ca


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def is_text_like(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def supported(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES | TEXT_SUFFIXES | DOCUMENT_SUFFIXES


def read_text_safe(path: Path, limit: int = 200_000) -> str:
    """Read a text file, tolerating weird encodings and huge files."""
    try:
        raw = path.read_bytes()[:limit]
    except OSError:
        return ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that small models love to add."""
    text = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def parse_json_lenient(text: str) -> Any:
    """Parse JSON that may be fenced, prefixed with prose, or trailing commas.

    Small open-weight models are enthusiastic but sloppy. Rather than fail a
    run because of one stray comma, we recover what we can and let the
    caller decide whether the result is good enough.
    """
    if text is None:
        return None
    candidate = strip_code_fences(text)
    attempts = [candidate]

    # First {...} / [...] block in the string.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            attempts.append(candidate[start : end + 1])

    # Strip prose before the first brace.
    brace = candidate.find("{")
    if brace > 0:
        attempts.append(candidate[brace:])
        attempts.append(candidate[brace:].rstrip().rstrip(",") + "}")

    for attempt in attempts:
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            pass
        repaired = attempt.replace(",}", "}").replace(",]", "]").replace("'", '"')
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Math (kept pure-Python so we do not need numpy)
# --------------------------------------------------------------------------- #
def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    av = list(a)
    bv = list(b)
    if not av or not bv or len(av) != len(bv):
        return 0.0
    dot = sum(x * y for x, y in zip(av, bv))
    na = sum(x * x for x in av) ** 0.5
    nb = sum(y * y for y in bv) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def truncate(text: str, limit: int, suffix: str = "...") -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
