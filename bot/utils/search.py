"""Smart text matching for stop/station search.

Handles accents, abbreviations, and fuzzy matching so users can type
"d joao 2" and find "D. João II".
"""

import unicodedata
import re

# Common abbreviations in Porto transport names
_ABBREVIATIONS = {
    "d.": "dom",
    "s.": "são santo santa",
    "sta.": "santa",
    "sto.": "santo",
    "sr.": "senhor",
    "sra.": "senhora",
    "av.": "avenida",
    "r.": "rua",
    "pr.": "praça",
    "lg.": "largo",
    "univ.": "universidade universitário",
}

# Roman numeral to arabic mapping
_ROMAN_TO_ARABIC = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
}

# Reverse mapping
_ARABIC_TO_ROMAN = {v: k for k, v in _ROMAN_TO_ARABIC.items()}


def normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip accents, expand abbreviations.

    Examples:
        >>> normalize("D. João II")
        'd joao ii 2 dom'
        >>> normalize("São Bento")
        'sao bento s.'
        >>> normalize("Fânzeres")
        'fanzeres'
    """
    text = text.strip()
    if not text:
        return ""

    lower = text.lower()

    # Strip accents: João → joao, Fânzeres → fanzeres
    stripped = _strip_accents(lower)

    # Remove punctuation except dots (for abbreviations)
    cleaned = re.sub(r"[''`()\[\]]", "", stripped)

    # Build expanded form with abbreviation alternatives
    tokens = cleaned.split()
    expanded_tokens = list(tokens)

    for token in tokens:
        # Expand abbreviations both ways
        if token in _ABBREVIATIONS:
            expanded_tokens.extend(_ABBREVIATIONS[token].split())
        elif token + "." in _ABBREVIATIONS:
            # User typed "d" instead of "d." — treat as abbreviation
            expanded_tokens.extend(_ABBREVIATIONS[token + "."].split())
            expanded_tokens.append(token + ".")
        else:
            # Check if token is the expanded form of an abbreviation
            for abbr, expansions in _ABBREVIATIONS.items():
                if token in expansions.split():
                    expanded_tokens.append(abbr.rstrip("."))
                    expanded_tokens.append(abbr)

        # Roman ↔ Arabic numeral conversion
        if token in _ROMAN_TO_ARABIC:
            expanded_tokens.append(_ROMAN_TO_ARABIC[token])
        elif token in _ARABIC_TO_ROMAN:
            expanded_tokens.append(_ARABIC_TO_ROMAN[token])

    return " ".join(expanded_tokens)


def normalize_simple(text: str) -> str:
    """Normalize without expanding abbreviations — just lowercase + strip accents."""
    text = text.strip()
    if not text:
        return ""
    lower = text.lower()
    stripped = _strip_accents(lower)
    cleaned = re.sub(r"[''`()\[\].!]", "", stripped)
    return " ".join(cleaned.split())


def _strip_accents(text: str) -> str:
    """Remove diacritical marks from text. João → joao, café → cafe."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def match_score(query: str, name: str) -> float:
    """Score how well a query matches a name. Higher is better, 0 = no match.

    Scoring:
        - Exact match (normalized): 100
        - All query tokens found in name: 60-90 (based on coverage)
        - Partial token matches: 20-50
        - No match: 0
    """
    norm_query = normalize(query)
    norm_name = normalize(name)

    if not norm_query:
        return 0

    # Exact match
    if norm_query == norm_name:
        return 100

    # Check if normalized query is a substring of normalized name
    if norm_query in norm_name:
        # Longer match relative to name = higher score
        return 80 + 15 * (len(norm_query) / len(norm_name))

    # Token-based matching
    # Use original query tokens (before abbreviation expansion) for ratio calc
    orig_query = normalize_simple(query)
    orig_query_tokens = set(orig_query.split())
    query_tokens = set(norm_query.split())
    name_tokens = set(norm_name.split())

    if not query_tokens:
        return 0

    # Count how many ORIGINAL query tokens have at least one matching
    # expanded form in the name tokens
    matched = 0
    for oqt in orig_query_tokens:
        # Gather this token's expanded forms (including itself)
        expanded = {oqt}
        if oqt in _ABBREVIATIONS:
            expanded.update(_ABBREVIATIONS[oqt].split())
        elif oqt + "." in _ABBREVIATIONS:
            expanded.update(_ABBREVIATIONS[oqt + "."].split())
            expanded.add(oqt + ".")
        else:
            for abbr, expansions in _ABBREVIATIONS.items():
                if oqt in expansions.split():
                    expanded.add(abbr.rstrip("."))
                    expanded.add(abbr)
        # Roman/Arabic conversions
        if oqt in _ROMAN_TO_ARABIC:
            expanded.add(_ROMAN_TO_ARABIC[oqt])
        elif oqt in _ARABIC_TO_ROMAN:
            expanded.add(_ARABIC_TO_ROMAN[oqt])

        best = 0.0
        for eqt in expanded:
            for nt in name_tokens:
                if eqt == nt:
                    best = max(best, 1.0)
                elif len(eqt) >= 3 and len(nt) >= 3 and (eqt in nt or nt in eqt):
                    best = max(best, 0.7)
                elif len(eqt) <= 2 and len(nt) >= 2 and nt.startswith(eqt):
                    best = max(best, 0.5)
        matched += best

    if matched == 0:
        return 0

    ratio = matched / len(orig_query_tokens)

    if ratio >= 1.0:
        # All tokens matched
        return 60 + 30 * (len(norm_query) / max(len(norm_name), 1))
    elif ratio >= 0.5:
        return 30 + 30 * ratio
    else:
        return 10 * ratio


def fuzzy_search(query: str, names: list[str], min_score: float = 15,
                 max_results: int = 15) -> list[tuple[str, float]]:
    """Search a list of names and return matches sorted by score.

    Returns list of (name, score) tuples.
    """
    results = []
    for name in names:
        score = match_score(query, name)
        if score >= min_score:
            results.append((name, score))

    results.sort(key=lambda x: (-x[1], len(x[0])))
    return results[:max_results]
