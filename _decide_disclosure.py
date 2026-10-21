"""Read the disclosure level of the replacement draft and decide the outcome."""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

NEW_ID = 4886839
OLD_ID = 4885250


def read(article_id: int) -> dict:
    request = urllib.request.Request(
        f"https://dev.to/api/articles/{article_id}", headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    new = read(NEW_ID)
    old = read(OLD_ID)
    print(f"new draft {NEW_ID}: level={new.get('ai_disclosure_level')} label={new.get('ai_disclosure_label')}")
    print(f"live post {OLD_ID}: level={old.get('ai_disclosure_level')} label={old.get('ai_disclosure_label')}")

    if new.get("ai_disclosure_level") == "some_ai":
        print("\nnew draft carries the right disclosure -> publish it and retire the old one")
        client = MCP()
        try:
            client.initialize()
            raw = client.call(
                "update_article",
                {
                    "id": NEW_ID,
                    "title": "Siesta: the local agent that naps so you don't have to",
                    "body_markdown": (Path(__file__).resolve().parent / "docs" / "DEV_POST.md").read_text(encoding="utf-8"),
                    "tags": ["hf26challenge", "devchallenge", "ollama", "opensource"],
                    "published": True,
                },
            )
            article = unwrap(raw)
            article = article.get("Ok", article) if isinstance(article, dict) else {}
            print(f"  published {NEW_ID}: {article.get('url')}")
            raw = client.call("unpublish_article", {"id": OLD_ID})
            print("  unpublished old:", json.dumps(unwrap(raw), ensure_ascii=True)[:200])
        finally:
            client.close()
        return 0

    print("\nThe MCP create path does not set the disclosure either.")
    print("It has to be chosen in the DEV editor. The live post is untouched.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
