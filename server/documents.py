import copy
import json
import sqlite3
from contextlib import contextmanager


class SQLiteDocuments:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS registry_documents (id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    @contextmanager
    def transaction(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            original = {key: json.loads(body) for key, body in connection.execute("SELECT id, body FROM registry_documents")}
            documents = copy.deepcopy(original)
            yield documents
            if write:
                for key in original.keys() - documents.keys():
                    connection.execute("DELETE FROM registry_documents WHERE id = ?", (key,))
                for key, value in documents.items():
                    if original.get(key) != value:
                        connection.execute("INSERT OR REPLACE INTO registry_documents VALUES (?, ?)", (key, json.dumps(value)))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def legacy(self):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skills'").fetchone():
                return None
            return {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for table in ("skills", "intakes", "proposals", "agent_bindings", "metadata")
            }
