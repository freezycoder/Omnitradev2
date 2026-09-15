from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from config.form13f import TAXONOMY_VERSION


def _cik(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits.zfill(10)


def _cik_map(rows: Mapping[str, str]) -> MappingProxyType[str, str]:
    return MappingProxyType({_cik(cik): name for cik, name in rows.items()})


# Frozen 2026-09-15, before evaluation. Named lists are identity/style labels,
# not return-tuned. Passive/index advisers are excluded from "notable" and are
# used only for the pre-registered ETF/index churn filter.

NAMED_ACTIVIST_MANAGERS = _cik_map(
    {
        "0000921669": "ICAHN CARL C",
        "0001336528": "PERSHING SQUARE CAPITAL MANAGEMENT, L.P.",
        "0001040273": "THIRD POINT LLC",
        "0001138995": "VALUEACT CAPITAL MANAGEMENT, L.P.",
        "0001366410": "STARBOARD VALUE LP",
        "0001345471": "TRIAN FUND MANAGEMENT, L.P.",
        "0001159159": "JANA PARTNERS LLC",
        "0001559771": "ENGAGED CAPITAL LLC",
        "0001647251": "TCI FUND MANAGEMENT LTD",
        "0001791786": "ELLIOTT INVESTMENT MANAGEMENT L.P.",
        "0001048445": "ELLIOTT ASSOCIATES, L.P.",
        "0001061768": "BAUPOST GROUP LLC/MA",
        "0001029160": "SOROS FUND MANAGEMENT LLC",
        "0001079114": "GREENLIGHT CAPITAL INC",
        "0001396440": "PAULSON & CO. INC.",
        "0001013797": "MAVERICK CAPITAL LTD",
        "0001167483": "TIGER GLOBAL MANAGEMENT LLC",
        "0001061164": "LONE PINE CAPITAL LLC",
        "0001103804": "VIKING GLOBAL INVESTORS LP",
        "0001536411": "COATUE MANAGEMENT LLC",
    }
)

NAMED_QUANT_OR_HF_MANAGERS = _cik_map(
    {
        "0001037389": "RENAISSANCE TECHNOLOGIES LLC",
        "0001423053": "CITADEL ADVISORS LLC",
        "0001179392": "TWO SIGMA INVESTMENTS, LP",
        "0001009207": "D. E. SHAW & CO., INC.",
        "0001273087": "MILLENNIUM MANAGEMENT LLC",
        "0001603466": "POINT72 ASSET MANAGEMENT, L.P.",
        "0001167557": "AQR CAPITAL MANAGEMENT LLC",
        "0001350695": "BRIDGEWATER ASSOCIATES, LP",
        "0001006438": "APPALOOSA LP",
        "0001067983": "BERKSHIRE HATHAWAY INC",
        "0001535392": "DUQUESNE FAMILY OFFICE LLC",
        "0001541617": "SOROBAN CAPITAL PARTNERS LP",
        "0001410882": "MATRIX CAPITAL MANAGEMENT COMPANY, LP",
    }
)

PASSIVE_INDEX_MANAGERS = _cik_map(
    {
        "0000102909": "VANGUARD GROUP INC",
        "0001364742": "BLACKROCK INC.",
        "0001086364": "BLACKROCK FUND ADVISORS",
        "0001001085": "BLACKROCK INSTITUTIONAL TRUST COMPANY, N.A.",
        "0000093751": "STATE STREET CORP",
        "0001299709": "GEODE CAPITAL MANAGEMENT, LLC",
        "0000895421": "INVESCO ADVISERS, INC.",
        "0000914208": "INVESCO LTD",
        "0000073124": "NORTHERN TRUST CORP",
        "0000070858": "BANK OF NEW YORK MELLON CORP",
        "0000313352": "CHARLES SCHWAB CORP",
        "0000315066": "FMR LLC",
    }
)

NAMED_NOTABLE_MANAGERS = MappingProxyType(
    {**dict(NAMED_ACTIVIST_MANAGERS), **dict(NAMED_QUANT_OR_HF_MANAGERS)}
)

# 8-character CUSIP stems, frozen with taxonomy v1. Issuer check-digits vary.
CUSIP8_TO_TICKER = MappingProxyType(
    {
        "03783310": "AAPL",
        "59491810": "MSFT",
        "67066G10": "NVDA",
        "02313510": "AMZN",
        "02079K30": "GOOGL",
        "02079K10": "GOOG",
        "30303M10": "META",
        "11135F10": "AVGO",
        "00790310": "AMD",
        "64110L10": "NFLX",
        "68389X10": "ORCL",
        "79466L30": "CRM",
        "46625H10": "JPM",
        "92826C83": "V",
        "53245710": "LLY",
        "00287Y10": "ABBV",
        "91324P10": "UNH",
        "30231G10": "XOM",
        "22160K10": "COST",
        "93114210": "WMT",
        "90353T10": "UBER",
        "87403910": "TSM",
        "N0705921": "ASML",
        "67010020": "NVO",
        "78025910": "SHEL",
        "80305420": "SAP",
        "01609W10": "BABA",
        "83569930": "SONY",
        "89160T10": "TM",
        "78008710": "RY",
        "82509L10": "SHOP",
        "58733R10": "MELI",
        "72230410": "PDD",
        "90476710": "UL",
        "75953010": "RELX",
        "78462F10": "SPY",
        "46090E10": "QQQ",
        "46428765": "IWM",
        "92290836": "VTI",
        "92189F10": "VOO",
    }
)

ISSUER_NAME_TO_TICKER = MappingProxyType(
    {
        "APPLE INC": "AAPL",
        "MICROSOFT CORP": "MSFT",
        "NVIDIA CORPORATION": "NVDA",
        "NVIDIA CORP": "NVDA",
        "AMAZON COM INC": "AMZN",
        "ALPHABET INC": "GOOGL",
        "META PLATFORMS INC": "META",
        "BROADCOM INC": "AVGO",
        "ADVANCED MICRO DEVICES INC": "AMD",
        "NETFLIX INC": "NFLX",
        "ORACLE CORP": "ORCL",
        "SALESFORCE INC": "CRM",
        "JPMORGAN CHASE & CO": "JPM",
        "VISA INC": "V",
        "ELI LILLY & CO": "LLY",
        "ABBVIE INC": "ABBV",
        "UNITEDHEALTH GROUP INC": "UNH",
        "EXXON MOBIL CORP": "XOM",
        "COSTCO WHOLESALE CORP": "COST",
        "WALMART INC": "WMT",
        "UBER TECHNOLOGIES INC": "UBER",
    }
)


def normalize_cik(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    return digits.zfill(10)


def normalize_cusip8(value: str | None) -> str | None:
    if not value:
        return None
    stem = str(value).strip().upper().replace(" ", "")
    if len(stem) < 8:
        return None
    return stem[:8]


def taxonomy_payload() -> dict[str, object]:
    return {
        "version": TAXONOMY_VERSION,
        "frozen_before_eval": True,
        "named_activist_ciks": dict(NAMED_ACTIVIST_MANAGERS),
        "named_quant_or_hf_ciks": dict(NAMED_QUANT_OR_HF_MANAGERS),
        "passive_index_ciks": dict(PASSIVE_INDEX_MANAGERS),
        "cusip8_to_ticker": dict(CUSIP8_TO_TICKER),
        "selection_rule": (
            "Notable if named activist/quant/HF CIK or prior/same-filing 13F AUM "
            "meets the frozen floor, unless the CIK is on the passive/index exclusion list."
        ),
    }
