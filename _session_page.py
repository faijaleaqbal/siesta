"""Inspect the agent session record and its public page for a publish path."""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

SLUG = "siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy"
SESSION_ID = 1073


def main() -> int:
    client = MCP()
    try:
        client.initialize()
        raw = client.call("execute_dev_api_request", {"method": "GET", "path": f"/api/agent_sessions/{SLUG}"})
        data = unwrap(raw)
        record = data.get("Ok", data) if isinstance(data, dict) else {}
        print("=== session record fields ===")
        for key, value in record.items():
            if key == "messages":
                print(f"  messages: <{len(value)} entries>")
            else:
                print(f"  {key}: {value}")
    finally:
        client.close()

    print("\n=== the public session page ===")
    request = urllib.request.Request(
        f"https://dev.to/agent_sessions/{SLUG}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            html = response.read().decode("utf-8", errors="replace")
        print(f"  HTTP 200, {len(html)} bytes")
        for needle in ("Publish", "publish", "sign in", "Sign in", "unpublished", "draft"):
            print(f"  contains {needle!r}: {needle in html}")
        links = sorted(set(re.findall(r'href="([^"]*agent_session[^"]*)"', html)))
        print("  session links on the page:")
        for link in links[:10]:
            print(f"    {link}")
    except Exception as exc:
        print(f"  fetch failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
