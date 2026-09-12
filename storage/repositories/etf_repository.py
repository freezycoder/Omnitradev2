from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from config.etf import ETF_CACHE_TTL_HOURS, ETF_HOLDINGS_CACHE_TTL_HOURS, EtfUniverseFilters
from domain.etf.models import AllocationSlice, EtfHolding, EtfHoldingsSnapshot, EtfProfile, as_fraction
from domain.etf.overlap import holding_key
from storage.sqlite import bootstrap_database, connection_scope


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_fresh(updated_at: str | None, ttl_hours: float) -> bool:
    parsed = _parse_dt(updated_at)
    if parsed is None:
        return False
    return datetime.now(UTC) - parsed <= timedelta(hours=ttl_hours)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _allocations_from_json(raw: str | None) -> tuple[AllocationSlice, ...]:
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    slices: list[AllocationSlice] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        weight = item.get("weight")
        if not label or weight is None:
            continue
        slices.append(AllocationSlice(label=label, weight=float(weight), source=item.get("source")))
    return tuple(slices)


def _profile_from_row(row: Any) -> EtfProfile:
    unavailable = ()
    if row["unavailable_fields_json"]:
        try:
            unavailable = tuple(json.loads(row["unavailable_fields_json"]))
        except json.JSONDecodeError:
            unavailable = ()
    return EtfProfile(
        ticker=row["ticker"],
        name=row["name"],
        issuer=row["issuer"],
        asset_class=row["asset_class"],
        category=row["category"],
        description=row["description"],
        expense_ratio=as_fraction(row["expense_ratio"]),
        aum=row["aum"],
        average_volume=row["average_volume"],
        dividend_yield=as_fraction(row["dividend_yield"], percent_if_above=0.2),
        inception_date=row["inception_date"],
        holdings_count=row["holdings_count"],
        geographic_exposure=_allocations_from_json(row["geographic_exposure_json"]),
        sector_exposure=_allocations_from_json(row["sector_exposure_json"]),
        source=row["source"],
        quote_type=row["quote_type"],
        updated_at=row["updated_at"],
        unavailable_fields=unavailable,
    )


def _holding_from_row(row: Any) -> EtfHolding:
    return EtfHolding(
        etf_ticker=row["etf_ticker"],
        holding_ticker=row["holding_ticker"],
        holding_name=row["holding_name"],
        weight=row["weight"],
        shares=row["shares"],
        as_of=row["as_of"],
        source=row["source"],
    )


class EtfRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        bootstrap_database(self._db_path)

    def upsert_profile(self, profile: EtfProfile) -> None:
        payload = {
            "ticker": profile.ticker.upper().strip(),
            "name": profile.name,
            "issuer": profile.issuer,
            "asset_class": profile.asset_class,
            "category": profile.category,
            "description": profile.description,
            "expense_ratio": profile.expense_ratio,
            "aum": profile.aum,
            "average_volume": profile.average_volume,
            "dividend_yield": profile.dividend_yield,
            "inception_date": profile.inception_date,
            "holdings_count": profile.holdings_count,
            "geographic_exposure_json": _json_dumps([item.__dict__ for item in profile.geographic_exposure]),
            "sector_exposure_json": _json_dumps([item.__dict__ for item in profile.sector_exposure]),
            "quote_type": profile.quote_type,
            "source": profile.source,
            "unavailable_fields_json": _json_dumps(list(profile.unavailable_fields)),
            "updated_at": profile.updated_at,
        }
        query = """
            INSERT INTO etfs (
                ticker, name, issuer, asset_class, category, description,
                expense_ratio, aum, average_volume, dividend_yield, inception_date,
                holdings_count, geographic_exposure_json, sector_exposure_json,
                quote_type, source, unavailable_fields_json, updated_at
            ) VALUES (
                :ticker, :name, :issuer, :asset_class, :category, :description,
                :expense_ratio, :aum, :average_volume, :dividend_yield, :inception_date,
                :holdings_count, :geographic_exposure_json, :sector_exposure_json,
                :quote_type, :source, :unavailable_fields_json, :updated_at
            )
            ON CONFLICT(ticker) DO UPDATE SET
                name = excluded.name,
                issuer = excluded.issuer,
                asset_class = excluded.asset_class,
                category = excluded.category,
                description = excluded.description,
                expense_ratio = excluded.expense_ratio,
                aum = excluded.aum,
                average_volume = excluded.average_volume,
                dividend_yield = excluded.dividend_yield,
                inception_date = excluded.inception_date,
                holdings_count = excluded.holdings_count,
                geographic_exposure_json = excluded.geographic_exposure_json,
                sector_exposure_json = excluded.sector_exposure_json,
                quote_type = excluded.quote_type,
                source = excluded.source,
                unavailable_fields_json = excluded.unavailable_fields_json,
                updated_at = excluded.updated_at
        """
        with connection_scope(self._db_path) as connection:
            connection.execute(query, payload)

    def get_profile(self, ticker: str, *, require_fresh: bool = False) -> EtfProfile | None:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM etfs WHERE ticker = ? LIMIT 1",
                (ticker.upper().strip(),),
            ).fetchone()
        if row is None:
            return None
        profile = _profile_from_row(row)
        if require_fresh and not _is_fresh(profile.updated_at, ETF_CACHE_TTL_HOURS):
            return None
        return profile

    def list_profiles(
        self,
        filters: EtfUniverseFilters | None = None,
        *,
        tickers: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[EtfProfile]:
        query = "SELECT * FROM etfs WHERE 1 = 1"
        params: list[object] = []
        if tickers:
            placeholders = ", ".join("?" for _ in tickers)
            query += f" AND ticker IN ({placeholders})"
            params.extend(ticker.upper().strip() for ticker in tickers)
        filters = filters or EtfUniverseFilters()
        if filters.ticker:
            query += " AND ticker LIKE ?"
            params.append(f"%{filters.ticker.upper().strip()}%")
        if filters.name:
            query += " AND LOWER(COALESCE(name, '')) LIKE ?"
            params.append(f"%{filters.name.lower().strip()}%")
        if filters.issuer:
            query += " AND LOWER(COALESCE(issuer, '')) LIKE ?"
            params.append(f"%{filters.issuer.lower().strip()}%")
        if filters.asset_class:
            query += " AND LOWER(COALESCE(asset_class, '')) LIKE ?"
            params.append(f"%{filters.asset_class.lower().strip()}%")
        if filters.category:
            query += " AND LOWER(COALESCE(category, '')) LIKE ?"
            params.append(f"%{filters.category.lower().strip()}%")
        if filters.max_expense_ratio is not None:
            query += " AND expense_ratio IS NOT NULL AND expense_ratio <= ?"
            params.append(filters.max_expense_ratio)
        if filters.min_aum is not None:
            query += " AND aum IS NOT NULL AND aum >= ?"
            params.append(filters.min_aum)
        if filters.min_average_volume is not None:
            query += " AND average_volume IS NOT NULL AND average_volume >= ?"
            params.append(filters.min_average_volume)
        if filters.min_dividend_yield is not None:
            query += " AND dividend_yield IS NOT NULL AND dividend_yield >= ?"
            params.append(filters.min_dividend_yield)
        if filters.sector:
            query += " AND LOWER(COALESCE(sector_exposure_json, '')) LIKE ?"
            params.append(f"%{filters.sector.lower().strip()}%")
        if filters.geography:
            query += " AND LOWER(COALESCE(geographic_exposure_json, '')) LIKE ?"
            params.append(f"%{filters.geography.lower().strip()}%")
        query += " ORDER BY ticker"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_profile_from_row(row) for row in rows]

    def replace_holdings(self, snapshot: EtfHoldingsSnapshot) -> None:
        updated_at = snapshot.captured_at
        with connection_scope(self._db_path) as connection:
            connection.execute("DELETE FROM etf_holdings WHERE etf_ticker = ?", (snapshot.etf_ticker,))
            for holding in snapshot.holdings:
                key = holding_key(holding)
                if key is None:
                    continue
                connection.execute(
                    """
                    INSERT INTO etf_holdings (
                        etf_ticker, holding_key, holding_ticker, holding_name, weight, shares, as_of, source, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.etf_ticker,
                        key,
                        holding.holding_ticker,
                        holding.holding_name,
                        holding.weight,
                        holding.shares,
                        holding.as_of,
                        holding.source or snapshot.source,
                        updated_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO etf_holdings_snapshots (
                    snapshot_id, etf_ticker, captured_at, source, holdings_json,
                    sector_allocation_json, geographic_allocation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    snapshot.etf_ticker,
                    snapshot.captured_at,
                    snapshot.source,
                    _json_dumps([holding.to_dict() for holding in snapshot.holdings]),
                    _json_dumps([item.__dict__ for item in snapshot.sector_allocation]),
                    _json_dumps([item.__dict__ for item in snapshot.geographic_allocation]),
                ),
            )

    def get_holdings(self, ticker: str, *, require_fresh: bool = False) -> EtfHoldingsSnapshot | None:
        etf_ticker = ticker.upper().strip()
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM etf_holdings WHERE etf_ticker = ? ORDER BY weight DESC",
                (etf_ticker,),
            ).fetchall()
            snapshot_row = connection.execute(
                """
                SELECT * FROM etf_holdings_snapshots
                WHERE etf_ticker = ?
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (etf_ticker,),
            ).fetchone()
        if not rows and snapshot_row is None:
            return None
        captured_at = snapshot_row["captured_at"] if snapshot_row else (rows[0]["updated_at"] if rows else None)
        if require_fresh and not _is_fresh(captured_at, ETF_HOLDINGS_CACHE_TTL_HOURS):
            return None
        holdings = tuple(_holding_from_row(row) for row in rows)
        sector = _allocations_from_json(snapshot_row["sector_allocation_json"] if snapshot_row else None)
        geography = _allocations_from_json(snapshot_row["geographic_allocation_json"] if snapshot_row else None)
        return EtfHoldingsSnapshot(
            etf_ticker=etf_ticker,
            captured_at=captured_at or "",
            source=snapshot_row["source"] if snapshot_row else (rows[0]["source"] if rows else None),
            holdings=holdings,
            sector_allocation=sector,
            geographic_allocation=geography,
        )

    def list_holdings_for_stock(self, stock_ticker: str) -> list[EtfHolding]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM etf_holdings
                WHERE holding_ticker = ?
                ORDER BY weight DESC
                """,
                (stock_ticker.upper().strip(),),
            ).fetchall()
        return [_holding_from_row(row) for row in rows]

    def list_all_holdings(self, etf_tickers: list[str] | None = None) -> list[EtfHolding]:
        query = "SELECT * FROM etf_holdings WHERE 1 = 1"
        params: list[object] = []
        if etf_tickers:
            placeholders = ", ".join("?" for _ in etf_tickers)
            query += f" AND etf_ticker IN ({placeholders})"
            params.extend(ticker.upper().strip() for ticker in etf_tickers)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_holding_from_row(row) for row in rows]


__all__ = ["EtfRepository"]
