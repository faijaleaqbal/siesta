"""Verify exactly one post is live, and tidy up the stray drafts."""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

IDS = {
    "original (live target)": 4885250,
    "replacement": 4886839,
}


def public(article_id: int) -> dict | None:
    request = urllib.request.Request(
        f"https://dev.to/api/articles/{article_id}", headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def main() -> int:
    print("=== public state ===")
    for label, article_id in IDS.items():
        info = public(article_id)
        if info:
            print(f"  {label}: {article_id} LIVE  url={info.get('url')}")
            print(f"      published_at={info.get('published_at')}  level={info.get('ai_disclosure_level')}")
        else:
            print(f"  {label}: {article_id} not publicly visible")

    client = MCP()
    try:
        client.initialize()
        print("\n=== drafts on the profile ===")
        mine = unwrap(client.call("get_my_articles", {"state": "unpublished"}))
        articles = mine.get("Ok") if isinstance(mine, dict) else mine
        for article in articles or []:
            print(f"  {article.get('id')}  {article.get('title')}  tags={article.get('tag_list')}")

        print("\n=== agent sessions ===")
        sessions = unwrap(client.call("list_agent_sessions", {}))
        items = sessions.get("Ok") if isinstance(sessions, dict) else sessions
        for session in items or []:
            print(f"  {session.get('id')}  published={session.get('published')}  {session.get('title')}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
