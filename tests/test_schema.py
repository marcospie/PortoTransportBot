"""Schema-completeness tests for :mod:`bot.database`.

These tests exist because ``commuter_profiles`` was queried by
``save_commuter_profile``/``get_commuter_profile`` but was never created by
``_SCHEMA_SQL``.  In JSON-fallback mode (no ``DATABASE_URL``) that is invisible,
so the bug only showed up in production as ``UndefinedTableError``.

Rather than hardcoding a list of expected tables/columns (which would rot), the
tests below *parse* ``_SCHEMA_SQL`` + ``_MIGRATIONS_SQL`` into a table -> columns
map, then *parse the SQL statements out of the module source* and assert that
every table and column that is referenced actually exists in the schema.  Any
future function that queries something that is never created fails here.
"""

import re
from pathlib import Path

import pytest

import bot.database as db


# ===================================================================
# Schema (DDL) parsing
# ===================================================================

_DDL_CONSTRAINT_KEYWORDS = {
    "UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "CONSTRAINT", "EXCLUDE", "LIKE",
}


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_schema(schema_sql: str, migrations: list[str]) -> dict[str, set[str]]:
    """Return ``{table_name: {column, ...}}`` parsed from the DDL."""
    tables: dict[str, set[str]] = {}

    for match in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)\n\s*\)\s*;",
        schema_sql,
        re.S | re.I,
    ):
        table = match.group(1)
        columns: set[str] = set()
        for part in _split_top_level(match.group(2)):
            part = part.strip()
            if not part:
                continue
            first = part.split()[0]
            if first.upper() in _DDL_CONSTRAINT_KEYWORDS:
                continue
            columns.add(first)
        tables[table] = columns

    # ALTER TABLE ... ADD COLUMN migrations add columns to existing tables.
    for statement in migrations:
        alter = re.search(
            r"ALTER\s+TABLE\s+([a-z_][a-z0-9_]*)\s+ADD\s+COLUMN\s+"
            r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
            statement,
            re.I,
        )
        if alter:
            tables.setdefault(alter.group(1), set()).add(alter.group(2))

    return tables


SCHEMA: dict[str, set[str]] = parse_schema(db._SCHEMA_SQL, db._MIGRATIONS_SQL)


# ===================================================================
# Query (DML) parsing out of the module source
# ===================================================================

def _query_source() -> str:
    """Module source with the DDL removed and whitespace normalised."""
    source = Path(db.__file__).read_text()
    source = source.replace(db._SCHEMA_SQL, " ")
    for statement in db._MIGRATIONS_SQL:
        source = source.replace(statement, " ")
    return re.sub(r"\s+", " ", source)


QUERY_SRC = _query_source()

# Placeholders that legitimately appear inside SQL text in database.py.  Each one
# must be derived from the _SETTINGS_COLUMNS allowlist (that is precisely what
# makes the f-string interpolation injection-safe), so each resolves to a known
# set of real column names.  A new, unknown placeholder fails the tests below.
_KNOWN_DYNAMIC_FRAGMENTS = {
    "{column}": lambda: set(db._SETTINGS_COLUMNS.values()),
    "{_SETTINGS_SELECT_COLUMNS}": lambda: {
        c.strip() for c in db._SETTINGS_SELECT_COLUMNS.split(",")
    },
}

# Column-list entries that are not column names.
_NON_COLUMN_TOKENS = {"*", "1"}


def _resolve_columns(raw_list: str) -> set[str]:
    """Turn a SQL column list into a set of concrete column names.

    Literals, ``*``, aggregates and bind parameters are ignored.  Dynamic
    ``{...}`` fragments are expanded via ``_KNOWN_DYNAMIC_FRAGMENTS``; an
    unrecognised fragment raises, which fails the calling test on purpose.
    """
    columns: set[str] = set()
    for token in raw_list.split(","):
        token = token.strip()
        if not token or token in _NON_COLUMN_TOKENS or token.startswith("$"):
            continue
        if "{" in token:
            if token not in _KNOWN_DYNAMIC_FRAGMENTS:
                raise AssertionError(
                    f"Unknown dynamic SQL fragment {token!r} in bot/database.py. "
                    "Dynamic identifiers must come from the _SETTINGS_COLUMNS "
                    "allowlist and be registered in _KNOWN_DYNAMIC_FRAGMENTS so "
                    "they can be checked against the schema."
                )
            columns |= _KNOWN_DYNAMIC_FRAGMENTS[token]()
            continue
        if "(" in token:  # COUNT(*), now(), ...
            continue
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", token):
            continue
        columns.add(token)
    return columns


