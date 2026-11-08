"""Render `proofops demo` output as an SVG terminal card.

The point is a README/posts image that is not a mock-up: the text in the SVG is the real stdout of
the command, captured here and escaped into the image. If the demo changes, regenerate; the image
cannot drift from the product without someone running this script.

    python3 scripts/make_demo_svg.py docs/demo.svg
"""
from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

# Explicit prefixes, in the order the demo prints them. Anything else is dropped: a screenshot that
# includes half a sentence reads as a copy-paste accident rather than a product.
KEEP_ORDER = [
    ("  proofops demo — ", "title"),
    ("fixture: ", "body"),
    ("ProofOps run ", "verdict"),
    ("  plan      demo:", "body"),
    ("  [PASS] reachable", "pass"),
    ("  [FAIL] says-ok", "fail"),
    ("         observed:", "dim"),
    ("  Not verified:", "body"),
    ("    - that the rows are correct", "dim"),
    ("    - that anyone has read", "dim"),
    ("  Now edit the receipt", "body"),
    ("    original receipt:", "body"),
    ("    edited receipt:", "fail"),
]
MAXLINE = 88

CHARS = 96
FONT = 15
LINE = 21
PAD = 26
BAR = 34


def capture() -> list[tuple[str, str]]:
    """Return (line, kind) pairs, verbatim from stdout, truncated with an ellipsis if long."""
    out = subprocess.run([sys.executable, "-m", "proofops", "demo"],
                         capture_output=True, text=True, timeout=120)
    picked: list[tuple[str, str]] = []
    for raw in out.stdout.splitlines():
        for prefix, kind in KEEP_ORDER:
            if not raw.startswith(prefix):
                continue
            if prefix.strip() == "observed:":
                # The raw evidence dict starts with the loopback URL, which pushes the value that
                # matters ("degraded") past any sane card width. Keep the interesting keys verbatim
                # and say plainly that the rest exist.
                import json as _json
                try:
                    ev = _json.loads(raw.split("observed:", 1)[1].strip())
                    short = {k: ev[k] for k in ("expected", "observed", "http_status") if k in ev}
                    picked.append(("         observed: " + _json.dumps(short)[:-1] + ",",
                                   "fail"))
                    picked.append(("                   (full evidence also carries url, field,",
                                   "dim"))
                    picked.append(("                    mode, elapsed_ms in the receipt)", "dim"))
                except Exception:
                    picked.append((raw[:MAXLINE - 1] + "…", kind))
                break
            line = raw if len(raw) <= MAXLINE else raw[:MAXLINE - 1] + "…"
            picked.append((line, kind))
            break
    return picked


def render(lines: list[tuple[str, str]], out: Path) -> None:
    widest = max((len(l) for l, _ in lines), default=CHARS)
    width = PAD * 2 + int(min(widest, MAXLINE) * FONT * 0.62)
    height = BAR + PAD * 2 + LINE * len(lines)
    bg, panel, text, dim = "#0b0f15", "#121826", "#e6edf3", "#8b98ac"
    green, red = "#4ade80", "#f87171"

    colours = {"pass": green, "fail": red, "dim": dim, "title": text, "verdict": text, "body": text}
    rows = []
    for i, (line, kind) in enumerate(lines):
        y = BAR + PAD + LINE * i + FONT
        colour = colours[kind]
        weight = "600" if kind in ("pass", "fail", "verdict", "title") else "400"
        rows.append(
            f'<text x="{PAD}" y="{y}" fill="{colour}" font-weight="{weight}" '
            f'xml:space="preserve">{html.escape(line)}</text>'
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Terminal running proofops demo: one check passes on a 200, the next fails because the service reports degraded, and a forged receipt is detected as tampered.">
  <rect width="{width}" height="{height}" rx="12" fill="{bg}"/>
  <rect width="{width}" height="{BAR}" rx="12" fill="{panel}"/>
  <rect y="{BAR - 12}" width="{width}" height="12" fill="{panel}"/>
  <circle cx="22" cy="{BAR // 2}" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="{BAR // 2}" r="6" fill="#febc2e"/>
  <circle cx="62" cy="{BAR // 2}" r="6" fill="#28c840"/>
  <text x="{width // 2}" y="{BAR // 2 + 5}" fill="{dim}" font-family="ui-monospace,Menlo,monospace" font-size="12" text-anchor="middle">proofops demo</text>
  <g font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="{FONT}">
    {chr(10).join("    " + r for r in rows)}
  </g>
</svg>
'''
    out.write_text(svg)
    print(f"wrote {out} ({len(lines)} lines, {width}x{height})")
    for line, kind in lines:
        print(f"  [{kind:7}] {line}")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.svg")
    render(capture(), target)
