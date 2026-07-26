"""WhatsApp text formatting helpers.

The shared translation table in ``bot/utils/i18n.py`` is written for Telegram's
**MarkdownV2** parse mode, which requires every one of ``_*[]()~`>#+-=|{}.!``
to be backslash-escaped.  WhatsApp uses a completely different (and much
smaller) markup dialect:

===============  =========================  =========================
meaning          Telegram MarkdownV2        WhatsApp
===============  =========================  =========================
bold             ``*bold*``                 ``*bold*``      (same)
italic           ``_italic_``               ``_italic_``    (same)
strikethrough    ``~strike~``               ``~strike~``    (same)
monospace        ``` `code` ```             ``` ```code``` ```
escaping         backslash before ``.!-``   **none at all**
===============  =========================  =========================

Sending a MarkdownV2 string straight to WhatsApp therefore leaks *visible
backslashes* to the user (``Bem-vindo\\!``).  ``from_markdown_v2`` is the single
conversion point that removes them, and :func:`whatsapp.strings.wt` runs every
translated string through it.
"""

from __future__ import annotations

import re

__all__ = [
    "from_markdown_v2",
    "has_markdown_v2_escapes",
    "bold",
    "italic",
    "truncate",
]

# Every character Telegram's MarkdownV2 requires to be escaped, plus the
# backslash itself.  Only *escaped* occurrences are rewritten - a lone ``*``
# stays a lone ``*`` so bold/italic markup survives untouched.
_MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!\\"
_MDV2_ESCAPE_RE = re.compile(r"\\([" + re.escape(_MDV2_SPECIALS) + r"])")

# Telegram inline code spans (`BCM2`).  WhatsApp does not render single
# backticks, so they would show up literally - drop the delimiters and keep the
# content as plain text.
_CODE_SPAN_RE = re.compile(r"`([^`\n]*)`")

# Telegram's ``__underline__`` has no WhatsApp equivalent; degrade to italic.
_UNDERLINE_RE = re.compile(r"__(.+?)__", re.DOTALL)


def from_markdown_v2(text: str) -> str:
    """Convert a Telegram MarkdownV2 string into WhatsApp-safe markup.

    Removes MarkdownV2 backslash escapes (so users never see ``\\!``), turns
    inline code spans into plain text and degrades underline to italic.  Bold,
    italic and strikethrough already share the same syntax and pass through.
    """
    if not text:
        return ""
    out = _MDV2_ESCAPE_RE.sub(r"\1", text)
    out = _UNDERLINE_RE.sub(r"_\1_", out)
    out = out.replace("```", "")
    out = _CODE_SPAN_RE.sub(r"\1", out)
    return out


def has_markdown_v2_escapes(text: str) -> bool:
    """True if *text* still contains MarkdownV2 backslash escapes."""
    return bool(_MDV2_ESCAPE_RE.search(text or ""))


def bold(text: str) -> str:
    """Wrap *text* in WhatsApp bold markers."""
    return f"*{text}*"


def italic(text: str) -> str:
    """Wrap *text* in WhatsApp italic markers."""
    return f"_{text}_"


def truncate(text: str, limit: int) -> str:
    """Trim *text* to *limit* characters, adding an ellipsis when cut.

    WhatsApp rejects payloads whose fields exceed documented limits (1024 for
    an interactive body, 24 for a list-row title, ...), so every user-visible
    field goes through here.
    """
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return text[: limit - 1].rstrip() + "…"
