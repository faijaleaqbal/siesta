"""Publish the replacement post, check its disclosure badge, and retire the
redundant one so exactly one post is ever live.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

NEW_ID = 4886839
OLD_ID = 4885250
TITLE = "Siesta: the local agent that naps so you don't have to"
TAGS = ["hf26challenge", "devchallenge", "ollama", "opensource"]


def public(article_id: int) -> dict:
    request = urllib.request.Request(
        f"https://dev.to/api/articles/{article_id}", headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    markdown = (Path(__file__).resolve().parent / "docs" / "DEV_POST.md").read_text(encoding="utf-8")
    client = MCP()
    try:
        client.initialize()

        print("=== publish the replacement ===")
        raw = client.call(
            "update_article",
            {
                "id": NEW_ID,
                "title": TITLE,
                "body_markdown": markdown,
                "tags": TAGS,
                "published": True,
            },
        )
        article = unwrap(raw)
        article = article.get("Ok", article) if isinstance(article, dict) else {}
        print(f"  id: {article.get('id')}  url: {article.get('url')}")

        # The public API is served through a CDN, so give it time to catch up.
        level, url = None, None
        for attempt in range(12):
            time.sleep(5)
            try:
                info = public(NEW_ID)
                level = info.get("ai_disclosure_level")
                url = info.get("url")
                print(f"  attempt {attempt + 1}: public disclosure level = {level}")
                if level:
                    break
            except Exception as exc:
                print(f"  attempt {attempt + 1}: not readable yet ({exc.__class__.__name__})")
        if not level:
            print("  gave up waiting for the CDN")

        if level == "some_ai":
            print("\n=== retiring the old post ===")
            raw = client.call("unpublish_article", {"id": OLD_ID})
            print("  " + json.dumps(unwrap(raw), ensure_ascii=True)[:220].replace("\n", " "))
            time.sleep(3)
            try:
                public(OLD_ID)
                print("  old post still publicly visible")
            except Exception:
                print("  old post is no longer publicly visible")
            print(f"\nFINAL URL: {url}")
            return 0

        print("\n=== the replacement has no better badge - reverting ===")
        raw = client.call("unpublish_article", {"id": NEW_ID})
        print("  " + json.dumps(unwrap(raw), ensure_ascii=True)[:220].replace("\n", " "))
        time.sleep(3)
        info = public(OLD_ID)
        print(f"\n  the original post stays live: {info.get('url')}")
        print(f"  its disclosure level: {info.get('ai_disclosure_level')}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
