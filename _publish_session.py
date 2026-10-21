"""Publish the saved agent session through the DEV API."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

SESSION_ID = 1073


def main() -> int:
    client = MCP()
    try:
        client.initialize()

        print("=== current state ===")
        state = unwrap(client.call("get_agent_session", {"id_or_slug": str(SESSION_ID)}))
        text = json.dumps(state, indent=2, ensure_ascii=True) if not isinstance(state, str) else state
        for line in text.splitlines():
            if any(key in line for key in ("published", "id", "slug", "url", "title")):
                print("  " + line.strip())

        attempts = [
            ("PUT", f"/api/agent_sessions/{SESSION_ID}", {"published": True}),
            ("PATCH", f"/api/agent_sessions/{SESSION_ID}", {"published": True}),
            ("POST", f"/api/agent_sessions/{SESSION_ID}/publish", {}),
            ("PUT", f"/api/agent_sessions/{SESSION_ID}", {"agent_session": {"published": True}}),
        ]
        for method, path, body in attempts:
            raw = client.call("execute_dev_api_request", {"method": method, "path": path, "body": body})
            result = unwrap(raw)
            summary = json.dumps(result, ensure_ascii=True)[:220] if not isinstance(result, str) else result[:220]
            print(f"\n--- {method} {path} {json.dumps(body)[:40]} ---")
            print("  " + summary.replace("\n", " ")[:220])

        print("\n=== state after ===")
        state = unwrap(client.call("get_agent_session", {"id_or_slug": str(SESSION_ID)}))
        text = json.dumps(state, indent=2, ensure_ascii=True) if not isinstance(state, str) else state
        published = "published" in text
        for line in text.splitlines():
            if "published" in line or "url" in line:
                print("  " + line.strip())
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
