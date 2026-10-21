"""Minimal MCP stdio client for the DevRelay gateway."""

import json
import subprocess
import threading
from pathlib import Path

EXE = Path.home() / ".devrelay" / "bin" / "dev_mlh_mcp_server.exe"


class MCP:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [str(EXE), "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._id = 0
        self._lock = threading.Lock()

    def _send(self, method: str, params: dict) -> dict:
        with self._lock:
            self._id += 1
            message = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("the MCP server closed the connection")
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("id") == self._id:
                    return payload

    def notify(self, method: str, params: dict) -> None:
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        with self._lock:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()

    def initialize(self) -> dict:
        result = self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "siesta-publisher", "version": "1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def tools(self) -> list[dict]:
        return self._send("tools/list", {}).get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict) -> dict:
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


def unwrap(result: dict) -> object:
    content = result.get("result", {}).get("content", [])
    for block in content:
        if block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return result
