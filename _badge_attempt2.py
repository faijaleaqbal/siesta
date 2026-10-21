"""Second attempt at the `some_ai` badge: publish the replacement, read it
through its own public URL (not the API), and swap only if the badge is
right. Any failure rolls back to the original.
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


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


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
        new_url = article.get("url")
        print(f"  url: {new_url}")

        print("\n=== waiting for it to be publicly readable ===")
        level = None
        for attempt in range(10):
            time.sleep(6)
            status, body = fetch(f"https://dev.to/api/articles/{NEW_ID}")
            if status == 200:
                level = json.loads(body).get("ai_disclosure_level")
                print(f"  attempt {attempt + 1}: HTTP {status}, disclosure = {level}")
                break
            page_status, _ = fetch(new_url)
            print(f"  attempt {attempt + 1}: api {status}, page {page_status}")

        if level == "some_ai":
            print("\n=== the replacement has the right badge - retiring the original ===")
            client.call("unpublish_article", {"id": OLD_ID})
            time.sleep(3)
            status, _ = fetch(f"https://dev.to/api/articles/{OLD_ID}")
            print(f"  original now: HTTP {status} (404 means it is gone)")
            status, _ = fetch(f"https://dev.to/api/articles/{NEW_ID}")
            print(f"  replacement now: HTTP {status}")
            print(f"\nFINAL URL: {new_url}")
            return 0

        print("\n=== still no better badge - rolling back ===")
        client.call("unpublish_article", {"id": NEW_ID})
        time.sleep(2)
        status, _ = fetch(f"https://dev.to/api/articles/{OLD_ID}")
        print(f"  original still live: HTTP {status}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
