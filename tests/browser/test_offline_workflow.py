"""Real Chromium + ADK workflow; the repair node is deterministic, with no Gemini calls."""

import asyncio
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.adk.workflow import Edge, Workflow, node
from google.genai import types

from app import agent
from app.ambient_service import _collect_response


@node
def deterministic_repair(ctx, node_input):
    ctx.state["repair_count"] = ctx.state.get("repair_count", 0) + 1
    soup = BeautifulSoup(Path(ctx.state["html_path"]).read_text(), "html.parser")
    for img in soup.find_all("img"):
        img["alt"] = "Demo logo"
    for inp in soup.find_all("input"):
        inp["aria-label"] = "Demo field"
    for element in soup.find_all(attrs={"role": True}):
        element["role"] = "group"
    for element in soup.find_all(attrs={"style": True}):
        if ctx.state.get("retry_once") and ctx.state["repair_count"] == 1:
            continue
        element["style"] = (
            element["style"]
            .replace("color:#7f7f7f", "color:#000000")
            .replace("background-color:#808080", "background-color:#ffffff")
        )
    return {"html": str(soup)}


def _make_runner():
    def replace(value):
        return deterministic_repair if value is agent.remediation_agent else value

    edges = [
        Edge(
            from_node=replace(edge.from_node),
            to_node=replace(edge.to_node),
            route=edge.route,
        )
        for edge in agent.root_agent.edges
    ]
    workflow = Workflow(name="offline_test", edges=edges)
    return InMemoryRunner(app=App(name="offline_test_app", root_agent=workflow))


async def start(runner, state=None):
    session = await runner.session_service.create_session(
        app_name="offline_test_app", user_id="tester", state=state or {}
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="tester",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="Audit demo")]
            ),
        )
    ]
    return session.id, _collect_response(events, session.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_pause_resume_with_real_browser(action):
    runner = _make_runner()
    session_id, response = await start(runner)
    assert response["status"] == "paused_for_hitl", response
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    name="adk_request_input",
                    id=response["interrupt_id"],
                    response={"result": action, "approved": action == "approve"},
                )
            )
        ],
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="tester", session_id=session_id, new_message=message
        )
    ]
    final = _collect_response(events, session_id)
    assert final["status"] == "completed", final
    output = "\n".join(final["outputs"])
    assert (
        "verified successfully" if action == "approve" else "rejected by human"
    ) in output, output


@pytest.mark.asyncio
async def test_concurrent_audits_use_separate_files():
    runner = _make_runner()
    sessions = await asyncio.gather(start(runner), start(runner))
    states = [
        (
            await runner.session_service.get_session(
                app_name="offline_test_app", user_id="tester", session_id=session_id
            )
        ).state
        for session_id, _ in sessions
    ]
    assert states[0]["html_path"] != states[1]["html_path"]
    assert states[0]["desktop_screenshot"] != states[1]["desktop_screenshot"]
    assert all(response["status"] == "paused_for_hitl" for _, response in sessions)


@pytest.mark.asyncio
async def test_retry_requires_fresh_approval_and_keeps_original():
    runner = _make_runner()
    session_id, response = await start(runner, {"retry_once": True})
    session = await runner.session_service.get_session(
        app_name="offline_test_app", user_id="tester", session_id=session_id
    )
    target = Path(session.state["html_path"])
    original = target.read_bytes()
    first_id = response["interrupt_id"]
    for attempt in range(2):
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="adk_request_input",
                        id=response["interrupt_id"],
                        response={"result": "approve", "approved": True},
                    )
                )
            ],
        )
        events = [
            event
            async for event in runner.run_async(
                user_id="tester", session_id=session_id, new_message=message
            )
        ]
        response = _collect_response(events, session_id)
        if attempt == 0:
            assert response["status"] == "paused_for_hitl", response
            assert response["interrupt_id"] != first_id
            assert target.read_bytes() == original
        else:
            assert response["status"] == "completed", response
            assert "verified successfully" in "\n".join(response["outputs"])


@pytest.mark.asyncio
async def test_offline_page_does_not_run_target_scripts():
    from playwright.async_api import async_playwright

    from app.safety import offline_page

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await offline_page(
                browser,
                '<html><body><script>document.body.dataset.executed="yes"</script><img src="http://127.0.0.1/private"></body></html>',
            )
            assert await page.evaluate("document.body.dataset.executed") is None
            assert await page.locator("img").evaluate("(img) => img.naturalWidth") == 0
        finally:
            await browser.close()
