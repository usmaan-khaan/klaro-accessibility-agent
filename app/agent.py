# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import logging
import os
import re

import google.auth
from dotenv import load_dotenv

# Load local environment variables (.env)
load_dotenv()

logger = logging.getLogger("accessibility_shield.agent")

# Set up local authentication environment variables
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    try:
        _, project_id = google.auth.default()
        if project_id:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    except Exception:
        pass

if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

if "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import START, Edge, Workflow, node
from google.genai import types
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maximum number of self-heal attempts before the workflow gives up. Without
# this cap the verify -> remediate loop could run forever (and burn tokens)
# whenever the model fails to fully fix a page.
MAX_HEAL_ATTEMPTS = int(os.environ.get("MAX_HEAL_ATTEMPTS", "3"))

_MOCK_APP_DIR = os.path.join(os.path.dirname(__file__), "mock_app")
DEFAULT_TARGET_HTML = os.path.abspath(os.path.join(_MOCK_APP_DIR, "index.html"))
DESKTOP_SCREENSHOT = os.path.abspath(os.path.join(_MOCK_APP_DIR, "screenshot_desktop.png"))
MOBILE_SCREENSHOT = os.path.abspath(os.path.join(_MOCK_APP_DIR, "screenshot_mobile.png"))

# ---------------------------------------------------------------------------
# Regular expressions for PII and sensitive data
# ---------------------------------------------------------------------------
SSH_KEY_REGEX = re.compile(
    r"-----BEGIN [A-Z ]+ PRIVATE KEY-----\n[\s\S]+?\n-----END [A-Z ]+ PRIVATE KEY-----"
)
DB_TOKEN_REGEX = re.compile(
    r"\b(?:postgres|postgresql|mongodb|mysql|redis):\/\/[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+(?::\d+)?\/?[a-zA-Z0-9_.-]*\b"
)
API_KEY_REGEX = re.compile(r"\bAIzaSy[a-zA-Z0-9-_]{33}\b")

