from __future__ import annotations

from providers.events.form4_xml import classify_form4_from_transactions, parse_form4_xml


FORM4_XML = b"""
<ownershipDocument>
  <issuer>
    <issuerCik>320193</issuerCik>
    <issuerName>Apple Inc</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>000123</rptOwnerCik>
      <rptOwnerName>COOK TIMOTHY</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>250</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes>
    <footnote id="F1">Routine award. Not a 10b5-1 plan.</footnote>
  </footnotes>
</ownershipDocument>
"""


def test_form4_xml_keeps_open_market_purchase_and_drops_award():
    rows = parse_form4_xml(FORM4_XML, accession_number="0001", filed_at="2026-07-25")
    assert len(rows) == 1
    assert rows[0].transaction_code == "P"
    assert rows[0].ticker == "AAPL"
    assert rows[0].owner_cik == "000123"
    assert rows[0].value_usd == 250_000
    assert rows[0].is_10b5_1 is False
    assert rows[0].source == "edgar_form4_xml"


def test_form4_classifier_matches_live_insider_purchase_summary():
    rows = parse_form4_xml(FORM4_XML, accession_number="0001", filed_at="2026-07-25")
    category, direction, importance, summary, value = classify_form4_from_transactions(rows)
    assert category == "insider_purchase"
    assert direction == 1
    assert importance == 3
    assert "insider purchase" in summary.lower()
    assert value == 250_000
