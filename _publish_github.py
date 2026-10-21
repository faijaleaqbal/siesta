"""Create the public GitHub repo for Siesta and push the local commits.

Uses the credential already stored in Git Credential Manager. The token is
read from the helper and used in-memory only - it is never printed, logged or
written to disk.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "siesta"
OWNER = "faijaleaqbal"
DESCRIPTION = (
    "A local-first agent that naps until something changes, then does the chores "
    "you keep putting off. Open-weight models, local inference, one calm page."
)
PROJECT = Path(__file__).resolve().parent


def stored_credential() -> tuple[str, str]:
    """Ask Git Credential Manager for the github.com credential."""
    request = "protocol=https\nhost=github.com\n\n"
    result = subprocess.run(
        ["git", "credential", "fill"],
        input=request,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode != 0:
        raise SystemExit(f"git credential fill failed: {result.stderr[:300]}")
    username = password = ""
    for line in result.stdout.splitlines():
        if line.startswith("username="):
            username = line.split("=", 1)[1]
        elif line.startswith("password="):
            password = line.split("=", 1)[1]
    if not password:
        raise SystemExit("no password in the stored credential")
    return username, password


def api(method: str, path: str, token: str, body: dict | None = None):
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "siesta-publisher",
    }
    if data:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            # "Not found" is a valid answer for a lookup, not a failure.
            return 404, {"message": raw[:200]}
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {raw[:400]}") from exc


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(PROJECT), capture_output=True, text=True, encoding="utf-8", timeout=600
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def main() -> int:
    username, token = stored_credential()
    print(f"credential for: {username}")

    status, existing = api("GET", f"/repos/{OWNER}/{REPO}", token)
    print(f"repo exists? {'yes' if status == 200 else 'no'}")

    if status != 200:
        status, created = api(
            "POST",
            "/user/repos",
            token,
            {
                "name": REPO,
                "description": DESCRIPTION,
                "private": False,
                "auto_init": False,
                "has_issues": True,
                "has_wiki": False,
                "topics": ["ai", "ollama", "local-llm", "agents", "opensource", "hacktoberfest"],
            },
        )
        print(f"created repo: {created.get('full_name')}  html_url={created.get('html_url')}")
        print(f"private: {created.get('private')}")
    else:
        print(f"using existing repo: {existing.get('full_name')}")

    remote = f"https://github.com/{OWNER}/{REPO}.git"
    remotes = git("remote").split()
    if "origin" in remotes:
        git("remote", "set-url", "origin", remote)
    else:
        git("remote", "add", "origin", remote)
    print(f"remote set to {remote}")

    output = git("push", "-u", "origin", "main")
    print(output.strip()[-800:])

    status, info = api("GET", f"/repos/{OWNER}/{REPO}", token)
    print(f"\nrepo now: {info.get('full_name')}  private={info.get('private')}  stars={info.get('stargazers_count')}")
    print(f"url: {info.get('html_url')}")
    print(f"default branch: {info.get('default_branch')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