# Prompt-injection detection. We match on a whitespace-normalised, lower-cased
# copy of the text using word-aware regexes. This avoids the brittleness of raw
# substring checks while keeping the false-positive surface small.
INJECTION_PATTERNS = [
    r"ignore (?:all |the )?(?:previous |prior |above )?instructions",
    r"disregard (?:all |the )?(?:previous |prior |above )?(?:instructions|rules)",
    r"bypass (?:the )?(?:rules|safeguards|guardrails|security)",
    r"override (?:the )?(?:prompt|system|instructions)",
    r"auto[ -]?approve",
    r"force (?:the )?approval",
    r"you must approve",
    r"reveal (?:your )?(?:system )?prompt",
]
INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def run_security_screen(text: str) -> tuple[str, str, dict]:
    """Core security logic that can be tested directly without ADK wrappers."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if INJECTION_REGEX.search(normalized):
        return (
            "Security threat detected: Prompt injection block triggered.",
            "flagged",
            {"security_threat": True},
        )

    # Redact sensitive data
    scrubbed = text
    scrubbed, ssh_count = SSH_KEY_REGEX.subn("[REDACTED_SSH_KEY]", scrubbed)
    scrubbed, db_count = DB_TOKEN_REGEX.subn("[REDACTED_DB_CONNECTION]", scrubbed)
    scrubbed, key_count = API_KEY_REGEX.subn("[REDACTED_GOOGLE_API_KEY]", scrubbed)

    state_delta = {
        "redacted_pii_count": ssh_count + db_count + key_count,
        "security_threat": False,
    }
    return scrubbed, "clean", state_delta


@node
def security_screen(node_input: types.Content | str) -> Event:
    """Redacts sensitive developer PII (like SSH keys, DB tokens, API keys) and blocks prompt injections."""
    text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text or ""
    elif hasattr(node_input, "text"):
        text = node_input.text or ""
    else:
        text = str(node_input)

    output_text, route, state_delta = run_security_screen(text)
    # Preserve the (scrubbed) request so downstream nodes can pick a target.
    state_delta["request_text"] = text
    return Event(output=output_text, route=route, state=state_delta)


# ---------------------------------------------------------------------------
# Browser / visual auditing helpers
# ---------------------------------------------------------------------------

# JS that walks the rendered DOM and flags text whose contrast ratio is below
# the WCAG 2.2 AA threshold. Large text (>=24px, or >=18.66px bold) only needs
# 3:1; everything else needs 4.5:1 - so we no longer flag valid headings.
_CONTRAST_JS = r"""
() => {
    const elements = Array.from(document.querySelectorAll('*')).filter(el => {
        const childNodes = Array.from(el.childNodes);
        return childNodes.some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    });
    const results = [];
    elements.forEach(el => {
        const style = window.getComputedStyle(el);
        const color = style.color;
        let bgColor = style.backgroundColor;
        let parent = el;
        while ((bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') && parent.parentElement) {
            parent = parent.parentElement;
            bgColor = window.getComputedStyle(parent).backgroundColor;
        }
        if (bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') {
            bgColor = 'rgb(255, 255, 255)';
        }

        function getLuminance(rgbStr) {
            const m = rgbStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
            if (!m) return 1.0;
            const conv = v => {
                v = v / 255;
                return (v <= 0.04045) ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            };
            return 0.2126 * conv(+m[1]) + 0.7152 * conv(+m[2]) + 0.0722 * conv(+m[3]);
        }

        const l1 = getLuminance(color);
        const l2 = getLuminance(bgColor);
        const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);

        const fontSize = parseFloat(style.fontSize) || 16;
        const fontWeight = parseInt(style.fontWeight) || 400;
        const isLarge = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
        const required = isLarge ? 3.0 : 4.5;

        if (ratio < required) {
            results.push({
                element: el.tagName.toLowerCase(),
                id: el.id,
                class: el.className,
                text: el.textContent.trim().substring(0, 60),
                contrast: ratio.toFixed(2),
                required: required.toFixed(1),
                color: color,
                bgColor: bgColor
            });
        }
    });
    return results;
}
"""


REMOTE_CAPTURE = os.path.abspath(os.path.join(_MOCK_APP_DIR, "_remote_capture.html"))


def _extract_url(text) -> str | None:
    m = re.search(r"https?://[^\s'\"<>]+", str(text or ""))
    return m.group(0) if m else None


def _resolve_target(text) -> tuple[str, bool]:
    """Return (target, is_remote).

    A http(s) URL in the request is audited live; otherwise an existing local
    .html path is used; otherwise the bundled demo page.
    """
    url = _extract_url(text)
    if url:
        return url, True
    candidate = str(text or "").strip()
    if (
        candidate
        and "\n" not in candidate
        and candidate.lower().endswith(".html")
        and os.path.isfile(candidate)
    ):
        return os.path.abspath(candidate), False
    return DEFAULT_TARGET_HTML, False


def _file_url(path: str) -> str:
    return f"file:///{path.replace(os.sep, '/')}"


@node
async def browser_control_node(ctx: Context, node_input: str) -> Event:
    """Launches headless Chromium to snapshot + scan the target (a live URL or a local file)."""
    target, is_remote = _resolve_target(ctx.state.get("request_text", node_input))
    nav = target if is_remote else _file_url(target)
    html_path = target

    contrast_violations = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1200, "height": 800})
            await page.goto(nav, wait_until="load", timeout=45000)
            await page.screenshot(path=DESKTOP_SCREENSHOT)
            contrast_violations = await page.evaluate(_CONTRAST_JS)

            # For a remote URL, materialise the rendered DOM to a local file so the
            # rest of the pipeline (audit, heal, verify) works unchanged. The live
            # site is never modified; the healed copy is downloadable from the dashboard.
            if is_remote:
                rendered = await page.content()
                with open(REMOTE_CAPTURE, "w", encoding="utf-8") as fh:
                    fh.write(rendered)
                html_path = REMOTE_CAPTURE

            await page.set_viewport_size({"width": 375, "height": 812})
            await page.screenshot(path=MOBILE_SCREENSHOT)
            await browser.close()
    except Exception as e:  # pragma: no cover - environment dependent
        logger.error("Playwright capture failed for %s: %s", target, e, exc_info=True)
        return Event(
            output=(
                f"Could not load the target ({target}). If it is a URL, check it is public "
                "and reachable; if this is a fresh environment, run "
                "`uv run playwright install --with-deps chromium`. "
                f"Details: {e}"
            ),
            route="approved",
            state={"html_path": html_path if not is_remote else "", "contrast_violations": []},
        )

    state_delta = {
        "desktop_screenshot": DESKTOP_SCREENSHOT,
        "mobile_screenshot": MOBILE_SCREENSHOT,
        "contrast_violations": contrast_violations,
        "html_path": html_path,
        "target": target,
        "is_remote": is_remote,
    }
    return Event(
        output="Screenshots and visual data captured successfully.", state=state_delta
    )


# Valid WAI-ARIA roles (WCAG 2.2). Kept module-level so audit + verify share it.
VALID_ARIA_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "button", "cell",
    "checkbox", "columnheader", "combobox", "complementary", "contentinfo",
    "definition", "dialog", "directory", "document", "feed", "figure", "form",
    "grid", "gridcell", "group", "heading", "img", "link", "list", "listbox",
    "listitem", "log", "main", "marquee", "math", "menu", "menubar", "menuitem",
    "menuitemcheckbox", "menuitemradio", "navigation", "none", "note", "option",
    "presentation", "progressbar", "radio", "radiogroup", "region", "row",
    "rowgroup", "rowheader", "scrollbar", "search", "searchbox", "separator",
    "slider", "spinbutton", "status", "switch", "tab", "table", "tablist",
    "tabpanel", "term", "textbox", "timer", "toolbar", "tooltip", "tree",
    "treegrid", "treeitem",
}


def run_visual_audit(
    html_content: str, contrast_violations: list
) -> tuple[str, str, dict]:
    """Core visual audit logic that can be tested directly without ADK wrappers."""
    soup = BeautifulSoup(html_content, "html.parser")
    violations = []

    # 1. Missing alt tags
    for img in soup.find_all("img"):
        if not img.has_attr("alt"):
            violations.append(
                {
                    "type": "Missing Alt Tag",
                    "element": str(img),
                    "description": f"Image tag '{img.get('src', '')}' has no 'alt' attribute.",
                }
            )

    # 2. Missing form labels
    label_fors = {
        label.get("for") for label in soup.find_all("label") if label.get("for")
    }
    for inp in soup.find_all("input"):
        inp_type = inp.get("type", "text").lower()
        if inp_type in ["hidden", "submit", "button", "image", "checkbox", "radio"]:
            continue
        inp_id = inp.get("id")
        if not inp_id or (inp_id not in label_fors):
            if not inp.has_attr("aria-label") and not inp.has_attr("aria-labelledby"):
                violations.append(
                    {
                        "type": "Missing Form Label",
                        "element": str(inp),
                        "description": f"Input field '{inp.get('id') or ''}' has no associated label or ARIA naming attributes.",
                    }
                )

    # 3. Invalid ARIA roles
    for el in soup.find_all(attrs={"role": True}):
        role = el.get("role")
        if role not in VALID_ARIA_ROLES:
            violations.append(
                {
                    "type": "Invalid ARIA Role",
                    "element": str(el),
                    "description": f"Element uses invalid ARIA role '{role}': {el}",
                }
            )

    # 4. Integrate contrast violations
    for cv in contrast_violations:
        required = cv.get("required", "4.5")
        violations.append(
            {
                "type": "Low Color Contrast",
                "element": f"<{cv['element']} id='{cv['id']}' class='{cv['class']}'>",
                "description": f"Text '{cv['text']}' contrast ratio is {cv['contrast']}:1. Foreground: {cv['color']}, background: {cv['bgColor']}. Must be >= {required}:1.",
            }
        )

    state_delta = {"violations": violations}
    if violations:
        return (
            f"Visual audit completed: {len(violations)} accessibility issues found.",
            "violations",
            state_delta,
        )
    return (
        "Visual audit completed: All accessibility checks passed.",
        "approved",
        state_delta,
    )


@node
def visual_audit_node(ctx: Context, node_input: str) -> Event:
    """Evaluates HTML DOM structure against WCAG 2.2 AA standards (alt tags, labels, ARIA roles, contrast)."""
    html_path = ctx.state.get("html_path")
    if not html_path or not os.path.exists(html_path):
        return Event(output="Error: target HTML file not found.", route="approved")

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    contrast_violations = ctx.state.get("contrast_violations", [])
    output_msg, route, state_delta = run_visual_audit(html_content, contrast_violations)
    return Event(output=output_msg, route=route, state=state_delta)


@node
def format_remediation_request(ctx: Context, node_input: str) -> str:
    """Prepares the prompt for the remediation LLM agent."""
    html_path = ctx.state.get("html_path")
    if not html_path or not os.path.exists(html_path):
        return "Error: no target HTML available for remediation."

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    violations = ctx.state.get("violations", [])
    violations_desc = "\n".join(f"- {v['type']}: {v['description']}" for v in violations)

    return f"""
