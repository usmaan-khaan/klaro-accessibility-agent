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

import asyncio
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from app.agent import root_agent, run_security_screen
from app.case_library import BATCH_SIZE, CASES, TOTAL_BATCHES

# Load local environment variables (.env)
load_dotenv()

_DASHBOARD_HTML = Path(__file__).parent / "dashboard" / "index.html"

# Configure logging using standard Python logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ambient_service")

# Disable otel log exports to cloud in local mode
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"

adk_app = App(name="accessibility_shield_app", root_agent=root_agent)
runner = InMemoryRunner(app=adk_app)

_batch = {"cursor": 0}
_session_access: dict[str, tuple[str, asyncio.Lock]] = {}
_pending_interrupts: dict[str, str] = {}

app = FastAPI(title="Accessibility Shield Pub/Sub and Webhook Service")

# Simple per-IP rate limit to protect the hosted instance's Gemini quota/cost.
_RATE_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
_hits: dict[str, deque] = {}


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    path = request.url.path
    if request.method == "POST" and (path == "/trigger" or path.startswith("/resume")):
        ip = request.client.host if request.client else "anon"
        now = time.time()
        dq = _hits.setdefault(ip, deque())
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= _RATE_PER_MIN:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit reached, try again in a minute."},
            )
        dq.append(now)
    return await call_next(request)


def is_request_input_event(event) -> bool:
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.function_call and part.function_call.name == "adk_request_input":
                return True
    return False


def get_interrupt_id(event) -> str | None:
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.function_call and part.function_call.name == "adk_request_input":
                return part.function_call.id
    return None


def get_request_input_message(event) -> str | None:
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.function_call and part.function_call.name == "adk_request_input":
                return part.function_call.args.get("message")
    return None


class TriggerPayload(BaseModel):
    commit_payload: str = Field(max_length=10000)
    user_id: str = Field(default="default-user", min_length=1, max_length=128)


class ResumeRequest(BaseModel):
    """Validated body for resuming a paused HITL session (see CONTEXT.md section 1)."""

    interrupt_id: str = Field(min_length=1, max_length=128)
    action: Literal["approve", "reject"]
    audit_token: str = Field(min_length=1, max_length=128)
    user_id: str = Field(default="default-user", min_length=1, max_length=128)


def _collect_response(events: list, session_id: str) -> dict[str, Any]:
    """Shared response shaping for /trigger and /resume."""
    response_data: dict[str, Any] = {
        "status": "completed",
        "session_id": session_id,
        "outputs": [],
    }
    seen: set[str] = set()
    for event in events:
        if is_request_input_event(event):
            response_data.update(
                {
                    "status": "paused_for_hitl",
                    "interrupt_id": get_interrupt_id(event),
                    "message": get_request_input_message(event),
                }
            )
            break
        # Workflow function-nodes carry their text on Event.output; LlmAgent
        # text arrives on content.parts. Capture both, de-duplicated.
        node_output = getattr(event, "output", None)
        if (
            isinstance(node_output, str)
            and node_output.strip()
            and node_output not in seen
        ):
            response_data["outputs"].append(node_output)
            seen.add(node_output)
        elif event.content and event.content.parts:
            for part in event.content.parts:
                if part.text and part.text not in seen:
                    response_data["outputs"].append(part.text)
                    seen.add(part.text)
    if response_data["status"] == "paused_for_hitl":
        _pending_interrupts[session_id] = response_data["interrupt_id"]
    else:
        _pending_interrupts.pop(session_id, None)
    return response_data


def _batch_info() -> dict:
    return {
        "batch": _batch["cursor"] // BATCH_SIZE + 1,
        "batches": TOTAL_BATCHES,
        "total_cases": len(CASES),
    }


@app.get("/batch-status")
async def batch_status() -> dict:
    return _batch_info()


@app.post("/next-batch")
async def next_batch() -> dict:
    _batch["cursor"] = (_batch["cursor"] + BATCH_SIZE) % len(CASES)
    return _batch_info()


@app.get("/")
async def dashboard() -> FileResponse:
    """Serve the interactive accessibility review dashboard."""
    if not _DASHBOARD_HTML.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return FileResponse(_DASHBOARD_HTML)


@app.post("/trigger", status_code=status.HTTP_200_OK)
async def trigger_audit(payload: TriggerPayload):
    """HTTP endpoint to trigger the accessibility shield audit workflow."""
    session = await runner.session_service.create_session(
        app_name="accessibility_shield_app",
        user_id=payload.user_id,
        state={"batch_cursor": _batch["cursor"]},
    )
    session_id = session.id
    token = secrets.token_urlsafe(32)
    _session_access[session_id] = (token, asyncio.Lock())
    logger.info("Created new session %s for user %s", session_id, payload.user_id)

    scrubbed, route, _ = run_security_screen(payload.commit_payload)
    if route != "clean":
        _session_access.pop(session_id, None)
        raise HTTPException(
            status_code=400, detail="Request failed security screening."
        )
    run_message = types.Content(
        role="user", parts=[types.Part.from_text(text=scrubbed)]
    )

    events = []
    try:
        async for event in runner.run_async(
            user_id=payload.user_id,
            session_id=session_id,
            new_message=run_message,
        ):
            events.append(event)
    except Exception as e:
        logger.error("Workflow execution failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    response = _collect_response(events, session_id)
    response["audit_token"] = token
    return response


@app.post("/resume/{session_id}", status_code=status.HTTP_200_OK)
async def resume_audit(session_id: str, body: ResumeRequest):
    """HTTP endpoint to resume a paused audit session with human choice."""
    access = _session_access.get(session_id)
    if not access or not secrets.compare_digest(access[0], body.audit_token):
        raise HTTPException(status_code=403, detail="Invalid session capability.")
    lock = access[1]
    if lock.locked():
        raise HTTPException(status_code=409, detail="Session is already being resumed.")
    async with lock:
        user_id = body.user_id
        list_resp = await runner.session_service.list_sessions(
            app_name="accessibility_shield_app", user_id=user_id
        )

        session_exists = any(s.id == session_id for s in list_resp.sessions)
        if not session_exists:
            raise HTTPException(status_code=404, detail="Session not found.")

        expected = _pending_interrupts.get(session_id)
        if not expected or body.interrupt_id != expected:
            raise HTTPException(
                status_code=409, detail="Stale or invalid approval interrupt."
            )
        approved = body.action == "approve"
        run_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="adk_request_input",
                        response={"result": body.action, "approved": approved},
                        id=body.interrupt_id,
                    )
                )
            ],
        )

        events = []
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=run_message,
            ):
                events.append(event)
        except Exception as e:
            logger.error("Workflow resumption failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e)) from e

        return _collect_response(events, session_id)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
