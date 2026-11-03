"""Safely copy BarberFlow data from SQLite into an empty PostgreSQL database.

The default mode is a read-only source audit. Use --apply only after reviewing
the audit and making backups of both databases.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from database_postgres import POSTGRES_SCHEMA


# Parent tables must be inserted before their dependents (all target FKs are
# checked during the same transaction).
TABLE_ORDER = (
    "users",
    "services",
    "products",
    "barbers",
    "appointments",
    "orders",
    "order_items",
    "settings",
    "stock_movements",
    "portfolio",
    "auth_login_attempts",
    "password_reset_tokens",
    "financial_transactions",
    "barber_commission_settings",
)


def _sqlite_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _source_audit(source: sqlite3.Connection) -> tuple[dict[str, int], dict[str, list[str]]]:
    integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"SQLite integrity_check falhou: {integrity}")
    foreign_key_errors = source.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise ValueError(
            f"SQLite contém {len(foreign_key_errors)} violações de chave estrangeira."
        )

    tables = {
        row[0]
        for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    counts: dict[str, int] = {}
    columns: dict[str, list[str]] = {}
    for table in TABLE_ORDER:
        if table not in tables:
            continue
        quoted = _sqlite_identifier(table)
        columns[table] = [
            row[1] for row in source.execute(f"PRAGMA table_info({quoted})")
        ]
        counts[table] = source.execute(
            f"SELECT COUNT(*) FROM {quoted}"
        ).fetchone()[0]
    if not counts:
        raise ValueError(
            "O arquivo SQLite não contém tabelas reconhecidas do BarberFlow."
        )
    return counts, columns


def audit_sqlite_file(sqlite_path: str | Path) -> dict[str, int]:
    """Read-only integrity and row-count audit of a SQLite database."""
    path = Path(sqlite_path).expanduser().resolve(strict=True)
    uri = path.as_uri() + "?mode=ro"
    source = sqlite3.connect(uri, uri=True)
    try:
        counts, _ = _source_audit(source)
        return counts
    finally:
        source.close()


def migrate_sqlite_connection(
    sqlite_path: str | Path,
    target: psycopg.Connection,
) -> dict[str, int]:
    """Copy one SQLite database into a schema-only, empty PostgreSQL database.

    Schema creation and all row inserts are one transaction. Any failure rolls
    back the entire import. Existing target rows are never overwritten.
    """
    path = Path(sqlite_path).expanduser().resolve(strict=True)
    source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        counts, source_columns = _source_audit(source)
        with target.transaction():
            for statement in POSTGRES_SCHEMA:
                target.execute(statement)

            for table in TABLE_ORDER:
                existing = target.execute(
                    sql.SQL("SELECT COUNT(*) AS total FROM {}").format(
                        sql.Identifier(table)
                    )
                ).fetchone()["total"]
                if existing:
                    raise ValueError(
                        f"O destino PostgreSQL não está vazio: {table} contém "
                        f"{existing} registro(s). Nenhum dado foi alterado."
                    )

            target_columns: dict[str, set[str]] = {}
            for table in TABLE_ORDER:
                rows = target.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema=current_schema() AND table_name=%s
                    """,
                    (table,),
                ).fetchall()
                target_columns[table] = {row["column_name"] for row in rows}

            for table in TABLE_ORDER:
                if table not in counts or not counts[table]:
                    continue
                unknown_columns = set(source_columns[table]) - target_columns[table]
                if unknown_columns:
                    names = ", ".join(sorted(unknown_columns))
                    raise ValueError(
                        f"A tabela {table} tem colunas sem equivalente no destino "
                        f"({names}); importação cancelada para evitar perda de dados."
                    )
                columns = [
                    name
                    for name in source_columns[table]
                    if name in target_columns[table]
                ]
                if not columns:
                    raise ValueError(f"Nenhuma coluna compatível para importar: {table}")
                insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                source_rows = source.execute(
                    f"SELECT {', '.join(map(_sqlite_identifier, columns))} "
                    f"FROM {_sqlite_identifier(table)}"
                )
                for row in source_rows:
                    target.execute(insert, tuple(row[column] for column in columns))

            for table, expected_count in counts.items():
                actual_count = target.execute(
                    sql.SQL("SELECT COUNT(*) AS total FROM {}").format(
                        sql.Identifier(table)
                    )
                ).fetchone()["total"]
                if actual_count != expected_count:
                    raise ValueError(
                        f"Contagem divergente em {table}: SQLite={expected_count}, "
                        f"PostgreSQL={actual_count}."
                    )

            # Explicitly inserted identity values do not reliably advance
            # identity sequences. Restore each high-water mark, including IDs
            # consumed by rows that were later deleted from the source.
            source_sequence: dict[str, int] = {}
            try:
                for row in source.execute("SELECT name, seq FROM sqlite_sequence"):
                    source_sequence[row["name"]] = int(row["seq"])
            except sqlite3.OperationalError:
                pass

            for table in TABLE_ORDER:
                if table not in target_columns or "id" not in target_columns[table]:
                    continue
                sequence_name = target.execute(
                    "SELECT pg_get_serial_sequence(%s, 'id') AS sequence_name",
                    (table,),
                ).fetchone()["sequence_name"]
                if not sequence_name:
                    continue
                max_id = target.execute(
                    sql.SQL("SELECT MAX(id) AS max_id FROM {}").format(
                        sql.Identifier(table)
                    )
                ).fetchone()["max_id"]
                high_water = max(max_id or 0, source_sequence.get(table, 0))
                if high_water:
                    target.execute(
                        "SELECT setval(%s::regclass, %s, true)",
                        (sequence_name, high_water),
                    )
        return counts
    finally:
        source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audita ou importa SQLite para PostgreSQL sem sobrescrever dados."
    )
    parser.add_argument(
        "--sqlite",
        required=True,
        type=Path,
        help="caminho do arquivo SQLite de origem",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="executa a cópia; sem esta opção, apenas audita o SQLite",
    )
    args = parser.parse_args(argv)

    try:
        counts = audit_sqlite_file(args.sqlite)
        total = sum(counts.values())
        print("Auditoria da origem SQLite concluída:")
        for table, count in counts.items():
            print(f"  {table}: {count}")
        print(f"  total de registros: {total}")

        if not args.apply:
            print("Modo somente leitura. Use --apply para importar ao PostgreSQL.")
            return 0

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("Defina DATABASE_URL para o banco PostgreSQL de destino.")
        print(
            "ATENÇÃO: o destino deve ser uma base PostgreSQL exclusiva e vazia. "
            "O importador rejeita destinos com registros existentes."
        )
        with psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row) as target:
            migrated = migrate_sqlite_connection(args.sqlite, target)
        print(f"Importação concluída ({sum(migrated.values())} registros).")
        return 0
    except (OSError, sqlite3.Error, psycopg.Error, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
