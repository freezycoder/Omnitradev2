"""Kronos forecasting sidecar (Python 3.11 + PyTorch).

Loads the Kronos tokenizer/model once and serves forecasts over HTTP so the
OmniTrade API can stay free of heavy ML dependencies.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


MODEL_ID = os.environ.get("KRONOS_MODEL_ID", "NeoQuasar/Kronos-small")
TOKENIZER_ID = os.environ.get("KRONOS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
DEVICE = os.environ.get("KRONOS_DEVICE", "cpu")
MAX_CONTEXT = int(os.environ.get("KRONOS_MAX_CONTEXT", "512"))
REPO_PATH = os.environ.get("KRONOS_REPO_PATH", "").strip()

if REPO_PATH and REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

app = FastAPI(title="Kronos Forecast Service", version="1.0.0")

_predictor: Any | None = None


class Candle(BaseModel):
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


class PredictRequest(BaseModel):
    candles: list[Candle] = Field(min_length=32)
    future_timestamps: list[str] = Field(min_length=1)
    horizon: int = Field(default=30, ge=1, le=240)
    T: float = Field(default=1.0, gt=0, le=2.0)
    top_p: float = Field(default=0.9, gt=0, le=1.0)
    sample_count: int = Field(default=20, ge=1, le=64)


def get_predictor() -> Any:
    global _predictor
    if _predictor is None:
        from model import Kronos, KronosPredictor, KronosTokenizer

        tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
        model = Kronos.from_pretrained(MODEL_ID)
        _predictor = KronosPredictor(model, tokenizer, device=DEVICE, max_context=MAX_CONTEXT)
    return _predictor


@app.on_event("startup")
def _warm_model() -> None:
    if os.environ.get("KRONOS_EAGER_LOAD", "true").strip().lower() in {"1", "true", "yes"}:
        try:
            get_predictor()
        except Exception as exc:  # keep /health reachable so the caller sees the reason
            print(f"[kronos] model load failed at startup: {exc}", flush=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_ID,
        "tokenizer": TOKENIZER_ID,
        "device": DEVICE,
        "max_context": MAX_CONTEXT,
        "loaded": _predictor is not None,
    }


def _quantile_bands(paths: list[pd.DataFrame]) -> dict[str, list[float]]:
    closes = np.stack([frame["close"].to_numpy(dtype=float) for frame in paths])
    return {
        "p10": np.percentile(closes, 10, axis=0).round(6).tolist(),
        "p50": np.percentile(closes, 50, axis=0).round(6).tolist(),
        "p90": np.percentile(closes, 90, axis=0).round(6).tolist(),
    }


@app.post("/predict")
def predict(payload: PredictRequest) -> dict[str, Any]:
    try:
        predictor = get_predictor()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Kronos model unavailable: {exc}") from exc

    history = pd.DataFrame(
        {
            "open": [c.o for c in payload.candles],
            "high": [c.h for c in payload.candles],
            "low": [c.l for c in payload.candles],
            "close": [c.c for c in payload.candles],
            "volume": [c.v for c in payload.candles],
        }
    )
    x_timestamp = pd.to_datetime(pd.Series([c.t for c in payload.candles]))
    y_timestamp = pd.to_datetime(pd.Series(payload.future_timestamps))
    pred_len = len(y_timestamp)

    try:
        mean_path = predictor.predict(
            df=history,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=payload.T,
            top_p=payload.top_p,
            sample_count=payload.sample_count,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Kronos prediction failed: {exc}") from exc

    bands: dict[str, list[float]] | None = None
    if payload.sample_count > 1:
        try:
            samples = [
                predictor.predict(
                    df=history,
                    x_timestamp=x_timestamp,
                    y_timestamp=y_timestamp,
                    pred_len=pred_len,
                    T=payload.T,
                    top_p=payload.top_p,
                    sample_count=1,
                )
                for _ in range(min(payload.sample_count, 12))
            ]
            bands = _quantile_bands(samples)
        except Exception as exc:  # bands are a nicety, never fail the request for them
            print(f"[kronos] band sampling failed: {exc}", flush=True)

    points = [
        {
            "t": pd.Timestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S"),
            "o": float(row.get("open", row["close"])),
            "h": float(row.get("high", row["close"])),
            "l": float(row.get("low", row["close"])),
            "c": float(row["close"]),
            "v": float(row.get("volume", 0.0) or 0.0),
        }
        for timestamp, (_, row) in zip(y_timestamp, mean_path.iterrows(), strict=False)
    ]

    return {
        "model": MODEL_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "points": points,
        "bands": bands,
    }
