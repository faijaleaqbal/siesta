"""Rendering the digest.

The digest is the agent's only user-facing output, so it has to feel like the
end of a long day rather than the start of another one: short sections, no
urgency, no notification badges, no "action required".

Both a Markdown file (for the repo / terminal / Obsidian) and a small HTML
page (for the web UI) are produced from the same structured data.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from .util import now_iso, truncate


@dataclass
class DigestSection:
    title: str
    body: str
    bullets: list[str] = field(default_factory=list)


@dataclass
class Digest:
    headline: str = "Nothing needed doing."
    sections: list[DigestSection] = field(default_factory=list)
    closing: str = "Sleep well."
    files: int = 0
    chores: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    ts: str = field(default_factory=now_iso)

    # ------------------------------------------------------------------ #
    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.headline}")
        lines.append("")
        lines.append(f"*{self.ts} — {self.files} file(s) handled, {len(self.chores)} chore(s)*")
        lines.append("")
        for section in self.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            if section.body:
                lines.append(section.body)
                lines.append("")
            for bullet in section.bullets:
                lines.append(f"- {bullet}")
            if section.bullets:
                lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(self.closing)
        lines.append("")
        lines.append(
            f"<sub>{self.tokens} tokens · {self.latency_ms} ms · generated locally "
            f"by open-weight models, on this machine</sub>"
        )
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def to_html(self) -> str:
        def esc(text: str) -> str:
            return html.escape(text or "")

        parts = [
            "<article class='digest'>",
            f"<h1>{esc(self.headline)}</h1>",
            f"<p class='meta'>{esc(self.ts)} · {self.files} file(s) · {len(self.chores)} chore(s) · "
            f"{self.tokens} tokens · {self.latency_ms} ms</p>",
        ]
        for section in self.sections:
            parts.append("<section>")
            parts.append(f"<h2>{esc(section.title)}</h2>")
            if section.body:
                parts.append(f"<p>{esc(section.body)}</p>")
            if section.bullets:
                parts.append("<ul>")
                for bullet in section.bullets:
                    parts.append(f"<li>{esc(bullet)}</li>")
                parts.append("</ul>")
            parts.append("</section>")
        parts.append(f"<footer><p>{esc(self.closing)}</p></footer>")
        parts.append("</article>")
        return "\n".join(parts)


def fallback_digest(results: list[Any], files: int = 0) -> Digest:
    """Build a digest without asking the model.

    If the reasoning model is unavailable or returns nonsense, the agent still
    has something useful to say. A silent failure at 2am is worse than a
    plain summary.
    """
    sections: list[DigestSection] = []
    pantry_notes: list[str] = []
    shopping: list[str] = []
    spending: list[str] = []
    chats: list[str] = []
    chores: list[str] = []
    tokens = 0
    latency = 0

    for result in results:
        chores.append(result.kind)
        tokens += result.tokens
        latency += result.latency_ms
        data = result.data or {}
        if result.kind == "pantry":
            for item in data.get("use_first", [])[:4]:
                pantry_notes.append(
                    f"{item.get('name')} — about {item.get('expiry_days')} day(s) left"
                )
            for entry in (data.get("shopping_list") or [])[:8]:
                shopping.append(str(entry.get("name")))
            if data.get("note"):
                pantry_notes.append(str(data["note"]))
        elif result.kind == "receipt":
            spending.append(
                f"{data.get('merchant', 'Unknown')}: {data.get('total', 0):.2f} {data.get('currency', '')}".strip()
            )
        elif result.kind == "chat":
            if data.get("summary"):
                chats.append(str(data["summary"]))
        elif result.kind == "tidy":
            for move in (data.get("moves") or [])[:6]:
                shopping.append(f"{Path_name(move.get('from'))} → {Path_name(move.get('to'))}")

    if pantry_notes:
        sections.append(DigestSection(title="Kitchen", body="", bullets=pantry_notes))
    if shopping:
        sections.append(DigestSection(title="To pick up", body="", bullets=sorted(set(shopping))))
    if spending:
        sections.append(DigestSection(title="Spending", body="", bullets=spending))
    if chats:
        sections.append(DigestSection(title="What you missed", body=truncate(chats[0], 400)))

    headline = "A quiet night." if not sections else f"{len(sections)} small thing(s) while you were away."
    closing = "Nothing else needs doing tonight."
    return Digest(
        headline=headline,
        sections=sections,
        closing=closing,
        files=files,
        chores=chores,
        tokens=tokens,
        latency_ms=latency,
    )


def Path_name(value: Any) -> str:
    """Small helper so the fallback renderer stays import-free of pathlib."""
    if not value:
        return ""
    text = str(value)
    for sep in ("\\", "/"):
        if sep in text:
            return text.rsplit(sep, 1)[-1]
    return text
