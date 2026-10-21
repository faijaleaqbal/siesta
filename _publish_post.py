"""Publish the staged DEV post and verify what the public page renders."""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

ARTICLE_ID = 4885250
TITLE = "Siesta: the local agent that naps so you don't have to"
TAGS = ["hf26challenge", "devchallenge", "ollama", "opensource"]


def main() -> int:
    markdown = (Path(__file__).resolve().parent / "docs" / "DEV_POST.md").read_text(encoding="utf-8")

    client = MCP()
    try:
        client.initialize()
        raw = client.call(
            "update_article",
            {
                "id": ARTICLE_ID,
                "title": TITLE,
                "body_markdown": markdown,
                "tags": TAGS,
                "published": True,
                "ai_disclosure_level": "some_ai",
            },
        )
        data = unwrap(raw)
        article = data.get("Ok", data) if isinstance(data, dict) else {}
        print("=== publish result ===")
        for key in ("id", "title", "published", "ai_disclosure_level", "url", "edit_url", "tag_list", "published_at"):
            if key in article:
                print(f"  {key}: {article[key]}")
    finally:
        client.close()

    time.sleep(4)
    print("\n=== public page ===")
    url = "https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-2d2n"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            html = response.read().decode("utf-8", errors="replace")
        print(f"  HTTP 200, {len(html)} bytes")
        checks = {
            "title present": "Siesta" in html,
            "mermaid diagram": "mermaid" in html,
            "screenshot image": "siesta-ui" in html,
            "agent_session embed": "agent_session" in html,
            "github link": "github.com/faijaleaqbal/siesta" in html,
            "hf26challenge tag": "hf26challenge" in html,
            "some_ai disclosure": "AI" in html and ("disclos" in html.lower() or "generated" in html.lower()),
        }
        for label, ok in checks.items():
            print(f"  {label:<24}: {ok}")
    except Exception as exc:
        print(f"  fetch failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
