"""Smart text matching for stop/station search.

Handles accents, abbreviations, English/tourist aliases and typos so users can
type "d joao 2" and find "D. João II", or "Trinidade" and still find
"Trindade".

Typo tolerance uses the standard library's :class:`difflib.SequenceMatcher`
rather than ``rapidfuzz``: it is good enough for short station names and adds
no third-party dependency (the bot has to install cleanly on Railway from
``requirements.txt``). It is applied strictly as a *secondary* signal — only
when the exact/token/abbreviation matching below found nothing at all — so no
query that already resolved keeps a different score than before.
"""

import unicodedata
import re
from difflib import SequenceMatcher

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
    # Very common in the wild and previously missing
    "est.": "estacao",
    "hosp.": "hospital",
    "aerop.": "aeroporto",
    "pq.": "parque",
}

# English / tourist phrasings mapped onto the Portuguese wording actually used
# in the station and stop names. Keys are accent-free lowercase; multi-word
# keys are applied before single-word ones.
_QUERY_ALIASES = {
    "airport": "aeroporto",
    "oporto": "porto",
    "dragon stadium": "estadio do dragao",
    "dragons stadium": "estadio do dragao",
    "dragon": "dragao",
    "stadium": "estadio",
    "house of music": "casa da musica",
    "music house": "casa da musica",
    "concert hall": "casa da musica",
    "city center": "aliados",
    "city centre": "aliados",
    "downtown": "aliados",
    "town hall": "aliados",
    "city hall": "aliados",
    "university": "universitario",
    "campus": "universitario",
    "beach": "praia",
    "garden": "jardim",
    "market": "mercado",
    "bridge": "ponte",
    "hospital of": "hospital de",
    "saint": "sao",
}

# Generic words tourists append that carry no distinguishing information
# ("São Bento station", "Trindade metro stop"). Dropped from the query when
# something else remains to match on.
_QUERY_STOPWORDS = {
    "station", "stations", "stop", "stops", "metro", "subway",
    "underground", "tube", "line", "platform",
    # English filler words. Portuguese connectors (de/do/da) are left alone:
    # they are part of the official names and the token scorer handles them.
    "the", "an", "of", "and", "to",
}

_ALIAS_PHRASES = sorted(_QUERY_ALIASES, key=lambda p: (-len(p.split()), -len(p)))

# Typo tolerance: a query has to be at least this similar to a name (or to one
# of its words) before it counts as a misspelling rather than a different word.
_FUZZY_MIN_RATIO = 0.82
_FUZZY_MIN_LEN = 4
_FUZZY_MAX_SCORE = 70.0

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


def expand_query_aliases(query: str) -> str:
    """Rewrite English/tourist phrasings into the Portuguese station wording.

    Only applied to the *query* — the names come from the operators and are
    always Portuguese.

    Examples:
        >>> expand_query_aliases("airport")
        'aeroporto'
        >>> expand_query_aliases("São Bento station")
        'sao bento'
        >>> expand_query_aliases("dragon stadium")
        'estadio do dragao'
    """
    text = _strip_accents(query.strip().lower())
    if not text:
        return ""

    for phrase in _ALIAS_PHRASES:
        if phrase in text:
            text = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)",
                          _QUERY_ALIASES[phrase], text)

    tokens = text.split()
    kept = [tok for tok in tokens if tok.strip(".") not in _QUERY_STOPWORDS]
    # Never let the stopword filter empty the query ("station" on its own).
    return " ".join(kept or tokens)


def _ratio(a: str, b: str) -> float:
    """Similarity of two short strings, cheaply rejecting hopeless pairs."""
    matcher = SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < _FUZZY_MIN_RATIO:
        return 0.0
    if matcher.quick_ratio() < _FUZZY_MIN_RATIO:
        return 0.0
    return matcher.ratio()


def typo_score(query: str, name: str) -> float:
    """Score ``query`` as a possible *misspelling* of ``name``.

    Returns 0 unless the query is close enough to be a typo rather than a
    different word, so junk queries never resolve to a station. This is a
    secondary signal: :func:`match_score` only consults it when exact, token
    and abbreviation matching all scored zero.

    Examples:
        >>> typo_score("Trinidade", "Trindade") > 0
        True
        >>> typo_score("xyzqwerty123", "Trindade")
        0.0
    """
    q = normalize_simple(expand_query_aliases(query))
    n = normalize_simple(name)
    if len(q) < _FUZZY_MIN_LEN or len(n) < _FUZZY_MIN_LEN:
        return 0.0

    best = _ratio(q, n)

    # A single misspelt word inside a longer name ("hosp. sao jaoo").
    q_tokens = [tok for tok in q.split() if len(tok) >= _FUZZY_MIN_LEN]
    n_tokens = [tok for tok in n.split() if len(tok) >= _FUZZY_MIN_LEN]
    if q_tokens and n_tokens:
        matched = 0
        total = 0.0
        for qt in q_tokens:
            token_best = 0.0
            for nt in n_tokens:
                if abs(len(qt) - len(nt)) > 2:
                    continue
                token_best = max(token_best, _ratio(qt, nt))
            if token_best >= _FUZZY_MIN_RATIO:
                matched += 1
                total += token_best
        if matched:
            # Scale by how much of the query the typo match actually explains,
            # so one lucky word out of four does not look like a hit.
            coverage = matched / len(q.split())
            best = max(best, (total / matched) * coverage)

    if best < _FUZZY_MIN_RATIO:
        return 0.0
    return min(_FUZZY_MAX_SCORE, 100.0 * best - 25.0)


def match_score(query: str, name: str, fuzzy: bool = True) -> float:
    """Score how well a query matches a name. Higher is better, 0 = no match.

    Scoring:
        - Exact match (normalized): 100
        - All query tokens found in name: 60-90 (based on coverage)
        - Partial token matches: 20-50
        - Typo of the name (secondary signal, only when nothing else
          matched): 57-70
        - No match: 0

    Args:
        query: What the user typed. English/tourist aliases ("airport",
            "dragon stadium", "São Bento station") are resolved first.
        name: The official stop/station name.
        fuzzy: Set to False to disable typo tolerance entirely.
    """
    query = expand_query_aliases(query) or query
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
        # Nothing matched literally — the only remaining possibility is that
        # the user misspelled the name. Deliberately last, so this can never
        # change the score of a query that already resolved.
        return typo_score(query, name) if fuzzy else 0

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
