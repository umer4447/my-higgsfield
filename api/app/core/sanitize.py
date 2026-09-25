"""Normalisation for every string that is stored, shown to another person, or
used as a cache key. See architecture.md section 9.
"""

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_SPACES = re.compile("[ \t\u00a0]+")  # NBSP included deliberately
_BLANK_LINES = re.compile(r"\n{3,}")
_HANDLE_OK = re.compile(r"^[a-z0-9._-]{3,32}$")

RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "root",
        "system",
        "support",
        "help",
        "darkroom",
        "staff",
        "moderator",
        "null",
        "undefined",
        "me",
        "you",
        "settings",
        "login",
        "logout",
        "signup",
        "about",
        "www",
    }
)

MAX_PROMPT = 2000
MAX_SEARCH = 100


def _strip_invisible(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_ZERO_WIDTH)
    # Keep newlines; drop every other control character. They are invisible in
    # the UI and make two identical-looking prompts hash differently, which
    # breaks dedupe and defeats any content filter added later.
    return "".join(c for c in s if c == "\n" or unicodedata.category(c)[0] != "C")


def sanitize_prompt(raw: str) -> str:
    s = _strip_invisible(raw)
    s = _SPACES.sub(" ", s)
    s = _BLANK_LINES.sub("\n\n", s).strip()
    if not s:
        raise ValueError("Prompt is empty after normalisation.")
    return s[:MAX_PROMPT]


def sanitize_search(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = _SPACES.sub(" ", _strip_invisible(raw).replace("\n", " ")).strip()
    return s[:MAX_SEARCH] or None


def normalize_handle(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw).strip().lower()
    if not _HANDLE_OK.match(s):
        raise ValueError(
            "Handles are 3-32 characters: lowercase letters, digits, dot, "
            "underscore or hyphen."
        )
    if s in RESERVED_HANDLES:
        raise ValueError("That handle is reserved.")
    return s


def compose_prompt(prompt: str, template: str | None) -> str:
    """Apply a preset template. This is the prompt that is actually sent."""
    base = prompt.strip()
    if not template:
        return base
    return template.replace("{prompt}", base or "a striking subject")
