"""Set the AI disclosure level to `some_ai` on the published post.

The MCP `update_article` accepted the field but the article still reports
`not_disclosed`, so this tries the other write paths and re-reads the public
API after each one.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mcp_client import MCP, unwrap

EXE = Path.home() / ".devrelay" / "bin" / "dev_mlh_mcp_server.exe"
ARTICLE_ID = 4885250
TITLE = "Siesta: the local agent that naps so you don't have to"
TAGS = ["hf26challenge", "devchallenge", "ollama", "opensource"]
POST = "https://dev.to/api/articles/4885250"


def read_level() -> str:
    import urllib.request

    request = urllib.request.Request(POST, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return str(data.get("ai_disclosure_level"))


def raw(method: str, path: str, body: dict) -> str:
    result = subprocess.run(
        [str(EXE), "api", method, path, "{}", json.dumps(body)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    return (result.stdout or "") + (result.stderr or "")


def main() -> int:
    markdown = (Path(__file__).resolve().parent / "docs" / "DEV_POST.md").read_text(encoding="utf-8")
    article = {
        "title": TITLE,
        "body_markdown": markdown,
        "tags": TAGS,
        "ai_disclosure_level": "some_ai",
    }

    print(f"level before: {read_level()}")

    attempts = [
        ("raw PUT, article wrapper", lambda: raw("PUT", f"/api/articles/{ARTICLE_ID}", {"article": article})),
        ("raw PUT, flat", lambda: raw("PUT", f"/api/articles/{ARTICLE_ID}", article)),
        ("raw PATCH, flat", lambda: raw("PATCH", f"/api/articles/{ARTICLE_ID}", article)),
    ]

    for label, call in attempts:
        out = call()
        failed = "error" in out.lower() and "status" in out.lower()
        print(f"\n--- {label} --- failed={failed}")
        print("  " + out[:220].replace("\n", " "))
        try:
            level = read_level()
            print(f"  level now: {level}")
            if level == "some_ai":
                print("\nSUCCESS")
                return 0
        except Exception as exc:
            print(f"  could not re-read: {exc}")

    print("\n--- MCP update_article again ---")
    client = MCP()
    try:
        client.initialize()
        client.call(
            "update_article",
            {
                "id": ARTICLE_ID,
                "title": TITLE,
                "body_markdown": markdown,
                "tags": TAGS,
                "ai_disclosure_level": "some_ai",
            },
        )
        time_wait = 2
        import time

        time.sleep(time_wait)
        level = read_level()
        print(f"  level now: {level}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
