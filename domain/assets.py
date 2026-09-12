from __future__ import annotations

from enum import StrEnum


class AssetType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    CRYPTO = "CRYPTO"
    FUTURE = "FUTURE"


def normalize_asset_type(value: str | None, default: AssetType = AssetType.STOCK) -> AssetType:
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().upper()
    try:
        return AssetType(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported asset_type: {value}") from exc


__all__ = ["AssetType", "normalize_asset_type"]
