from __future__ import annotations

from app.workers.mock_signal_worker import _select_shard_symbols


def test_select_shard_symbols_modulo_partition() -> None:
    symbols = [f"S{i:03d}/USDT" for i in range(1, 101)]
    shard0 = _select_shard_symbols(symbols, shard_index=0, shard_count=3)
    shard1 = _select_shard_symbols(symbols, shard_index=1, shard_count=3)
    shard2 = _select_shard_symbols(symbols, shard_index=2, shard_count=3)

    merged = set(shard0) | set(shard1) | set(shard2)
    assert len(merged) == 100
    assert set(shard0).isdisjoint(shard1)
    assert set(shard0).isdisjoint(shard2)
    assert set(shard1).isdisjoint(shard2)
