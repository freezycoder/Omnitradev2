# FINRA Short Sale Volume — Terms of Use review

**Status:** recorded for shadow research only. **Do not ship a commercial path.**
**Review date:** 2026-09-14
**Approver required for any shipping change:** Alvaro

## Source

- Catalog: [FINRA Short Sale Volume](https://www.finra.org/finra-data/browse-catalog/short-sale-volume)
- Daily file verified 2026-09-11: `https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260911.txt`
- Schema: `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`
- Adapter note: [finance-query FINRA provider](https://verdenroz.github.io/finance-query/library/providers/finra/)

## What this is

Daily aggregated **short sale volume** by security for FINRA facilities (TRF/ADF/ORF), published as Reg SHO daily files such as `CNMSshvol`.

## What this is not

- Not bi-monthly **short interest**.
- Not a consolidated tape of exchange + off-exchange short volume.
- Exchange short volume is **absent**. Provenance is permanently `FINRA_OFF_EXCHANGE`.

## Use class

FINRA states the short-sale volume files are **free for non-commercial use**. This repository uses them only as a **shadow research ingest**:

- no live recommendation changes
- no commercial redistribution of the files
- no merge to a shipping/commercial path without Alvaro approval and a commercial agreement if that use is intended

If commercial use is later required, **block merge** until an agreement exists and Alvaro records approval. `legal_gate.commercial_use_allowed` stays `false` and `shipping_allowed` stays `false` until then.

## OmniTrade implementation constraints

- Feature family metadata is `short_volume`, never `short_interest`.
- Applied impact is always `0`.
- Activation is never automatic.
- Combining this ratio with short interest is not pre-registered and is not implemented.
