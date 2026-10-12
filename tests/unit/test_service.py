import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import ambient_service as service


@pytest.fixture(autouse=True)
def clear_capabilities():
    service._session_access.clear()
    service._pending_interrupts.clear()
    yield
    service._session_access.clear()
    service._pending_interrupts.clear()


@pytest.mark.parametrize("action", ["do not approve", "not approved", "yes", ""])
def test_resume_action_is_an_enum(action):
    with pytest.raises(ValidationError):
        service.ResumeRequest(interrupt_id="review", action=action, audit_token="token")


@pytest.mark.asyncio
async def test_invalid_token_never_runs_agent(monkeypatch):
    service._session_access["session"] = ("private", asyncio.Lock())
    runner = SimpleNamespace(session_service=SimpleNamespace(list_sessions=AsyncMock()))
    monkeypatch.setattr(service, "runner", runner)
    with pytest.raises(HTTPException) as exc:
        await service.resume_audit(
            "session",
            service.ResumeRequest(
                interrupt_id="review", action="approve", audit_token="wrong"
            ),
        )
    assert exc.value.status_code == 403
    runner.session_service.list_sessions.assert_not_called()


@pytest.mark.asyncio
async def test_replayed_or_stale_interrupt_is_rejected(monkeypatch):
    service._session_access["session"] = ("private", asyncio.Lock())
    sessions = SimpleNamespace(
        list_sessions=AsyncMock(
            return_value=SimpleNamespace(sessions=[SimpleNamespace(id="session")])
        ),
        get_session=AsyncMock(return_value=SimpleNamespace(state={})),
    )
    monkeypatch.setattr(service, "runner", SimpleNamespace(session_service=sessions))
    with pytest.raises(HTTPException) as exc:
        await service.resume_audit(
            "session",
            service.ResumeRequest(
                interrupt_id="old_review", action="approve", audit_token="private"
            ),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_resume_is_rejected():
    lock = asyncio.Lock()
    await lock.acquire()
    service._session_access["session"] = ("private", lock)
    try:
        with pytest.raises(HTTPException) as exc:
            await service.resume_audit(
                "session",
                service.ResumeRequest(
                    interrupt_id="review", action="approve", audit_token="private"
                ),
            )
        assert exc.value.status_code == 409
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_batch_change_does_not_write_shared_target(monkeypatch):
    from pathlib import Path

    from app.agent import DEFAULT_TARGET_HTML

    before = Path(DEFAULT_TARGET_HTML).read_bytes()
    await service.next_batch()
    assert Path(DEFAULT_TARGET_HTML).read_bytes() == before
