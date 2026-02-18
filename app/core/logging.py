from __future__ import annotations

import logging


def setup_logging(level: str) -> None:
    # Минимальная настройка: единый формат для API/бота/воркеров.
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

