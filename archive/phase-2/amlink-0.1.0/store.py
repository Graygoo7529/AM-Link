"""SQLite truth store, staged idempotency and one copy of each graph edge."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .errors import MemoryError
from .text import digest, dumps, indexed, now, terms

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests(
 user_id TEXT,request_id TEXT,payload_hash TEXT NOT NULL,status TEXT NOT NULL,
 response TEXT NOT NULL,planned INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,request_id));
CREATE TABLE IF NOT EXISTS raw_events(
 user_id TEXT,ref TEXT,request_id TEXT,session_id TEXT,ordinal INTEGER,
 role TEXT,text TEXT,source_time INTEGER,created_at TEXT,blocked INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,ref),UNIQUE(user_id,session_id,ordinal));
CREATE INDEX IF NOT EXISTS raw_session ON raw_events(user_id,session_id,ordinal);
CREATE TABLE IF NOT EXISTS working(user_id TEXT,session_id TEXT,processed_through INTEGER NOT NULL,
 PRIMARY KEY(user_id,session_id));
CREATE TABLE IF NOT EXISTS nodes(
 user_id TEXT,ref TEXT,kind TEXT,text TEXT,sources TEXT,status TEXT,
 time_expression TEXT,time_start TEXT,time_end TEXT,created_at TEXT,updated_at TEXT,
 PRIMARY KEY(user_id,ref));
CREATE TABLE IF NOT EXISTS edges(
 user_id TEXT,from_ref TEXT,to_ref TEXT,relation TEXT,sources TEXT,
 PRIMARY KEY(user_id,from_ref,to_ref,relation));
CREATE INDEX IF NOT EXISTS edges_in ON edges(user_id,to_ref,relation);
CREATE TABLE IF NOT EXISTS batches(
 user_id TEXT,request_id TEXT,number INTEGER,event_refs TEXT,context TEXT,mutation TEXT,
 vectors TEXT NOT NULL DEFAULT '{}',completed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,request_id,number));
CREATE TABLE IF NOT EXISTS vectors(user_id TEXT,ref TEXT,fingerprint TEXT,vector TEXT,
 PRIMARY KEY(user_id,ref));
CREATE TABLE IF NOT EXISTS blocks(user_id TEXT,ref TEXT,instructions TEXT,
 PRIMARY KEY(user_id,ref));
CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(user_id UNINDEXED,ref UNINDEXED,body);
"""


