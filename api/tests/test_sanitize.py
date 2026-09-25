import pytest

from app.core.sanitize import (
    compose_prompt,
    normalize_handle,
    sanitize_prompt,
    sanitize_search,
)


def test_zero_width_characters_are_stripped() -> None:
    """Invisible characters make two identical-looking prompts hash
    differently, which breaks dedupe and defeats any content filter."""
    assert sanitize_prompt("a​b‌c") == "abc"


def test_control_characters_are_stripped_but_newlines_survive() -> None:
    assert sanitize_prompt("a\x00b\x07c") == "abc"
    assert sanitize_prompt("line one\nline two") == "line one\nline two"


def test_whitespace_is_collapsed() -> None:
    assert sanitize_prompt("  a    b  ") == "a b"
    assert sanitize_prompt("a\n\n\n\n\nb") == "a\n\nb"


def test_nfkc_normalisation() -> None:
    # Fullwidth latin, deliberately: NFKC must fold it to ASCII.
    assert sanitize_prompt("ａｂｃ") == "abc"  # noqa: RUF001


def test_empty_after_normalisation_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        sanitize_prompt("​​​")


def test_prompt_is_truncated() -> None:
    assert len(sanitize_prompt("x" * 5000)) == 2000


def test_handles_are_validated_and_lowercased() -> None:
    assert normalize_handle("  HaNa.K  ") == "hana.k"
    for bad in ["ab", "x" * 33, "has space", "has/slash", "admin", "api"]:
        with pytest.raises(ValueError):
            normalize_handle(bad)


def test_search_normalises_and_caps() -> None:
    assert sanitize_search("  fog\nlight  ") == "fog light"
    assert sanitize_search(None) is None
    assert sanitize_search("   ") is None
    assert len(sanitize_search("y" * 500) or "") == 100


def test_compose_prompt_substitutes_the_slot() -> None:
    assert compose_prompt("a cat", "{prompt}, shot on 35mm") == "a cat, shot on 35mm"
    assert compose_prompt("a cat", None) == "a cat"
    assert compose_prompt("", "{prompt}, moody") == "a striking subject, moody"