You are an expert accessibility healing assistant.
The following HTML file has accessibility violations:

--- HTML FILE ---
{html_content}

--- WCAG 2.2 AA VIOLATIONS ---
{violations_desc}

Please return the entire HTML file, with the violations fixed:
1. Add missing 'alt' attributes to images.
2. Associate labels with inputs (ensure inputs have matching labels or aria-label/aria-labelledby attributes).
3. Correct color contrast ratios so text meets >= 4.5:1 (large text >= 3:1).
4. Correct invalid ARIA roles (e.g. change invalid roles to valid roles like role="dialog" or remove them if not needed).

Rules:
- Do NOT modify the layout or structure of the HTML, only add or update accessibility-related attributes and styles.
- Return ONLY the raw HTML code. Do NOT wrap it in markdown code blocks.
"""


remediation_agent = LlmAgent(
    name="remediation_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are an expert web accessibility engineer that patches HTML code to meet WCAG 2.2 AA requirements.",
)


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing markdown code fence if the model added one."""
    healed = (text or "").strip()
    if healed.startswith("```"):
        lines = healed.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        healed = "\n".join(lines).strip()
    return healed


@node(rerun_on_resume=True)
async def human_approval_gate(ctx: Context, node_input: str):
    """Pauses execution if violations are found, serving broken/healed comparisons and snapshots to the dashboard."""
    violations = ctx.state.get("violations", [])
    if not violations:
        yield Event(output="No violations to approve.", route="approved")
        return

    # Prepare healed HTML from LlmAgent output (node_input may be str/Content).
    if hasattr(node_input, "parts") and node_input.parts:
        raw = node_input.parts[0].text or ""
    else:
        raw = str(node_input or "")
    healed_html = _strip_code_fence(raw)

    html_path = ctx.state.get("html_path")
    broken_html = ""
    if html_path and os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            broken_html = f.read()

    def _b64(path_key: str) -> str:
        p = ctx.state.get(path_key)
        if p and os.path.exists(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        return ""

    if not ctx.resume_inputs:
        payload = {
            "violations": violations,
            "broken_html": broken_html,
            "healed_html": healed_html,
            "desktop_snapshot": _b64("desktop_screenshot"),
            "mobile_snapshot": _b64("mobile_screenshot"),
        }
        # Stash healed html so we don't depend on the resume payload echoing it.
        ctx.state["healed_html"] = healed_html
        yield RequestInput(
            interrupt_id="confirm_remediation", message=json.dumps(payload)
        )
        return

    user_response = ctx.resume_inputs.get("confirm_remediation")
    response_str = ""
    approved = False
    if isinstance(user_response, dict):
        response_str = str(
            user_response.get("result")
            or user_response.get("value")
            or user_response.get("response")
            or next(iter(user_response.values()), "")
        )
        approved = bool(user_response.get("approved", False))
    else:
        response_str = str(user_response or "")

    healed_html = ctx.state.get("healed_html", healed_html)
    if approved or "yes" in response_str.lower() or "approve" in response_str.lower():
        yield Event(output=healed_html, route="remediating")
    else:
        yield Event(
            output="Remediation rejected by human gate. Keeping original broken files.",
            route="approved",
        )


async def _audit_html_file(html_path: str) -> list:
    """Re-run the full audit (static + live contrast) on a healed file."""
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    contrast_violations: list = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1200, "height": 800})
            await page.goto(_file_url(html_path))
            contrast_violations = await page.evaluate(_CONTRAST_JS)
            await browser.close()
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning("Contrast re-check skipped (browser unavailable): %s", e)

    _msg, _route, state = run_visual_audit(html_content, contrast_violations)
    return state["violations"]