class Store:
    def __init__(self, path):
        self.path, self.mutex, self.owner = str(path), threading.RLock(), None
        if self.path != ":memory:":
            file = Path(path).resolve()
            file.parent.mkdir(parents=True, exist_ok=True)
            self.owner = file.with_suffix(file.suffix + ".owner").open("a+b")
            try:
                self.owner.seek(0)
                if self.owner.read(1) == b"":
                    self.owner.write(b"0")
                    self.owner.flush()
                self.owner.seek(0)
                if __import__("os").name == "nt":
                    import msvcrt
                    msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.owner.close()
                self.owner = None
                raise MemoryError("database_already_owned_use_one_worker", 503) from None
        try:
            self.db = sqlite3.connect(self.path, timeout=1, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, 1) or (version == 0 and tables):
                raise MemoryError("incompatible_database", 503)
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA user_version=1")
            self.db.commit()
        except BaseException:
            self.close()
            raise

    def close(self):
        if getattr(self, "db", None) is not None:
            self.db.close()
            self.db = None
        if self.owner is not None:
            self.owner.close()
            self.owner = None

    @contextmanager
    def transaction(self):
        with self.mutex:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def rows(self, sql, args=()):
        with self.mutex:
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def metadata(self, key, value):
        with self.transaction() as db:
            old = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if old and old[0] != value:
                raise MemoryError("index_configuration_mismatch", 503)
            db.execute("INSERT OR IGNORE INTO meta VALUES(?,?)", (key, value))

    @staticmethod
    def _index(db, user, ref, text):
        db.execute("DELETE FROM lexical WHERE user_id=? AND ref=?", (user, ref))
        db.execute("INSERT INTO lexical(user_id,ref,body) VALUES(?,?,?)", (user, ref, indexed(text)))

    def start_add(self, request):
        user, rid = request.user_id, request.request_id
        signature = digest(request.model_dump())
        response = {"success": True, "request_id": rid, "user_id": user, "session_id": request.session_id}
        with self.transaction() as db:
            old = db.execute("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid)).fetchone()
            if old:
                if old["payload_hash"] != signature:
                    raise MemoryError("idempotency_payload_conflict", 422)
                return dict(old), "cached" if old["status"] == "done" else "resumed"
            if db.execute("SELECT 1 FROM requests WHERE user_id=? AND status!='done'", (user,)).fetchone():
                raise MemoryError("prior_add_incomplete", 409)
            db.execute("INSERT INTO requests(user_id,request_id,payload_hash,status,response) VALUES(?,?,?,?,?)",
                       (user, rid, signature, "raw", dumps(response)))
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0) FROM raw_events WHERE user_id=? AND session_id=?",
                                 (user, request.session_id)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO working VALUES(?,?,0)", (user, request.session_id))
            for index, message in enumerate(request.messages):
                ref = "raw:" + digest([user, rid, index])[:32]
                db.execute("INSERT INTO raw_events(user_id,ref,request_id,session_id,ordinal,role,text,source_time,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (user, ref, rid, request.session_id, ordinal+index+1, message.role,
                            message.content, message.timestamp, now()))
                self._index(db, user, ref, message.content)
        return self.one("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid)), "none"

    def pending(self, user):
        rows = self.rows("""SELECT r.* FROM raw_events r JOIN working w
            ON r.user_id=w.user_id AND r.session_id=w.session_id
            WHERE r.user_id=? AND r.ordinal>w.processed_through AND r.blocked=0
            ORDER BY r.rowid""", (user,))
        return [self._raw(row) for row in rows]

    def plan_batches(self, user, rid, groups):
        with self.transaction() as db:
            for number, group in enumerate(groups):
                db.execute("INSERT INTO batches(user_id,request_id,number,event_refs) VALUES(?,?,?,?)",
                           (user, rid, number, dumps(group)))
            db.execute("UPDATE requests SET planned=1 WHERE user_id=? AND request_id=?", (user, rid))

    def batches(self, user, rid):
        result = self.rows("SELECT * FROM batches WHERE user_id=? AND request_id=? ORDER BY number", (user, rid))
        for row in result:
            for key in ("event_refs", "context", "mutation", "vectors"):
                row[key] = json.loads(row[key]) if row[key] is not None else None
        return result

    def save_stage(self, user, rid, number, column, value):
        if column not in {"context", "mutation", "vectors"}:
            raise ValueError("unknown stage")
        with self.transaction() as db:
            db.execute(f"UPDATE batches SET {column}=? WHERE user_id=? AND request_id=? AND number=?",
                       (dumps(value), user, rid, number))

    def finish(self, user, rid):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM batches WHERE user_id=? AND request_id=? AND completed=0", (user, rid)).fetchone():
                raise MemoryError("unfinished_add", 503)
            db.execute("UPDATE requests SET status='done' WHERE user_id=? AND request_id=?", (user, rid))

    def ready(self, user):
        if self.one("SELECT 1 FROM requests WHERE user_id=? AND status!='done' LIMIT 1", (user,)):
            raise MemoryError("user_add_incomplete", 425)

    @staticmethod
    def _raw(row):
        return {**row, "kind": "raw", "status": "tombstoned" if row["blocked"] else "active",
                "source_refs": [row["ref"]]}

    @staticmethod
    def _node(row):
        row = dict(row)
        row["source_refs"] = json.loads(row.pop("sources"))
        return row

    def get(self, user, ref, *, include_blocked=False):
        if not isinstance(ref, str) or not re.fullmatch(r"(?:raw|memory):[a-zA-Z0-9_-]+", ref):
            return None
        if ref.startswith("raw:"):
            row = self.one("SELECT * FROM raw_events WHERE user_id=? AND ref=?", (user, ref))
            value = self._raw(row) if row else None
        else:
            row = self.one("SELECT * FROM nodes WHERE user_id=? AND ref=?", (user, ref))
            value = self._node(row) if row else None
        if value and (include_blocked or value["status"] != "tombstoned"):
            return value
        return None

    def edges(self, user, ref, *, incoming=False):
        column = "to_ref" if incoming else "from_ref"
        result = self.rows(f"SELECT * FROM edges WHERE user_id=? AND {column}=? ORDER BY relation,from_ref,to_ref", (user, ref))
        # Symmetric edges are stored once, but are navigable from either endpoint.
        other = "from_ref" if incoming else "to_ref"
        result += self.rows(f"SELECT * FROM edges WHERE user_id=? AND {other}=? AND relation IN ('contradicts','same_event_as') ORDER BY relation,from_ref,to_ref", (user, ref))
        visible = []
        for edge in result:
            if not self.get(user, edge["from_ref"]) or not self.get(user, edge["to_ref"]):
                continue
            edge["source_refs"] = json.loads(edge.pop("sources"))
            if all(self.get(user, s) for s in edge["source_refs"]):
                visible.append(edge)
        return visible

    def lexical(self, user, query, limit, *, memories_only=False):
        tokens = list(dict.fromkeys(terms(query)))[:64]
        if not tokens:
            return []
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
        scope = " AND ref LIKE 'memory:%'" if memories_only else ""
        rows = self.rows(f"SELECT ref,bm25(lexical) AS rank FROM lexical WHERE lexical MATCH ? AND user_id=?{scope} ORDER BY rank,ref LIMIT ?", (match, user, limit))
        result = []
        for rank, row in enumerate(rows, 1):
            node = self.get(user, row["ref"])
            if node:
                result.append({**node, "score": 1/(60+rank), "lexical_rank": rank})
        return result

    def vector_rows(self, user, fingerprint):
        for row in self.rows("SELECT ref,vector FROM vectors WHERE user_id=? AND fingerprint=?", (user, fingerprint)):
            node = self.get(user, row["ref"])
            if node:
                yield node, json.loads(row["vector"])

    def source_states(self, user, source_ref):
        return [self._node(row) for row in self.rows("""SELECT DISTINCT n.* FROM nodes n,
            json_each(n.sources) s WHERE n.user_id=? AND s.value=? AND n.status IN ('superseded','conflict')""",
            (user, source_ref))]

    def commit_batch(self, user, rid, batch, prepared, fingerprint):
        """All derived data and cursor movement commit together; sources never mutate."""
        with self.transaction() as db:
            for item in prepared["items"]:
                old = db.execute("SELECT created_at,status FROM nodes WHERE user_id=? AND ref=?", (user, item["ref"])).fetchone()
                db.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (user, item["ref"], item["kind"], item["text"], dumps(item["source_refs"]),
                     old["status"] if old else "active", item.get("time_expression"), item.get("time_start"), item.get("time_end"),
                     old[0] if old else now(), now()))
                self._index(db, user, item["ref"], item["text"])
            for edge in prepared["links"]:
                previous = db.execute("SELECT sources FROM edges WHERE user_id=? AND from_ref=? AND to_ref=? AND relation=?",
                    (user, edge["from_ref"], edge["to_ref"], edge["relation"])).fetchone()
                sources = list(dict.fromkeys((json.loads(previous[0]) if previous else []) + edge["source_refs"]))
                db.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)", (user,
                    edge["from_ref"], edge["to_ref"], edge["relation"], dumps(sources)))
                if edge["relation"] == "supersedes":
                    db.execute("UPDATE nodes SET status='superseded' WHERE user_id=? AND ref=?", (user, edge["to_ref"]))
                elif edge["relation"] == "contradicts":
                    db.execute("UPDATE nodes SET status='conflict' WHERE user_id=? AND ref IN (?,?) AND status='active'",
                               (user, edge["from_ref"], edge["to_ref"]))
            for ref, vector in batch["vectors"].items():
                db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)", (user, ref, fingerprint, dumps(vector)))
            # Whole-source suppression is deliberate and conservative: summaries
            # depending on that source are invalidated, other raw sources survive.
            for removal in prepared["forget"]:
                blocked = set(removal["source_refs"]) | set(removal["instruction_refs"])
                for ref in blocked:
                    db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (user, ref, dumps(removal["instruction_refs"])))
                    db.execute("UPDATE raw_events SET blocked=1 WHERE user_id=? AND ref=?", (user, ref))
                    db.execute("DELETE FROM lexical WHERE user_id=? AND ref=?", (user, ref))
                blocked_memories = set(removal["memory_refs"])
                for node in db.execute("SELECT ref,sources FROM nodes WHERE user_id=?", (user,)).fetchall():
                    if blocked.intersection(json.loads(node["sources"])):
                        blocked_memories.add(node["ref"])
                for ref in blocked_memories:
                    db.execute("UPDATE nodes SET status='tombstoned' WHERE user_id=? AND ref=?", (user, ref))
                    db.execute("DELETE FROM lexical WHERE user_id=? AND ref=?", (user, ref))
                    db.execute("DELETE FROM vectors WHERE user_id=? AND ref=?", (user, ref))
            for ref in batch["event_refs"]:
                event = db.execute("SELECT session_id,ordinal FROM raw_events WHERE user_id=? AND ref=?", (user, ref)).fetchone()
                db.execute("UPDATE working SET processed_through=MAX(processed_through,?) WHERE user_id=? AND session_id=?",
                           (event["ordinal"], user, event["session_id"]))
            db.execute("UPDATE batches SET completed=1 WHERE user_id=? AND request_id=? AND number=?", (user, rid, batch["number"]))

    def snapshot(self, user):
        return {"nodes": [self._node(r) for r in self.rows("SELECT * FROM nodes WHERE user_id=? ORDER BY ref", (user,))],
                "edges": self.rows("SELECT * FROM edges WHERE user_id=? ORDER BY from_ref,to_ref", (user,)),
                "working": self.rows("SELECT * FROM working WHERE user_id=?", (user,))}
