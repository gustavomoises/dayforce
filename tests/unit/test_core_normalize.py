"""Normalization of codes, tags, free text and queries."""

import pytest

from app.core.normalize import normalize_code, normalize_query, normalize_tags, normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Payments-API ", "payments-api"),
        ("PROD", "prod"),
        ("inc-00001\n", "inc-00001"),
        ("Auth \t  Service", "auth service"),
    ],
)
def test_codes_are_lowercased_trimmed_and_collapsed(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


def test_tags_are_normalized_deduplicated_and_sorted() -> None:
    assert normalize_tags([" Pool", "db", "POOL", "  ", "Auth"]) == ("auth", "db", "pool")


def test_no_tags_give_an_empty_tuple() -> None:
    assert normalize_tags([]) == ()


def test_free_text_keeps_case_and_punctuation() -> None:
    assert normalize_text("  Pool EXHAUSTED: retry!  ") == "Pool EXHAUSTED: retry!"


def test_query_collapses_whitespace_and_keeps_case() -> None:
    assert normalize_query("  Pool \n  Exhausted  ") == "Pool Exhausted"
