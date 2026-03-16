from __future__ import annotations

import os

from app.core.config import settings
from app.workers.mock_signal_worker import (
    _derive_shard_index_from_identity,
    _resolve_shard_index,
    _select_shard_symbols,
)


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


def test_derive_shard_index_from_identity_is_stable() -> None:
    a = _derive_shard_index_from_identity("abc123", 5)
    b = _derive_shard_index_from_identity("abc123", 5)
    assert a == b
    assert 0 <= a < 5


def test_resolve_shard_index_uses_hostname_hash_when_no_suffix() -> None:
    old_idx = settings.worker_shard_index
    old_hostname = os.getenv("HOSTNAME")
    try:
        settings.worker_shard_index = -1
        os.environ["HOSTNAME"] = "7b24ce847113"
        idx = _resolve_shard_index(5)
        assert 0 <= idx < 5
    finally:
        settings.worker_shard_index = old_idx
        if old_hostname is None:
            os.environ.pop("HOSTNAME", None)
        else:
            os.environ["HOSTNAME"] = old_hostname