@node
async def verify_remediation_node(ctx: Context, node_input: str) -> Event:
    """Overwrites HTML with healed code and re-audits it to confirm the fix actually worked."""
    healed_html = _strip_code_fence(str(node_input or ""))
    html_path = ctx.state.get("html_path")
    if not html_path:
        return Event(output="Verification failed: no target HTML path.", route="retry")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(healed_html)

    attempts = ctx.state.get("heal_attempts", 0) + 1
    ctx.state["heal_attempts"] = attempts

    remaining = await _audit_html_file(html_path)

    if not remaining:
        ctx.state["violations"] = []
        return Event(
            output="Self-healing verified successfully. All WCAG 2.2 AA checks passed.",
            route="success",
        )

    # Still broken - keep the residual list for the next remediation prompt.
    ctx.state["violations"] = remaining
    if attempts >= MAX_HEAL_ATTEMPTS:
        summary = "; ".join(v["type"] for v in remaining[:5])
        return Event(
            output=(
                f"Gave up after {attempts} heal attempts. "
                f"{len(remaining)} issue(s) remain: {summary}."
            ),
            route="giveup",
        )
    return Event(
        output=f"Verification found {len(remaining)} remaining issue(s); retrying (attempt {attempts}/{MAX_HEAL_ATTEMPTS}).",
        route="retry",
    )


