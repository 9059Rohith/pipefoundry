"""Small DB-API compatibility boundary for fixed control-plane SQL statements.

No identifiers or SQL are accepted from configuration. PostgreSQL uses a fixed
pf_ table prefix so workload tables stay separate from metadata.
"""

import re
import sqlite3

import psycopg

TABLES = re.compile(r"\b(revisions|audit|operations|cluster_targets|artifacts|demo_seed)\b")


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        values = self.cursor.fetchone()
        if values is None:
            return None
        return Record(zip([column.name for column in self.cursor.description], values, strict=True))

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    @property
    def rowcount(self):
        return self.cursor.rowcount


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        # The durable operation row already serializes writers for each pipeline;
        # SQLite's database-wide IMMEDIATE transaction is unnecessary on PG.
        if statement == "BEGIN IMMEDIATE":
            statement = "SELECT 1"
        statement = TABLES.sub(lambda match: "pf_" + match.group(0), statement)
        statement = statement.replace("?", "%s")
        statement = statement.replace("id INTEGER PRIMARY KEY", "id BIGSERIAL PRIMARY KEY")
        statement = statement.replace("contents BLOB", "contents BYTEA")
        try:
            return Cursor(self.connection.execute(statement, parameters))
        except psycopg.errors.UniqueViolation as exc:
            # Preserve the engine's conflict boundary across both DB adapters.
            raise sqlite3.IntegrityError("metadata uniqueness conflict") from exc

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)
