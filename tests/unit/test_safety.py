from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import agent
from app.safety import (
    approved_response,
    content_hash,
    resolve_local_target,
    validate_repair,
)


@pytest.mark.parametrize(
    "response",
    [
        "do not approve",
        "not approved",
        "yesterday",
        "reject",
        {"approved": False, "result": "approve"},
        {"approved": "true"},
    ],
)
def test_negative_and_ambiguous_approval(response):
    assert not approved_response(response)


@pytest.mark.parametrize("response", ["approve", " YES ", {"approved": True}])
def test_exact_approval(response):
    assert approved_response(response)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://169.254.169.254",
        "https://example.com",
        "file:///etc/passwd",
    ],
)
def test_urls_are_disabled(url):
    with pytest.raises(ValueError):
        resolve_local_target(url, "demo.html")


def test_path_boundary(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    inside = root / "index.html"
    outside = tmp_path / "secret.html"
    inside.write_text("inside")
    outside.write_text("outside")
    monkeypatch.setenv("AUDIT_ALLOWED_DIR", str(root))
    assert resolve_local_target(str(inside), "demo.html") == str(inside.resolve())
    with pytest.raises(ValueError):
        resolve_local_target(str(outside), "demo.html")
    with pytest.raises(ValueError):
        resolve_local_target(str(root / ".." / "secret.html"), "demo.html")


ORIGINAL = '<html><body><p style="color:#777;background-color:#fff;padding:8px">Text</p><input id="email"><img src="logo.png"></body></html>'
HEALED = (
    ORIGINAL.replace("color:#777", "color:#111")
    .replace('<input id="email">', '<input id="email" aria-label="Email">')
    .replace('src="logo.png"', 'src="logo.png" alt="Logo"')
)


def test_narrow_accessibility_patch_allowed():
    validate_repair(ORIGINAL, HEALED)


def test_html_serialization_does_not_count_as_a_structural_edit():
    from bs4 import BeautifulSoup

    from app.case_library import build_batch_page

    original = build_batch_page(0)
    validate_repair(original, str(BeautifulSoup(original, "html.parser")).strip())


def test_visible_word_separation_is_preserved():
    original = "<html><body><span>A</span> <span>B</span></body></html>"
    with pytest.raises(ValueError):
        validate_repair(original, original.replace("</span> <span>", "</span><span>"))


@pytest.mark.parametrize(
    "candidate",
    [
        HEALED.replace("</body>", '<script>fetch("/resume")</script></body>'),
        HEALED.replace('src="logo.png"', 'src="https://attacker.example/logo.png"'),
        HEALED.replace("padding:8px", "padding:80px"),
        HEALED.replace("Text", "Completely different content"),
        HEALED.replace("color:#111", "color:url(https://attacker.example)"),
        HEALED.replace("color:#111", r"color:u\72l(https://attacker.example)"),
        "",
    ],
)
def test_unsafe_or_unrelated_patch_rejected(candidate):
    with pytest.raises(ValueError):
        validate_repair(ORIGINAL, candidate)


def _context(tmp_path):
    target = tmp_path / "index.html"
    target.write_text(ORIGINAL, encoding="utf-8")
    return SimpleNamespace(
        state={
            "html_path": str(target),
            "original_hash": content_hash(str(target)),
            "violations": [{"type": "original"}],
        }
    ), target


@pytest.mark.asyncio
async def test_browser_failure_keeps_original(tmp_path, monkeypatch):
    ctx, target = _context(tmp_path)
    monkeypatch.setattr(
        agent, "_audit_html_file", AsyncMock(side_effect=RuntimeError("browser failed"))
    )
    result = await agent.verify_remediation(ctx, HEALED)
    assert result.actions.route == "failed"
    assert target.read_text() == ORIGINAL
    assert not (tmp_path / "candidate.html").exists()


@pytest.mark.asyncio
async def test_failed_candidates_never_replace_original(tmp_path, monkeypatch):
    ctx, target = _context(tmp_path)
    monkeypatch.setattr(
        agent, "_audit_html_file", AsyncMock(return_value=[{"type": "contrast"}])
    )
    for _ in range(agent.MAX_HEAL_ATTEMPTS):
        result = await agent.verify_remediation(ctx, HEALED)
        assert target.read_text() == ORIGINAL
    assert result.actions.route == "giveup"


@pytest.mark.asyncio
async def test_verified_candidate_preserves_backup(tmp_path, monkeypatch):
    ctx, target = _context(tmp_path)
    monkeypatch.setattr(agent, "_audit_html_file", AsyncMock(return_value=[]))
    result = await agent.verify_remediation(ctx, HEALED)
    assert result.actions.route == "success"
    assert target.read_text() == HEALED
    assert (tmp_path / "original.html").read_text() == ORIGINAL


@pytest.mark.asyncio
async def test_changed_target_requires_new_review(tmp_path, monkeypatch):
    ctx, target = _context(tmp_path)
    target.write_text("changed since review")
    audit = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_audit_html_file", audit)
    result = await agent.verify_remediation(ctx, HEALED)
    assert result.actions.route == "failed"
    audit.assert_not_called()
    assert target.read_text() == "changed since review"


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<label>Name<input></label>", False),
        ('<input type="checkbox">', True),
        ('<input type="radio" aria-label="">', True),
        ('<input aria-labelledby="missing">', True),
        ('<span id="name">Name</span><input aria-labelledby="name">', False),
        ("<textarea></textarea><select></select>", True),
    ],
)
def test_accessible_control_names(html, expected):
    violations = agent.run_visual_audit(html, [])[2]["violations"]
    assert bool(violations) is expected
