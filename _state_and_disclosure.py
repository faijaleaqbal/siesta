"""Confirm exactly one post is live, and find how DEV surfaces the AI
disclosure on the page (so we know what to look for in the editor)."""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OLD_ID = 4885250
NEW_ID = 4886839
OLD_URL = "https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-4gfd"
NEW_URL = "https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-1opd"


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def main() -> int:
    for label, article_id, url in (("original", OLD_ID, OLD_URL), ("replacement", NEW_ID, NEW_URL)):
        api_status, api_body = fetch(f"https://dev.to/api/articles/{article_id}")
        page_status, page_body = fetch(url)
        print(f"{label:<12} id={article_id}  api={api_status}  page={page_status}")
        if api_status == 200:
            data = json.loads(api_body)
            print(f"             published_at={data.get('published_at')}  level={data.get('ai_disclosure_level')}")

    print("\n=== looking for disclosure rendering in the live page ===")
    _, page = fetch(OLD_URL)
    for pattern in (
        r'ai[-_]disclosure[^"\']*',
        r'data-disclosure[^>]*',
        r'class="[^"]*disclos[^"]*"',
        r'>\s*(Not Disclosed|Some AI|Fully Autonomous)\s*<',
    ):
        found = re.findall(pattern, page, re.I)
        print(f"  {pattern[:44]:<46}: {len(found)} match(es)  {found[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
