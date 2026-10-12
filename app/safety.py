"""Boundaries for offline audits and narrowly scoped model repairs."""

import hashlib
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup


def resolve_local_target(text: str, default: str) -> str:
    if re.search(r"[a-z][a-z0-9+.-]*://", text, re.I):
        raise ValueError(
            "Live URL audits are disabled: an isolated egress service is required."
        )
    candidate = text.strip()
    if not candidate.lower().endswith(".html") or "\n" in candidate:
        return default
    allowed = os.environ.get("AUDIT_ALLOWED_DIR")
    if not allowed:
        raise ValueError("Local file audits require AUDIT_ALLOWED_DIR.")
    root = Path(allowed).resolve(strict=True)
    target = Path(candidate).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("Target must be an HTML file inside AUDIT_ALLOWED_DIR.")
    return str(target)


def content_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def approved_response(response) -> bool:
    # An explicit boolean takes precedence over any accompanying free text.
    if isinstance(response, dict):
        if "approved" in response:
            return response["approved"] is True
        response = response.get("result", "")
    return isinstance(response, str) and response.strip().lower() in {
        "yes",
        "approve",
        "approved",
    }


_COLOR = re.compile(r"(?<![\w-])(?:color|background-color)\s*:\s*[^;}]+;?", re.I)
_ACCESSIBILITY = {
    "alt",
    "role",
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "tabindex",
}


def _without_colors(css: str) -> str:
    for declaration in _COLOR.findall(css):
        value = declaration.split(":", 1)[1].strip().rstrip(";").strip()
        if not re.fullmatch(
            r"(?:#[0-9a-f]{3,8}|[a-z]+|(?:rgb|rgba|hsl|hsla)\([0-9.,% /+-]+\))(?:\s*!important)?",
            value,
            re.I,
        ):
            raise ValueError("Only literal CSS colors are permitted in repairs.")
    return _COLOR.sub("", css)


def validate_repair(original: str, candidate: str) -> None:
    """Reject structural, script, URL, text, and non-accessibility changes.

    Repairs use naming attributes rather than adding labels or rewriting markup.
    Color changes are allowed; CSS URLs and executable values are never added.
    """
    if not candidate.strip():
        raise ValueError("Empty repair.")
    before = BeautifulSoup(original, "html.parser")
    after = BeautifulSoup(candidate, "html.parser")
    if not after.find("html") or not after.find("body"):
        raise ValueError("Repair must contain a complete HTML document.")
    old_tags, new_tags = before.find_all(True), after.find_all(True)
    if len(old_tags) != len(new_tags):
        raise ValueError("Repair changed document structure.")
    for old, new in zip(old_tags, new_tags, strict=True):
        if old.name != new.name:
            raise ValueError("Repair changed document structure.")
        for key in set(old.attrs) | set(new.attrs):
            if old.get(key) == new.get(key):
                continue
            if (
                key == "charset"
                and str(old.get(key, "")).lower() == str(new.get(key, "")).lower()
            ):
                new[key] = old[key]
                continue
            if key in _ACCESSIBILITY:
                continue
            if key == "style":
                old_style, new_style = str(old.get(key, "")), str(new.get(key, ""))
                if re.search(r"url\s*\(|expression\s*\(|@import", new_style, re.I):
                    raise ValueError("Unsafe CSS in repair.")
                if (
                    _without_colors(old_style).strip()
                    == _without_colors(new_style).strip()
                ):
                    continue
            raise ValueError(f"Repair changed forbidden attribute: {key}.")
        # Normalize only the allowed edits before comparing the entire DOM.
        for key in _ACCESSIBILITY | {"style"}:
            if key in old.attrs:
                new[key] = old[key]
            else:
                new.attrs.pop(key, None)
        if old.name == "style" and old.string != new.string:
            css = str(new.string or "")
            if re.search(r"url\s*\(|expression\s*\(|@import", css, re.I):
                raise ValueError("Unsafe stylesheet repair.")
            if _without_colors(str(old.string or "")) != _without_colors(css):
                raise ValueError("Repair changed non-color CSS.")
            new.string = old.string or ""
    for soup in (before, after):
        for text in list(soup.find_all(string=True)):
            if not str(text).strip() and text.parent.name not in {
                "pre",
                "textarea",
                "script",
                "style",
            }:
                text.replace_with(" ")
    if str(before) != str(after):
        raise ValueError(
            "Repair changed content outside accessibility attributes and colors."
        )


async def offline_page(browser, html: str):
    """No scripts, service workers, or network/local-file requests from target HTML."""
    context = await browser.new_context(
        viewport={"width": 1200, "height": 800},
        java_script_enabled=False,
        service_workers="block",
    )
    await context.route("**/*", lambda route: route.abort())
    page = await context.new_page()
    await page.set_content(html, wait_until="load", timeout=45000)
    return page