def referenced_tables() -> set[str]:
    """Every table name referenced by a query in bot/database.py."""
    tables: set[str] = set()
    tables |= set(re.findall(r"\bFROM\s+([a-z_][a-z0-9_]*)", QUERY_SRC))
    tables |= set(re.findall(r"\bINTO\s+([a-z_][a-z0-9_]*)", QUERY_SRC))
    tables |= set(re.findall(r"\bJOIN\s+([a-z_][a-z0-9_]*)", QUERY_SRC))
    tables |= set(re.findall(r"\bUPDATE\s+([a-z_][a-z0-9_]*)\s+SET\b", QUERY_SRC))
    return tables


def referenced_columns_by_table() -> dict[str, set[str]]:
    """Columns that can be attributed to a specific table."""
    result: dict[str, set[str]] = {}

    def add(table: str, columns: set[str]) -> None:
        result.setdefault(table, set()).update(columns)

    # INSERT INTO t (a, b)
    for table, cols in re.findall(
        r"\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)\s*\(([^)]*)\)", QUERY_SRC
    ):
        add(table, _resolve_columns(cols))

    # SELECT a, b FROM t
    for cols, table in re.findall(
        r"\bSELECT\s+(.+?)\s+FROM\s+([a-z_][a-z0-9_]*)", QUERY_SRC
    ):
        add(table, _resolve_columns(cols))

    # UPDATE t SET a = ..., b = ... WHERE
    for table, assignments in re.findall(
        r"\bUPDATE\s+([a-z_][a-z0-9_]*)\s+SET\s+(.+?)\s+WHERE\b", QUERY_SRC
    ):
        add(table, set(re.findall(r"([a-z_][a-z0-9_]*)\s*=", assignments)))

    return result


def referenced_columns_anywhere() -> set[str]:
    """Columns referenced without an easily attributable table.

    Covers ``WHERE col = $1`` predicates, ``ORDER BY col``, ``ON CONFLICT (col)``
    and ``DO UPDATE SET col = ...``.  These are checked against the union of all
    schema columns - enough to catch a column that is never created anywhere.
    """
    columns: set[str] = set()
    columns |= set(re.findall(r"([a-z_][a-z0-9_]*)\s*=\s*\$\d+", QUERY_SRC))
    columns |= set(re.findall(r"\bORDER\s+BY\s+([a-z_][a-z0-9_]*)", QUERY_SRC))
    columns |= set(
        re.findall(r"\bON\s+CONFLICT\s*\(\s*([a-z_][a-z0-9_]*)\s*\)", QUERY_SRC)
    )
    for assignments in re.findall(
        r"\bDO\s+UPDATE\s+SET\s+(.+?)(?:\bWHERE\b|\"\"\"|$)", QUERY_SRC
    ):
        columns |= set(re.findall(r"([a-z_][a-z0-9_]*)\s*=", assignments))
    # Drop dynamic placeholders - they are validated separately.
    return {c for c in columns if "{" not in c}


ALL_SCHEMA_COLUMNS = {col for cols in SCHEMA.values() for col in cols}


# ===================================================================
# Sanity checks on the parsers themselves
# ===================================================================

class TestParserSanity:
    """If the parsers silently stop working the other tests become vacuous."""

    def test_schema_has_tables(self):
        assert len(SCHEMA) >= 4, f"parsed too few tables: {sorted(SCHEMA)}"

    def test_every_parsed_table_has_columns(self):
        for table, columns in SCHEMA.items():
            assert columns, f"table {table} parsed with no columns"

    def test_known_columns_are_parsed(self):
        # A couple of anchors so a broken regex cannot make the suite pass.
        assert "id" in SCHEMA["users"]
        assert "stop_id" in SCHEMA["favorites"]
        assert "user_id" in SCHEMA["user_settings"]

    def test_queries_were_found(self):
        assert len(referenced_tables()) >= 4
        assert referenced_columns_by_table(), "no per-table columns extracted"
        assert referenced_columns_anywhere(), "no predicate columns extracted"


# ===================================================================
# The actual drift checks
# ===================================================================

