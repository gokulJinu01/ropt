"""Local journal for persistent memories, request limits and usage units.

Usage units are not a dollar invoice. Set monetary limits at your providers.
"""

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY, pet TEXT NOT NULL, started REAL NOT NULL,
                cloud INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'reserved',
                usage TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS turns_pet_time ON turns(pet, started);
            CREATE TABLE IF NOT EXISTS exchanges (
                id INTEGER PRIMARY KEY, pet TEXT NOT NULL, created REAL NOT NULL,
                user_text TEXT NOT NULL, reply TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS memories_pet ON exchanges(pet, created);
        """)

    def reserve(self, pet, hourly, daily_cloud, cloud, *, now=None):
        now = time.time() if now is None else now
        day = (
            datetime.fromtimestamp(now, timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            hour = self.db.execute(
                "SELECT COUNT(*) FROM turns WHERE pet=? AND started>?",
                (pet, now - 3600),
            ).fetchone()[0]
            used = self.db.execute(
                "SELECT COUNT(*) FROM turns WHERE pet=? AND cloud=1 AND started>=?",
                (pet, day),
            ).fetchone()[0]
            if hour >= hourly or (cloud and used >= daily_cloud):
                self.db.rollback()
                return None
            row = self.db.execute(
                "INSERT INTO turns(pet, started, cloud) VALUES(?,?,?)",
                (pet, now, int(cloud)),
            )
            self.db.commit()
            return row.lastrowid
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, turn_id, status, usage):
        if turn_id is not None:
            with self.db:
                self.db.execute(
                    "UPDATE turns SET status=?, usage=? WHERE id=?",
                    (status, json.dumps(usage), turn_id),
                )

    def save(self, pet, user_text, reply):
        with self.db:
            self.db.execute(
                "INSERT INTO exchanges(pet, created, user_text, reply) VALUES(?,?,?,?)",
                (pet, time.time(), user_text[:4000], reply[:2000]),
            )

    def recall(self, pet, query, budget):
        rows = self.db.execute(
            "SELECT created,user_text,reply FROM exchanges WHERE pet=? ORDER BY id DESC LIMIT 100",
            (pet,),
        ).fetchall()
        terms = set(re.findall(r"\w+", query.casefold())) - {
            "the",
            "a",
            "i",
            "you",
            "my",
            "is",
            "what",
            "do",
        }
        ranked = sorted(
            enumerate(rows),
            key=lambda item: (
                -len(terms & set(re.findall(r"\w+", item[1][1].casefold()))),
                item[0],
            ),
        )
        result = b""
        for _, (created, user, reply) in ranked[:6]:
            stamp = datetime.fromtimestamp(created, timezone.utc).isoformat(
                timespec="seconds"
            )
            line = f"[{stamp}] Human: {user}\nPet: {reply}\n".encode()
            result += line[: max(0, budget - len(result))]
            if len(result) >= budget:
                break
        return result.decode("utf-8", errors="ignore")

    def summary(self, pet):
        rows = self.db.execute(
            "SELECT status, usage FROM turns WHERE pet=?", (pet,)
        ).fetchall()
        totals = {}
        for _, raw in rows:
            for key, value in json.loads(raw).items():
                if isinstance(value, (int, float)):
                    totals[key] = round(totals.get(key, 0) + value, 3)
        return {
            "attempts": len(rows),
            "completed": sum(status == "complete" for status, _ in rows),
            "units": totals,
        }

    def close(self):
        self.db.close()
