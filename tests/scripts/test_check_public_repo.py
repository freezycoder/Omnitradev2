from __future__ import annotations

from scripts.check_public_repo import SECRET_PATTERNS, _scan_content


def test_github_token_pattern_detects_real_tokens():
    pattern = SECRET_PATTERNS["GitHub token"]
    sample_hash = b"0123456789abcdefghijklmnopqrstuvwxyz"
    real_tokens = [
        b"gh" + b"p_" + sample_hash,
        b"gh" + b"o_" + sample_hash,
        b"gh" + b"u_" + sample_hash,
        b"gh" + b"s_" + sample_hash,
        b"gh" + b"r_" + sample_hash,
        b"github_" + b"pat_" + b"11AAAAAAA_" + sample_hash + sample_hash + b"0123",
    ]
    for token in real_tokens:
        assert pattern.search(token) is not None, f"Failed to detect {token}"


def test_github_token_pattern_ignores_snake_case_words_ending_in_ghs():
    pattern = SECRET_PATTERNS["GitHub token"]
    false_positives = [
        b"def test_new_highs_are_secondary_and_not_part_of_the_gate():",
        b"throughs_and_peaks_in_the_multi_period_cycle = 42",
        b"weighed_highs_across_the_universe_lookback = [1, 2, 3]",
        b"sighs_of_relief_when_all_checks_finally_pass = True",
    ]
    for non_token in false_positives:
        assert pattern.search(non_token) is None, f"Falsely matched {non_token}"


def test_scan_content_reports_github_token_only_when_present():
    safe_code = b"def test_new_highs_are_secondary_and_not_part_of_the_gate():\n    return True\n"
    assert _scan_content("tests/foo.py", safe_code) == []

    unsafe_code = b"GITHUB_TOKEN = \"" + b"gh" + b"p_" + b"0123456789abcdefghijklmnopqrstuvwxyz\"\n"
    findings = _scan_content("config/api.py", unsafe_code)
    assert any("GitHub token" in finding for finding in findings)