class TestSchemaCompleteness:
    """Every table/column queried by database.py must exist in _SCHEMA_SQL."""

    def test_every_queried_table_exists(self):
        missing = sorted(referenced_tables() - set(SCHEMA))
        assert not missing, (
            f"bot/database.py queries table(s) that _SCHEMA_SQL never creates: "
            f"{missing}. Add them to _SCHEMA_SQL."
        )

    def test_every_queried_column_exists_on_its_table(self):
        problems = []
        for table, columns in referenced_columns_by_table().items():
            known = SCHEMA.get(table)
            if known is None:
                problems.append(f"{table} (table not in schema)")
                continue
            for column in sorted(columns - known):
                problems.append(f"{table}.{column}")
        assert not problems, (
            "bot/database.py queries column(s) that _SCHEMA_SQL never creates: "
            f"{problems}"
        )

    def test_every_predicate_column_exists_somewhere(self):
        missing = sorted(referenced_columns_anywhere() - ALL_SCHEMA_COLUMNS)
        assert not missing, (
            "bot/database.py references column(s) in WHERE/ORDER BY/ON CONFLICT "
            f"that no table in _SCHEMA_SQL defines: {missing}"
        )


class TestCommuterProfilesTable:
    """Regression guard for the original bug."""

    def test_table_is_created(self):
        assert "commuter_profiles" in SCHEMA, (
            "commuter_profiles is queried by save_commuter_profile() / "
            "get_commuter_profile() but is not created by _SCHEMA_SQL"
        )

    def test_has_required_columns(self):
        for column in ("user_id", "profile_data", "updated_at"):
            assert column in SCHEMA["commuter_profiles"], (
                f"commuter_profiles.{column} is used by database.py but not created"
            )

    def test_referenced_by_queries(self):
        # Make sure the queries really do target this table (guards the guard).
        assert "commuter_profiles" in referenced_tables()


# ===================================================================
# Settings allowlist <-> schema consistency
# ===================================================================

class TestSettingsAllowlist:
    """The DEFAULT_SETTINGS allowlist is the SQL-injection guard - verify it."""

    def test_allowlist_matches_defaults(self):
        assert set(db._SETTINGS_COLUMNS) == set(db.DEFAULT_SETTINGS)

    def test_every_setting_has_a_real_column(self):
        missing = sorted(
            set(db._SETTINGS_COLUMNS.values()) - SCHEMA["user_settings"]
        )
        assert not missing, (
            "DEFAULT_SETTINGS keys map to user_settings column(s) that are never "
            f"created: {missing}"
        )

    def test_select_column_list_covers_every_setting(self):
        selected = {c.strip() for c in db._SETTINGS_SELECT_COLUMNS.split(",")}
        assert selected == set(db._SETTINGS_COLUMNS.values()), (
            "get_user_settings() would silently return defaults for settings "
            "missing from its SELECT list"
        )

    def test_column_names_are_plain_identifiers(self):
        for column in db._SETTINGS_COLUMNS.values():
            assert db._SAFE_IDENTIFIER_RE.match(column), column

    @pytest.mark.parametrize(
        "hostile_key",
        [
            "language; DROP TABLE users --",
            "language) VALUES (1,1); --",
            "metro_radius_m, language",
            "unknown_key",
            "",
            "USERS",
        ],
    )
    def test_settings_column_rejects_non_allowlisted_keys(self, hostile_key):
        """_settings_column() must fail closed - it feeds an f-string."""
        with pytest.raises(ValueError):
            db._settings_column(hostile_key)

    def test_settings_column_accepts_every_known_key(self):
        for key in db.DEFAULT_SETTINGS:
            assert db._settings_column(key) == db._SETTINGS_COLUMNS[key]


class TestNoUnauditedDynamicSql:
    """Any new f-string identifier in SQL must be registered and checked."""

    def test_all_dynamic_fragments_are_known(self):
        # _resolve_columns raises on unknown fragments; walking every column list
        # exercises that path for the whole module.
        referenced_columns_by_table()  # must not raise

    def test_registered_fragments_resolve_to_real_columns(self):
        for fragment, resolver in _KNOWN_DYNAMIC_FRAGMENTS.items():
            resolved = resolver()
            assert resolved, f"{fragment} resolved to nothing"
            missing = sorted(resolved - ALL_SCHEMA_COLUMNS)
            assert not missing, f"{fragment} can expand to unknown columns: {missing}"
