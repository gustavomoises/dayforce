"""Labeled plain text that is embedded for each incident."""

from app.core.embedding_text import embedding_text


def test_fields_are_labeled_in_a_fixed_order() -> None:
    text = embedding_text(" Pool exhausted ", "Connections ran out.", "Raised the pool.")

    assert text == (
        "title: Pool exhausted\ndescription: Connections ran out.\nresolution: Raised the pool."
    )


def test_empty_fields_are_left_out() -> None:
    assert embedding_text("Pool exhausted", "   ", "Raised the pool.") == (
        "title: Pool exhausted\nresolution: Raised the pool."
    )


def test_all_empty_fields_give_empty_text() -> None:
    assert embedding_text("", " ", "") == ""
