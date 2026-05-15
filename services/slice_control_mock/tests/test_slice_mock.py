"""slice_control_mock state machine + WebSocket broadcast tests."""

import asyncio
import json

import httpx
import pytest

from services.slice_control_mock.app.main import _STORE, app
from services.slice_control_mock.app.state import SliceStore


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Each test gets an isolated SliceStore so order doesn't matter."""
    store = SliceStore()
    monkeypatch.setattr("services.slice_control_mock.app.main._STORE", store)
    return store


@pytest.mark.asyncio
async def test_get_state_initial():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as ac:
        r = await ac.get("/slices/state")
    assert r.status_code == 200
    body = r.json()
    assert body["eMBB"]["priority"] == 5
    assert body["URLLC"]["priority"] == 5
    assert body["mMTC"]["priority"] == 5
    assert body["preempt_active"] is False


@pytest.mark.asyncio
async def test_priority_change_persists():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as ac:
        r = await ac.post("/slices/URLLC/priority", json={"priority": 9})
        assert r.status_code == 200
        assert r.json()["URLLC"]["priority"] == 9
        r2 = await ac.get("/slices/state")
        assert r2.json()["URLLC"]["priority"] == 9


@pytest.mark.asyncio
async def test_priority_unknown_slice_404():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as ac:
        r = await ac.post("/slices/turbo/priority", json={"priority": 5})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_preempt_and_clear():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as ac:
        r = await ac.post("/slices/preempt",
                          json={"duration_seconds": 60, "reason": "fire"})
        body = r.json()
        assert body["preempt_active"] is True
        assert body["preempt_reason"] == "fire"
        assert body["preempt_until"] is not None

        r2 = await ac.post("/slices/preempt/clear")
        assert r2.json()["preempt_active"] is False


@pytest.mark.asyncio
async def test_websocket_broadcast_on_priority_change(fresh_store):
    """Done-when (2): live WebSocket reshape visibility."""
    received: list[dict] = []
    q = fresh_store.subscribe()

    async def reader():
        for _ in range(2):
            payload = await asyncio.wait_for(q.get(), timeout=1.0)
            received.append(json.loads(payload))

    reader_task = asyncio.create_task(reader())
    await fresh_store.set_priority("URLLC", 9)
    await fresh_store.set_priority("eMBB", 3)
    await asyncio.wait_for(reader_task, timeout=2.0)

    fresh_store.unsubscribe(q)
    assert len(received) == 2
    assert received[0]["event"] == "priority_change"
    assert received[0]["detail"] == {"slice_id": "URLLC", "priority": 9}
    assert received[0]["state"]["URLLC"]["priority"] == 9
    assert received[1]["detail"] == {"slice_id": "eMBB", "priority": 3}


@pytest.mark.asyncio
async def test_websocket_broadcast_on_preempt(fresh_store):
    q = fresh_store.subscribe()
    await fresh_store.preempt(30, "fire incident")
    msg = json.loads(await asyncio.wait_for(q.get(), timeout=1.0))
    fresh_store.unsubscribe(q)
    assert msg["event"] == "preempt_active"
    assert msg["detail"]["reason"] == "fire incident"
    assert msg["state"]["preempt_active"] is True
