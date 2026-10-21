"""List every image tag in the published body and resolve the disclosure fields."""

import json
import re
import urllib.request

POST = "https://dev.to/api/articles/4885250"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def main() -> int:
    data = json.loads(get(POST).decode("utf-8"))
    body = data.get("body_html", "")

    print("=== every <img> in the published body ===")
    tags = re.findall(r"<img[^>]*>", body)
    print(f"  {len(tags)} image tag(s)")
    for tag in tags:
        print("  " + tag[:400])

    print("\n=== does the raw github url appear anywhere in the body? ===")
    for needle in ("raw.githubusercontent", "siesta", "media2.dev.to/dynamic/image/width=800"):
        print(f"  {needle!r}: {needle in body}")

    print("\n=== article fields mentioning disclosure / ai ===")
    for key, value in data.items():
        if "disclos" in key.lower() or key.lower() in ("ai", "ai_disclosure", "type"):
            print(f"  {key}: {value}")
    for key in ("ai_disclosure_level", "ai_disclosure_label"):
        print(f"  {key}: {data.get(key, '<absent>')}")

    print("\n=== body_markdown: the image line as submitted ===")
    markdown = data.get("body_markdown", "")
    for line in markdown.splitlines():
        if "siesta-ui" in line or "![" in line:
            print("  " + line.strip()[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
