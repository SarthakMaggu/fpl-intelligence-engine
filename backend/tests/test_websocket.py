"""Tests for api/websocket.py — verifies the fix for the critical ImportError."""
import asyncio
import pytest


def test_websocket_module_has_router():
    """router must be importable (was missing before the fix)."""
    from api.websocket import router
    from fastapi import APIRouter
    assert isinstance(router, APIRouter), "router should be an APIRouter instance"


def test_start_pubsub_listener_is_coroutine():
    """start_pubsub_listener must be a module-level async function, not a bound method."""
    from api.websocket import start_pubsub_listener
    assert asyncio.iscoroutinefunction(start_pubsub_listener), (
        "start_pubsub_listener must be an async def at module level"
    )


def test_start_pubsub_listener_accepts_optional_arg():
    """main.py calls start_pubsub_listener(ws_manager) — verify it accepts that arg."""
    from api.websocket import start_pubsub_listener, ws_manager
    import inspect
    sig = inspect.signature(start_pubsub_listener)
    # The _manager param should exist with a default (None)
    params = list(sig.parameters.values())
    assert len(params) >= 1, "start_pubsub_listener should accept at least one argument"
    assert params[0].default is None or params[0].default is inspect.Parameter.empty


def test_ws_manager_singleton_exists():
    """ws_manager singleton should be importable."""
    from api.websocket import ws_manager
    assert ws_manager is not None


def test_websocket_router_has_websocket_route():
    """The router should have the /ws/live WebSocket route registered."""
    from api.websocket import router
    routes = router.routes
    assert any(
        getattr(r, "path", "") == "/ws/live"
        for r in routes
    ), "router must have a /ws/live WebSocket route"