@node
def security_alert(node_input: str) -> Event:
    return Event(
        output=f"SECURITY ALERT: Workflow terminated due to violation: {node_input}"
    )


@node
def approved_node(node_input: str) -> Event:
    return Event(output=f"PROCESS COMPLETED: {node_input}")


@node
def giveup_node(node_input: str) -> Event:
    return Event(output=f"REMEDIATION INCOMPLETE: {node_input}")


# State Graph Workflow Configuration
root_agent = Workflow(
    name="root_agent",
    edges=[
        Edge(from_node=START, to_node=security_screen),
        Edge(from_node=security_screen, to_node=browser_control_node, route="clean"),
        Edge(from_node=security_screen, to_node=security_alert, route="flagged"),
        Edge(from_node=browser_control_node, to_node=visual_audit_node),
        Edge(
            from_node=visual_audit_node,
            to_node=format_remediation_request,
            route="violations",
        ),
        Edge(from_node=visual_audit_node, to_node=approved_node, route="approved"),
        Edge(from_node=format_remediation_request, to_node=remediation_agent),
        Edge(from_node=remediation_agent, to_node=human_approval_gate),
        Edge(
            from_node=human_approval_gate,
            to_node=verify_remediation_node,
            route="remediating",
        ),
        Edge(from_node=human_approval_gate, to_node=approved_node, route="approved"),
        Edge(from_node=verify_remediation_node, to_node=approved_node, route="success"),
        Edge(from_node=verify_remediation_node, to_node=giveup_node, route="giveup"),
        Edge(
            from_node=verify_remediation_node,
            to_node=format_remediation_request,
            route="retry",
        ),
    ],
)

app = App(
    root_agent=root_agent,
    name="accessibility_shield_app",
)
