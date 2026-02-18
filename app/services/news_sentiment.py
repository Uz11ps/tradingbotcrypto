from __future__ import annotations

import re
from statistics import fmean
from typing import Any

import feedparser
import httpx

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

POSITIVE_WORDS = {
    "surge",
    "rally",
    "gain",
    "bullish",
    "breakout",
    "adoption",
    "partnership",
    "approval",
    "growth",
}
NEGATIVE_WORDS = {
    "dump",
    "crash",
    "hack",
    "bearish",
    "drop",
    "ban",
    "lawsuit",
    "exploit",
    "fear",
}


class NewsSentimentError(RuntimeError):
    pass


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]{3,}", text.lower())


def _score_text(text: str) -> float:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    pos = sum(1 for t in tokens if t in POSITIVE_WORDS)
    neg = sum(1 for t in tokens if t in NEGATIVE_WORDS)
    raw = pos - neg
    denom = max(3, pos + neg)
    score = raw / denom
    return max(-1.0, min(1.0, score))


def _symbol_aliases(symbol: str) -> set[str]:
    base = symbol.split("/")[0].upper()
    aliases = {base}
    if base == "BTC":
        aliases.update({"BITCOIN"})
    if base == "ETH":
        aliases.update({"ETHEREUM"})
    if base == "SOL":
        aliases.update({"SOLANA"})
    return aliases


async def _fetch_feed(url: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
    parsed = feedparser.parse(response.text)
    items: list[dict[str, str]] = []
    for entry in parsed.entries[:30]:
        title = str(entry.get("title", ""))
        link = str(entry.get("link", ""))
        summary = str(entry.get("summary", ""))
        if title and link:
            items.append({"title": title, "url": link, "summary": summary})
    return items


async def fetch_news_and_sentiment(symbol: str, *, limit: int = 8) -> dict[str, Any]:
    aliases = _symbol_aliases(symbol)
    all_items: list[dict[str, str]] = []
    for feed in RSS_FEEDS:
        try:
            all_items.extend(await _fetch_feed(feed))
        except Exception:
            continue

    if not all_items:
        raise NewsSentimentError("News feeds unavailable")

    filtered: list[dict[str, Any]] = []
    for item in all_items:
        text = f"{item['title']} {item['summary']}".upper()
        if not any(alias in text for alias in aliases):
            continue
        sentiment = _score_text(item["title"] + " " + item["summary"])
        filtered.append(
            {
                "title": item["title"],
                "url": item["url"],
                "source": "rss",
                "sentiment": sentiment,
            }
        )

    if not filtered:
        filtered = [
            {
                "title": item["title"],
                "url": item["url"],
                "source": "rss",
                "sentiment": _score_text(item["title"] + " " + item["summary"]),
            }
            for item in all_items[:limit]
        ]

    top = filtered[:limit]
    avg_sentiment = fmean([it["sentiment"] for it in top]) if top else 0.0

    return {
        "symbol": symbol,
        "avg_sentiment": float(avg_sentiment),
        "headlines": top,
    }

