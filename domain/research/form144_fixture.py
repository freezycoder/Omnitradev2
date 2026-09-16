from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from domain.research.form144_match_study import PricePanel, evaluate_form144_experiment
from providers.events.form144_models import Form4Sale, ProposedSaleNotice


ISSUER_CIK = "0000320193"
TICKER = "AAA"
NOISE_TICKER = "BBB"
NOISE_ISSUER = "0000999999"
AFFILIATES = (
    ("0001000001", "Affiliate One"),
    ("0001000002", "Affiliate Two"),
    ("0001000003", "Affiliate Three"),
)
NOISE_FILER = ("0001000009", "Low Intent")


def _notice(
    *,
    accession: str,
    filed_at: str,
    filer_cik: str,
    filer_name: str,
    units: float,
    ticker: str = TICKER,
    issuer_cik: str = ISSUER_CIK,
    prior_3m: float | None = 0.0,
    approx_sale_date: str | None = None,
) -> ProposedSaleNotice:
    return ProposedSaleNotice(
        accession_number=accession,
        ticker=ticker,
        issuer_cik=issuer_cik,
        issuer_name="Fixture Issuer",
        filer_cik=filer_cik,
        filer_name=filer_name,
        relationship="Officer",
        filed_at=filed_at,
        approx_sale_date=approx_sale_date or filed_at,
        proposed_units=units,
        aggregate_market_value=units * 10.0,
        broker="Fixture Broker",
        prior_3m_units=prior_3m,
        prior_3m_proceeds=None,
        securities_class="Common",
        source="fixture",
    )


def _sale(
    *,
    accession: str,
    event_date: str,
    filer_cik: str,
    filer_name: str,
    shares: float,
    ticker: str = TICKER,
    issuer_cik: str = ISSUER_CIK,
) -> Form4Sale:
    return Form4Sale(
        accession_number=accession,
        ticker=ticker,
        issuer_cik=issuer_cik,
        filer_cik=filer_cik,
        filer_name=filer_name,
        filed_at=event_date,
        transaction_date=event_date,
        transaction_code="S",
        acquired_disposed="D",
        shares=shares,
        value_usd=shares * 10.0,
        source="fixture",
        is_derivative=False,
    )


def history_frame(start: date, sessions: int, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=sessions)
    closes = [start_price for _ in range(sessions)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": [1_000_000] * sessions,
        },
        index=dates,
    )


def _week_dates(count: int = 18) -> list[date]:
    start = date(2023, 1, 3)
    return [start + timedelta(days=7 * index) for index in range(count)]


def aligned_form144_inputs(
    *,
    mode: str = "lead",
) -> tuple[list[ProposedSaleNotice], list[Form4Sale], PricePanel]:
    """Synthetic books for CI.

    lead: unmatched 144 clusters, Form 4 sales T-window later (calibration lift).
    same_day: 144 and Form 4 print together (infra radar, no nested lead).
    unmatched: 144s never execute (match-rate fail).
    """

    notices: list[ProposedSaleNotice] = []
    sales: list[Form4Sale] = []
    for index, filed in enumerate(_week_dates()):
        filed_text = filed.isoformat()
        if mode == "unmatched":
            cik, name = NOISE_FILER
            notices.append(
                _notice(
                    accession=f"144-noise-{index}",
                    filed_at=filed_text,
                    filer_cik=cik,
                    filer_name=name,
                    units=100.0,
                    ticker=NOISE_TICKER,
                    issuer_cik=NOISE_ISSUER,
                )
            )
            continue
        for affiliate_index, (cik, name) in enumerate(AFFILIATES):
            notices.append(
                _notice(
                    accession=f"144-{index}-{affiliate_index}",
                    filed_at=filed_text,
                    filer_cik=cik,
                    filer_name=name,
                    units=50_000.0,
                    prior_3m=1_000.0,
                )
            )
            event = filed if mode == "same_day" else filed + timedelta(days=3)
            sales.append(
                _sale(
                    accession=f"4-{index}-{affiliate_index}",
                    event_date=event.isoformat(),
                    filer_cik=cik,
                    filer_name=name,
                    shares=50_000.0,
                )
            )
        if mode == "lead":
            cik, name = NOISE_FILER
            notices.append(
                _notice(
                    accession=f"144-noise-{index}",
                    filed_at=filed_text,
                    filer_cik=cik,
                    filer_name=name,
                    units=100.0,
                    ticker=NOISE_TICKER,
                    issuer_cik=NOISE_ISSUER,
                )
            )
    frame = history_frame(date(2022, 12, 1), sessions=400)
    close = pd.to_numeric(frame["Close"], errors="coerce")
    close.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    series = close.dropna().sort_index()
    panel = PricePanel(stock={TICKER: series, NOISE_TICKER: series})
    return notices, sales, panel


def evaluate_aligned_fixture(*, mode: str = "lead") -> dict:
    notices, sales, panel = aligned_form144_inputs(mode=mode)
    return evaluate_form144_experiment(
        notices,
        sales,
        panel=panel,
        form4_store_meta={
            "present": False,
            "path": None,
            "source": "fixture",
            "sale_count": len(sales),
            "notes": "CI fixture; Form 4 KEEP store not required.",
        },
    )


FORM144_XML_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership144">
  <headerData>
    <submissionType>144</submissionType>
    <filerInfo>
      <filer>
        <filerCredentials>
          <cik>0001000001</cik>
        </filerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <issuerInfo>
      <issuerCik>0000320193</issuerCik>
      <issuerName>Fixture Issuer</issuerName>
      <issuerTradingSymbol>AAA</issuerTradingSymbol>
      <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Affiliate One</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
      <relationshipToIssuer>Officer</relationshipToIssuer>
    </issuerInfo>
    <securitiesInformation>
      <securitiesToBeSold>
        <securityClassTitle>Common Stock</securityClassTitle>
        <brokerOrMarketMaker>
          <name>Goldman Sachs &amp; Co. LLC</name>
        </brokerOrMarketMaker>
        <numberOfSharesOrUnitsToBeSold>12000</numberOfSharesOrUnitsToBeSold>
        <aggregateMarketValue>1800000</aggregateMarketValue>
        <approxDateOfSale>03/15/2023</approxDateOfSale>
      </securitiesToBeSold>
    </securitiesInformation>
    <securitiesSoldInPast3Months>
      <amountOfSecuritiesSold>500</amountOfSecuritiesSold>
      <grossProceeds>75000</grossProceeds>
    </securitiesSoldInPast3Months>
  </formData>
</edgarSubmission>
"""

FORM4_SALE_XML_FIXTURE = b"""
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerTradingSymbol>AAA</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001000001</rptOwnerCik>
      <rptOwnerName>Affiliate One</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2023-03-18</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>12000</value></transactionShares>
        <transactionPricePerShare><value>150</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""
