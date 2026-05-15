"""Stub VLM client tests — deterministic, image-blind, schema-correct."""

import asyncio

import pytest

from services.vlm.app.client import GenerationRequest, StubVLMClient
from shared.schemas.scene import SceneDescription


def _req(trigger_reason: str, **kw) -> GenerationRequest:
    return GenerationRequest(
        trigger_id=kw.get("trigger_id", "trig-1"),
        trigger_reason=trigger_reason,
        sensor_refs=kw.get(
            "sensor_refs",
            {"thermal-01": {"sensor_type": "thermal", "value": 80.0, "unit": "degC"}},
        ),
        frames=kw.get("frames", []),
        location_hint=kw.get("location_hint", "lab-A"),
    )


@pytest.mark.asyncio
async def test_stub_thermal_threshold_yields_fire_hazard():
    client = StubVLMClient()
    scene = await client.generate_scene(_req("thermal_threshold"))
    assert isinstance(scene, SceneDescription)
    assert any(h.hazard_type == "fire" for h in scene.hazards)
    assert scene.contextual_factors["stub"] is True


@pytest.mark.asyncio
async def test_stub_gas_threshold_yields_gas_leak_hazard():
    client = StubVLMClient()
    scene = await client.generate_scene(_req("gas_threshold"))
    assert any(h.hazard_type == "gas_leak" for h in scene.hazards)


@pytest.mark.asyncio
async def test_stub_prone_yields_prone_person():
    client = StubVLMClient()
    scene = await client.generate_scene(_req("person_prone_persistent"))
    assert any(p.posture == "prone" for p in scene.people_present)


@pytest.mark.asyncio
async def test_stub_compound_reason_compounds_hazards():
    client = StubVLMClient()
    scene = await client.generate_scene(
        _req("thermal_threshold|gas_threshold")
    )
    types = {h.hazard_type for h in scene.hazards}
    assert "fire" in types
    assert "gas_leak" in types


@pytest.mark.asyncio
async def test_stub_ignores_frame_content_entirely():
    """Image-blindness: stub never reads bytes, so feeding garbage is safe."""
    client = StubVLMClient()
    s1 = await client.generate_scene(_req("thermal_threshold", frames=[]))
    s2 = await client.generate_scene(
        _req("thermal_threshold", frames=[("cam-01", "0-1", b"\xff" * 4)])
    )
    # Same trigger_reason → same shape (only the frame-count metadata differs).
    assert {h.hazard_type for h in s1.hazards} == {h.hazard_type for h in s2.hazards}


@pytest.mark.asyncio
async def test_stub_concurrent_calls_are_independent():
    """Validate the "5 concurrent triggers without queue buildup" contract."""
    client = StubVLMClient()
    reqs = [_req("thermal_threshold", trigger_id=f"t-{i}") for i in range(10)]
    scenes = await asyncio.gather(*(client.generate_scene(r) for r in reqs))
    assert len(scenes) == 10
    assert {s.trigger_id for s in scenes} == {f"t-{i}" for i in range(10)}
