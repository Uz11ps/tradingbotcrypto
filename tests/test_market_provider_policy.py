from __future__ import annotations

from app.services.market_provider import MarketProviderRouter
from app.workers.mock_signal_worker import _format_market_route_trace


def test_market_policy_both_with_futures_adapter_disabled() -> None:
    router = MarketProviderRouter(futures_adapter_enabled=False)
    resolution = router.resolve("both")

    assert [route.market_type for route in resolution.enabled_routes] == ["spot"]
    assert [route.market_type for route in resolution.skipped_routes] == ["futures"]
    assert resolution.skipped_routes[0].reason == "futures_adapter_disabled"


def test_market_policy_both_with_futures_adapter_enabled() -> None:
    router = MarketProviderRouter(futures_adapter_enabled=True)
    resolution = router.resolve("both")

    assert [route.market_type for route in resolution.enabled_routes] == ["spot", "futures"]
    assert resolution.skipped_routes == ()
    assert resolution.enabled_routes[1].reason == "futures_route_live_source"


def test_market_route_trace_contains_policy_and_routes() -> None:
    router = MarketProviderRouter(futures_adapter_enabled=False)
    line = _format_market_route_trace(router, chat_id=777, requested_market_type="both")

    assert "market_route_trace" in line
    assert "chat_id=777" in line
    assert "policy=futures_adapter_disabled" in line
    assert "enabled=spot:bingx_spot" in line
    assert "skipped=futures:futures_adapter_disabled" in line

