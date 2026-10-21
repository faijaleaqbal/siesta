"""Find the tool/flag that publishes an agent session."""

import json
import subprocess
import sys
from pathlib import Path

EXE = Path.home() / ".devrelay" / "bin" / "dev_mlh_mcp_server.exe"


def main() -> int:
    result = subprocess.run(
        [str(EXE), "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        timeout=120,
    )
    # Fall back to listing the tools through a one-shot MCP handshake.
    from _mcp_client import MCP

    client = MCP()
    try:
        client.initialize()
        for tool in client.tools():
            if "session" in tool["name"]:
                print(f"=== {tool['name']} ===")
                print(json.dumps(tool.get("inputSchema", {}), indent=2)[:1200])
                print()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
