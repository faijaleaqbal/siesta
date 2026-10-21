"""Determine the replacement draft's disclosure level via every read path."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

NEW_ID = 4886839
NEW_SLUG = "siesta-the-local-agent-that-naps-so-you-dont-have-to-4dn5-temp-slug-4404637"
OLD_ID = 4885250
OLD_SLUG = "siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy"


def main() -> int:
    client = MCP()
    try:
        client.initialize()
        names = [t["name"] for t in client.tools()]
        print("article-related tools:")
        for name in names:
            if "article" in name or "unpublish" in name:
                print(f"  {name}")

        print("\n=== read attempts for the replacement draft ===")
        for label, path in (
            ("by id", f"/api/articles/{NEW_ID}"),
            ("by slug", f"/api/articles/{NEW_SLUG}"),
        ):
            raw = client.call("execute_dev_api_request", {"method": "GET", "path": path})
            data = unwrap(raw)
            text = json.dumps(data, ensure_ascii=True) if not isinstance(data, str) else data
            level = "not found"
            for candidate in (data if isinstance(data, dict) else {}).values():
                if isinstance(candidate, dict) and "ai_disclosure_level" in candidate:
                    level = candidate["ai_disclosure_level"]
            if isinstance(data, dict) and "ai_disclosure_level" in data:
                level = data["ai_disclosure_level"]
            print(f"  {label:<8} -> level={level}  ({text[:130]})")

        print("\n=== what the live post says ===")
        for label, slug in (("old", OLD_SLUG),):
            raw = client.call("execute_dev_api_request", {"method": "GET", "path": f"/api/articles/{OLD_ID}"})
            text = json.dumps(unwrap(raw), ensure_ascii=True)
            print(f"  {label}: {text[:200]}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
