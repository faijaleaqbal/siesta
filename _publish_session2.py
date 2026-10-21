"""Publish the agent session - try slug-based routes."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

SLUG = "siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy"
SESSION_ID = 1073


def main() -> int:
    client = MCP()
    try:
        client.initialize()

        attempts = [
            ("GET", f"/api/agent_sessions/{SLUG}", None),
            ("GET", f"/dev/v1/agent_sessions/{SLUG}", None),
            ("PUT", f"/api/agent_sessions/{SLUG}", {"published": True}),
            ("PATCH", f"/api/agent_sessions/{SLUG}", {"published": True}),
            ("PUT", f"/api/agent_sessions/{SLUG}", {"agent_session": {"published": True}}),
            ("POST", f"/api/agent_sessions/{SLUG}/publish", {}),
            ("POST", f"/api/agent_sessions/{SESSION_ID}/publish", {}),
        ]
        for method, path, body in attempts:
            args = {"method": method, "path": path}
            if body is not None:
                args["body"] = body
            raw = client.call("execute_dev_api_request", args)
            result = unwrap(raw)
            summary = (
                json.dumps(result, ensure_ascii=True)[:200] if not isinstance(result, str) else result[:200]
            )
            ok = "error" not in summary.lower() or "not_found" not in summary.lower()
            print(f"{'HIT ' if ok else '    '} {method} {path}")
            print(f"      {summary.replace(chr(10), ' ')[:190]}")

        print("\n=== published flag now ===")
        state = unwrap(client.call("get_agent_session", {"id_or_slug": str(SESSION_ID)}))
        text = json.dumps(state, indent=2, ensure_ascii=True) if not isinstance(state, str) else state
        for line in text.splitlines():
            if '"published"' in line:
                print("  " + line.strip())
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
