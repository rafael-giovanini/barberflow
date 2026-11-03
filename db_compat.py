"""Compatibility helpers for running the shared SQL layer on Psycopg 3."""
from __future__ import annotations

import re
import sqlite3
from typing import Any


def is_postgresql_configured() -> bool:
    import os
    return bool(os.getenv("DATABASE_URL", "").strip())


def adapt_sql_for_postgresql(sql: str) -> str:
    """Translate only known SQLite syntax, preserving quoted strings/comments."""
    # Psycopg uses %s. Do not change question marks or SQLite constructs inside
    # SQL strings, identifiers, dollar-quoted bodies, or comments. A global
    # regexp replacement is tempting here, but it can silently rewrite user
    # data in literals (for example a note containing "BEGIN IMMEDIATE").
    result: list[str] = []
    i = 0
    state = "normal"
    dollar_tag = ""
    normal_buffer: list[str] = []

    def flush_normal_buffer() -> None:
        if not normal_buffer:
            return
        normal_sql = "".join(normal_buffer)
        normal_sql = re.sub(
            r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", normal_sql, flags=re.IGNORECASE
        )
        normal_sql = re.sub(
            r"\bdate\(\s*'now'\s*,\s*'localtime'\s*\)",
            "CURRENT_DATE::text",
            normal_sql,
            flags=re.IGNORECASE,
        )
        # The application only uses COLLATE NOCASE with a bare column
        # expression. LOWER(column) has the same ordering/filtering semantics
        # and is accepted by PostgreSQL without requiring a database collation.
        normal_sql = re.sub(
            r"\b([a-zA-Z_][\w.]*)\s+COLLATE\s+NOCASE\b",
            r"LOWER(\1)",
            normal_sql,
            flags=re.IGNORECASE,
        )
        result.append(normal_sql.replace("?", "%s"))
        normal_buffer.clear()

    while i < len(sql):
        char = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if state == "normal":
            date_match = re.match(
                r"date\(\s*'now'\s*,\s*'localtime'\s*\)",
                sql[i:],
                flags=re.IGNORECASE,
            )
            if date_match:
                normal_buffer.append("CURRENT_DATE::text")
                i += len(date_match.group(0))
                continue
            if char == "'":
                flush_normal_buffer()
                state = "single"
                result.append(char)
            elif char == '"':
                flush_normal_buffer()
                state = "double"
                result.append(char)
            elif char == "-" and nxt == "-":
                flush_normal_buffer()
                state = "line_comment"
                result.extend((char, nxt))
                i += 1
            elif char == "/" and nxt == "*":
                flush_normal_buffer()
                state = "block_comment"
                result.extend((char, nxt))
                i += 1
            elif char == "$":
                match = re.match(r"\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$", sql[i:])
                if match:
                    flush_normal_buffer()
                    dollar_tag = match.group(0)
                    state = "dollar"
                    result.append(dollar_tag)
                    i += len(dollar_tag) - 1
                else:
                    normal_buffer.append(char)
            else:
                normal_buffer.append(char)
        elif state == "single":
            result.append(char)
            if char == "'":
                if nxt == "'":
                    result.append(nxt)
                    i += 1
                else:
                    state = "normal"
        elif state == "double":
            result.append(char)
            if char == '"':
                if nxt == '"':
                    result.append(nxt)
                    i += 1
                else:
                    state = "normal"
        elif state == "line_comment":
            result.append(char)
            if char == "\n":
                state = "normal"
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                result.extend((char, nxt))
                i += 1
                state = "normal"
            else:
                result.append(char)
        elif state == "dollar":
            if sql.startswith(dollar_tag, i):
                result.append(dollar_tag)
                i += len(dollar_tag) - 1
                state = "normal"
            else:
                result.append(char)
        i += 1
    flush_normal_buffer()
    return "".join(result)


class HybridRow(dict):
    """Mapping row that also supports SQLite-style positional access."""
    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def psycopg_row_factory(cursor):
    names = [column.name for column in (cursor.description or [])]

    def make_row(values):
        return HybridRow(zip(names, values))

    return make_row


def _translate_integrity_error(exc: Exception) -> sqlite3.IntegrityError:
    return sqlite3.IntegrityError(str(exc))


def postgres_connection_class():
    """Build a DB-API-compatible connection adapter lazily."""
    import psycopg

    class CompatibleCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def execute(self, query, params=None, *, prepare=None, binary=None):
            query = adapt_sql_for_postgresql(query)
            try:
                return self._cursor.execute(query, params, prepare=prepare, binary=binary)
            except psycopg.IntegrityError as exc:
                raise _translate_integrity_error(exc) from exc

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class CompatibleConnection(psycopg.Connection):
        def cursor(self, *args, **kwargs):
            return CompatibleCursor(super().cursor(*args, **kwargs))

        def execute(self, query, params=None, *, prepare=None, binary=None):
            try:
                return self.cursor().execute(query, params, prepare=prepare, binary=binary)
            except psycopg.IntegrityError as exc:
                raise _translate_integrity_error(exc) from exc

    return CompatibleConnection
