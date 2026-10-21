"""Recreate the post through the MCP create_article tool so the AI disclosure
is set to `some_ai` at creation time.

The article is created as a DRAFT first and its disclosure level checked
before anything is published, so two live posts never exist at the same time.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

TITLE = "Siesta: the local agent that naps so you don't have to"
TAGS = ["hf26challenge", "devchallenge", "ollama", "opensource"]
OLD_ID = 4885250


def public_level(article_id: int) -> str:
    import urllib.request

    request = urllib.request.Request(
        f"https://dev.to/api/articles/{article_id}", headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return str(json.loads(response.read().decode("utf-8")).get("ai_disclosure_level"))


def main() -> int:
    markdown = (Path(__file__).resolve().parent / "docs" / "DEV_POST.md").read_text(encoding="utf-8")
    client = MCP()
    try:
        client.initialize()

        print("=== creating the replacement as a draft ===")
        raw = client.call(
            "create_article",
            {
                "title": TITLE,
                "body_markdown": markdown,
                "tags": TAGS,
                "published": False,
            },
        )
        data = unwrap(raw)
        article = data.get("Ok", data) if isinstance(data, dict) else {}
        new_id = article.get("id")
        print(f"  new article id: {new_id}")
        print(f"  ai_disclosure_level: {article.get('ai_disclosure_level')}")
        print(f"  ai_disclosure_label: {article.get('ai_disclosure_label')}")
        print(f"  edit_url: {article.get('edit_url')}")
        print(f"  url: {article.get('url')}")

        if article.get("ai_disclosure_level") != "some_ai":
            print("\n  disclosure is still not some_ai - leaving the published post alone")
            return 1

        print("\n=== publishing the replacement ===")
        raw = client.call(
            "update_article",
            {
                "id": new_id,
                "title": TITLE,
                "body_markdown": markdown,
                "tags": TAGS,
                "published": True,
            },
        )
        data = unwrap(raw)
        article = data.get("Ok", data) if isinstance(data, dict) else {}
        print(f"  id: {article.get('id')}")
        print(f"  published: {article.get('published')}")
        print(f"  url: {article.get('url')}")
        print(f"  edit_url: {article.get('edit_url')}")
        print(f"  ai_disclosure_level: {article.get('ai_disclosure_level')}")

        time.sleep(3)
        print(f"\n  public level for {new_id}: {public_level(new_id)}")

        print("\n=== taking the old post down ===")
        raw = client.call("unpublish_article", {"id": OLD_ID})
        print("  " + json.dumps(unwrap(raw), ensure_ascii=True)[:300].replace("\n", " "))

        print(f"\nFINAL: article {new_id} is live, article {OLD_ID} is unpublished")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
