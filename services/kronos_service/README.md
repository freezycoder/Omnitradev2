# Kronos forecasting sidecar

Runs the [Kronos](https://github.com/shiyu-coder/Kronos) foundation model
(PyTorch) as a small HTTP service. OmniTrade's API never imports torch — it
only calls this service over HTTP.

## Install (Python 3.11)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git clone https://github.com/shiyu-coder/Kronos /opt/kronos   # provides the `model` package
export KRONOS_REPO_PATH=/opt/kronos
```

## Run

```bash
export KRONOS_MODEL_ID=NeoQuasar/Kronos-small
export KRONOS_TOKENIZER_ID=NeoQuasar/Kronos-Tokenizer-base
export KRONOS_DEVICE=cpu            # or cuda:0
export KRONOS_MAX_CONTEXT=512
uvicorn main:app --host 0.0.0.0 --port 8799
```

Then point the OmniTrade API at it:

```bash
export KRONOS_SERVICE_URL=http://127.0.0.1:8799
export KRONOS_ENABLED=true
```

## Endpoints

- `GET /health` — model id, device, and whether weights are loaded.
- `POST /predict` — body `{ candles: [{t,o,h,l,c,v}], future_timestamps: [...], horizon, T, top_p, sample_count }`;
  returns `{ model, generated_at, points: [{t,o,h,l,c,v}], bands: { p10, p50, p90 } }`.
  Bands are returned when `sample_count > 1`.
