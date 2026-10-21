"""Capture screenshots of the live sites into docs/screenshots/.

The repository's README and the DEV post both show the project as it is
actually running. This script takes those pictures from the live sites, so
they can be regenerated whenever something changes:

    python scripts/capture_screenshots.py

It uses headless Edge (or Brave, whichever is installed) and needs nothing
from PyPI. DEV shows a "Kindness is contagious" banner to logged-out
visitors, so the bottom band of the post capture is trimmed afterwards.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"

POST_URL = "https://dev.to/faijaleaqbal/siesta-the-local-agent-that-naps-so-you-dont-have-to-4gfd"
SESSION_URL = (
    "https://dev.to/agent_sessions/"
    "siesta-building-a-local-first-agent-that-naps-until-something-changes-gnwcdy"
)
REPO_URL = "https://github.com/faijaleaqbal/siesta"

BROWSERS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    Path(r"/usr/bin/microsoft-edge"),
    Path(r"/usr/bin/google-chrome"),
    Path(r"/usr/bin/chromium"),
]

FLAGS = [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--hide-scrollbars",
    "--run-all-compositor-stages-before-draw",
]

SHOTS = [
    ("dev-post.png", POST_URL, 1280, 2100, 1650),
    ("agent-session.png", SESSION_URL, 1280, 950, None),
    ("github-repo.png", REPO_URL, 1280, 1100, None),
]


def find_browser() -> Path | None:
    for candidate in BROWSERS:
        if candidate.exists():
            return candidate
    for name in ("msedge", "brave", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def shoot(browser: Path, name: str, url: str, width: int, height: int, profile: Path) -> bool:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    if target.exists():
        target.unlink()
    command = [
        str(browser),
        *FLAGS,
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--virtual-time-budget=45000",
        f"--screenshot={target}",
        url,
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.wait(timeout=240)
    except subprocess.TimeoutExpired:
        process.kill()
    time.sleep(1)
    if target.exists() and target.stat().st_size > 20_000:
        print(f"  ok   {name:<22} {target.stat().st_size // 1024} KB")
        return True
    size = target.stat().st_size if target.exists() else 0
    print(f"  thin {name:<22} {size // 1024} KB - the page did not render in time")
    return False


def trim(name: str, height: int | None) -> None:
    """Cut DEV's logged-out banner off the bottom of a capture."""
    if not height:
        return
    path = OUT / name
    try:
        from PIL import Image
    except ImportError:
        print("  (Pillow not installed - skipping the banner trim)")
        return
    image = Image.open(path)
    if image.height <= height:
        return
    image.crop((0, 0, image.width, height)).save(path, optimize=True)
    print(f"  trimmed {name} to {height}px")


def main() -> int:
    browser = find_browser()
    if browser is None:
        print("no headless browser found (looked for Edge, Brave and Chrome)")
        return 1
    print(f"browser: {browser}")
    profile = ROOT / ".shot-profile"
    ok = 0
    for name, url, width, height, trim_to in SHOTS:
        print(f"capturing {url}")
        if shoot(browser, name, url, width, height, profile):
            trim(name, trim_to)
            ok += 1
    shutil.rmtree(profile, ignore_errors=True)
    print(f"\n{ok}/{len(SHOTS)} captured into {OUT}")
    return 0 if ok == len(SHOTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
