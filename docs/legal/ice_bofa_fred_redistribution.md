# ICE BofA / FRED redistribution constraints

Status: research ingest only. This is not a license to productize ICE-branded series.

## What the data is

`BAMLH0A0HYM2` (ICE BofA US High Yield Index Option-Adjusted Spread) and
`BAMLC0A0CM` (ICE BofA US Corporate Index Option-Adjusted Spread) are ICE Data
Indices, LLC series. The Federal Reserve Bank of St. Louis redistributes a
limited public window through FRED and ALFRED.

Starting April 2026, the public FRED series retains about three years of
observations. Deeper history requires ALFRED vintages or a licensed ICE feed.

## What OmniTrade may do in this packet

- Internal, shadow-only ingest for a pre-registered regime-gate experiment.
- Cite series IDs and FRED URLs.
- Compute derived features (level, 20-session change, weekly change, HY−IG gap)
  inside the research harness.

## What OmniTrade may not do without a separate ICE license

- Display ICE-branded OAS prints, charts, or tables in the product UI, public
  API, marketing, or any customer-facing surface.
- Redistribute observation-level ICE values in git, seed data, or screenshots
  shipped with the product.
- Imply that FRED access equals ICE redistribution rights.
- Treat ALFRED vintages as a workaround for ICE display licensing.

## Experiment FAIL path

If the intended surface is a productized ICE-branded display and no ICE
redistribution license exists, the experiment FAILs on legal/redistribution
grounds even if the statistical gate shows lift.

The frozen `credit-gate-v1` recipe is a shadow throttle. `applied_impact` stays
`0`. Live recommendations do not change from this packet.
