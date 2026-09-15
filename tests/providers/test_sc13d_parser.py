from __future__ import annotations

from providers.events.sc13d_parser import parse_percent_of_class, parse_sc13d_document, plain_text


SAMPLE_13D = """
<HTML>
<BODY>
SCHEDULE 13D
CUSIP No. 037833100
NAME OF REPORTING PERSONS
Starboard Value LP
CIK 0001547643
(Name of Issuer)
Apple Inc.

Item 4. Purpose of Transaction
The Reporting Person acquired the securities to seek board representation
and may nominate directors. The Reporting Person intends to pursue strategic
alternatives to maximize shareholder value.
This statement converts this Schedule 13G into a Schedule 13D because the
Reporting Person is no longer eligible to file on Schedule 13G.

Item 5. Interest in Securities of the Issuer
The Reporting Person beneficially owns 6.4% of the outstanding shares of common stock.
Percent of Class Represented by Amount in Row (11) 6.4%

Item 6. Contracts, Arrangements, Understandings or Relationships With Respect to Securities of the Issuer
None.
</BODY>
</HTML>
"""


def test_plain_text_strips_html():
    assert "SCHEDULE 13D" in plain_text(SAMPLE_13D)
    assert "<HTML>" not in plain_text(SAMPLE_13D)


def test_parse_purpose_percent_and_conversion():
    parsed = parse_sc13d_document(SAMPLE_13D)
    assert "board representation" in parsed.purpose_text.lower()
    assert parsed.percent_of_class == 6.4
    assert parsed.reporting_cik == "0001547643"
    assert parsed.conversion_text_flag is True
    assert parsed.reporting_name is not None
    assert "Starboard" in parsed.reporting_name


def test_percent_of_class_from_item_5():
    text = "Item 5. Interest in Securities of the Issuer The fund beneficially owns 11.2% of the outstanding shares. Item 6."
    assert parse_percent_of_class(text) == 11.2
