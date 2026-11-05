"""Shared GitHub refresh coordination, with short database transactions."""

import os
import sqlite3
import threading
from contextlib import contextmanager

import psycopg

from pipefoundry.metadata import PostgresConnection

DDL = """
CREATE TABLE IF NOT EXISTS pf_github_cache (
    request_key TEXT PRIMARY KEY, repository TEXT NOT NULL, payload TEXT,
    checked_at DOUBLE PRECISION NOT NULL, revoked_until DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pf_github_refresh (
    id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL DEFAULT '',
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    cooldown_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    tokens DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
"""


class GitHubStore:
    def __init__(self, *, dsn=None, sqlite_path=":memory:", disabled=False):
        self.dsn = dsn
        self.sqlite_path = sqlite_path
        self.disabled = disabled
        self.ready = False
        self.lock = threading.RLock()
        self.memory = (
            sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            if not dsn and sqlite_path == ":memory:" and not disabled
            else None
        )

    @classmethod
    def configured(cls):
        dsn = os.getenv("PIPEFOUNDRY_METADATA_DSN")
        hosted = os.getenv("VERCEL") == "1"
        return cls(
            dsn=dsn,
            sqlite_path=os.getenv("PIPEFOUNDRY_GITHUB_CACHE_DB", ":memory:"),
            disabled=hosted and not dsn,
        )

    @contextmanager
    def connection(self):
        if self.disabled:
            raise OSError("Shared GitHub cache is not configured")
        if self.dsn:
            with psycopg.connect(self.dsn, connect_timeout=5) as connection:
                connection.execute("SET LOCAL statement_timeout='5s'")
                connection.execute("SET LOCAL lock_timeout='3s'")
                connection.execute("SELECT pg_advisory_xact_lock(1346785351,9)")
                database = PostgresConnection(connection)
                if not self.ready:
                    database.executescript(DDL)
                yield database
            self.ready = True
            return
        with self.lock:
            connection = self.memory or sqlite3.connect(
                self.sqlite_path, timeout=5, isolation_level=None
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self.ready:
                    for statement in DDL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                yield connection
                connection.commit()
                self.ready = True
            except BaseException:
                connection.rollback()
                raise
            finally:
                if connection is not self.memory:
                    connection.close()
