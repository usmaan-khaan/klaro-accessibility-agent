# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# Self-healing demo: a rotating library of seeded WCAG violations.
"""A library of 20 seeded accessibility violations, served in batches of 5.

Each call to ``write_batch`` regenerates the audit target page from the library
so the agent always finds a fresh, known set of issues to heal.
"""

import base64

BATCH_SIZE = 5


def _alt(i: int) -> str:
    # Real inline image (renders fine) but intentionally missing alt text,
    # so the snapshot looks clean while the audit still flags "Missing Alt Tag".
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='60'>"
        "<rect width='160' height='60' rx='6' fill='#9aa7b4'/>"
        f"<text x='80' y='36' font-family='Arial' font-size='15' fill='#ffffff' "
        f"text-anchor='middle'>Logo {i}</text></svg>"
    )
    src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return (
        f'<div class="case"><h3>Image case {i}</h3>'
        f'<img src="{src}" width="160" height="60"></div>'
    )


def _label(i: int) -> str:
    return (
        f'<div class="case"><h3>Field case {i}</h3>'
        f'<input type="text" id="field-{i}" placeholder="Enter value {i}"></div>'
    )


def _contrast(i: int) -> str:
    return (
        f'<div class="case"><h3>Text case {i}</h3>'
        f'<p style="color:#7f7f7f;background-color:#808080;padding:8px">'
        f'Low-contrast paragraph {i} that must be corrected to meet WCAG AA.</p></div>'
    )


def _role(i: int) -> str:
    return (
        f'<div class="case"><h3>Widget case {i}</h3>'
        f'<div role="popup-{i}">Custom widget {i} with an invalid ARIA role</div></div>'
    )


_BUILDERS = [_alt, _label, _contrast, _role]

# 20 cases: 5 of each violation type, interleaved.
CASES = [_BUILDERS[i % len(_BUILDERS)](i + 1) for i in range(20)]

TOTAL_BATCHES = (len(CASES) + BATCH_SIZE - 1) // BATCH_SIZE


def build_batch_page(start: int) -> str:
    start = start % len(CASES)
    fragments = "\n    ".join(CASES[start : start + BATCH_SIZE])
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8">\n'
        "<title>Accessibility Audit Target</title>\n"
        "<style>body{font-family:Arial,sans-serif;background:#fff;color:#111;padding:32px}"
        ".case{margin-bottom:18px}</style>\n</head>\n<body>\n"
        f"  <h1>Audit batch starting at case {start + 1}</h1>\n    {fragments}\n"
        "</body>\n</html>\n"
    )


def write_batch(target_path: str, start: int) -> int:
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(build_batch_page(start))
    return start
