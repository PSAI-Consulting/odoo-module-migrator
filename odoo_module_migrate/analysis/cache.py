"""Safe JSON caches of source summaries, invalidated by file metadata.

Never cache ASTs or execute serialized Python. Dirty files and new/deleted
files invalidate the entry independently of the checkout's git revision.
"""

import atexit
from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
import sys
import sqlite3

SCHEMA = 6


@lru_cache(maxsize=4)
def _connect(root):
    # One database avoids thousands of tiny cache files on Windows.
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        root / "sources.sqlite3", timeout=0.2, isolation_level=None
    )
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source (path TEXT PRIMARY KEY, signature TEXT, summary TEXT)"
    )
    atexit.register(connection.close)
    return connection


def cached_summary(path, build):
    path = Path(path).resolve()
    stat = path.stat()
    signature = json.dumps(
        [
            SCHEMA,
            list(sys.version_info[:2]),
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        ]
    )
    root = (
        Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        / "odoo-module-migrator"
        / "cache"
    )
    connection = None
    try:
        connection = _connect(root)
        row = connection.execute(
            "SELECT summary FROM source WHERE path=? AND signature=?",
            (str(path), signature),
        ).fetchone()
        if row:
            return json.loads(row[0])
    except (OSError, sqlite3.Error, ValueError):
        pass
    summary = build(path)
    if connection is not None:
        try:
            connection.execute(
                "INSERT OR REPLACE INTO source VALUES (?, ?, ?)",
                (str(path), signature, json.dumps(summary)),
            )
        except sqlite3.Error:
            pass  # read-only or busy cache must not prevent analysis
    return summary
