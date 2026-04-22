"""Shared token/symbol matching helpers for news classification."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

SYMBOL_ALIASES = {
    "BTC": ("bitcoin", "比特币", "btc"),
    "ETH": ("ethereum", "以太坊", "eth"),
    "SOL": ("solana", "索拉纳", "sol"),
    "BNB": ("bnb", "binance coin", "币安币"),
    "XRP": ("ripple", "瑞波", "xrp"),
    "DOGE": ("dogecoin", "狗狗币", "doge"),
    "ADA": ("cardano", "艾达", "ada"),
    "LINK": ("chainlink", "link"),
    "AVAX": ("avalanche", "avax"),
    "SUI": ("sui",),
    "TRX": ("tron", "trx"),
    "LTC": ("litecoin", "ltc"),
    "ARB": ("arbitrum", "arb"),
    "OP": ("optimism", "op"),
    "PEPE": ("pepe",),
    "WLD": ("worldcoin", "wld"),
}

TOKEN_RE = re.compile(r"[$#]([A-Za-z][A-Za-z0-9]{1,14})")
UPPER_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")


def dedupe_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _is_ascii_term(term: str) -> bool:
    return all(ord(char) < 128 for char in term)


@lru_cache(maxsize=512)
def _term_boundary_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")


def term_matches_text(text: str, term: str) -> bool:
    normalized_term = str(term or "").strip().lower()
    if not normalized_term:
        return False
    lowered = str(text or "").lower()
    if not lowered:
        return False
    if _is_ascii_term(normalized_term):
        return bool(_term_boundary_pattern(normalized_term).search(lowered))
    return normalized_term in lowered


def build_search_terms(*values: str | None) -> list[str]:
    terms: list[str] = []
    for value in values:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        terms.append(raw)
        compact = raw.replace("-", " ").replace("_", " ")
        if compact != raw:
            terms.append(compact)
        symbol = raw.upper()
        for alias in SYMBOL_ALIASES.get(symbol, ()):
            terms.append(alias.lower())
    return dedupe_terms(terms)


def extract_symbols_from_text(
    title: str,
    content: str | None = None,
    *,
    token_stopwords: set[str] | None = None,
) -> list[str]:
    raw_text = " ".join(part for part in (title, content or "") if part).strip()
    if not raw_text:
        return []
    lowered = raw_text.lower()
    found: list[str] = []
    for symbol, aliases in SYMBOL_ALIASES.items():
        if any(term_matches_text(lowered, alias) for alias in aliases):
            found.append(symbol)
    stopwords = token_stopwords or set()
    for candidate in TOKEN_RE.findall(raw_text):
        token = candidate.upper()
        if token not in stopwords:
            found.append(token)
    for candidate in UPPER_TOKEN_RE.findall(raw_text):
        token = candidate.upper()
        if token in stopwords:
            continue
        if token in SYMBOL_ALIASES or 2 <= len(token) <= 6:
            found.append(token)
    return dedupe_terms(found)


def item_matches_terms(item: dict[str, Any], terms: list[str], *, text_keys: tuple[str, ...] = ("title", "summary", "excerpt", "content")) -> bool:
    if not terms:
        return False
    item_symbols = [str(value or "").upper() for value in item.get("coins") or [] if str(value or "").strip()]
    for term in terms:
        if str(term or "").upper() in item_symbols:
            return True
    text = " ".join(str(item.get(key) or "") for key in text_keys).lower()
    return any(term_matches_text(text, term) for term in terms)
