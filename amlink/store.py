"""Durable source, episode, graph and Reflection workspace store."""
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
 response TEXT NOT NULL,session_id TEXT NOT NULL,raw_refs TEXT NOT NULL DEFAULT '[]',
 episode_ref TEXT,reflection_watermark INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,request_id));
CREATE TABLE IF NOT EXISTS raw_events(
 user_id TEXT,ref TEXT,request_id TEXT,session_id TEXT,ordinal INTEGER,
 role TEXT,text TEXT,source_time INTEGER,created_at TEXT,blocked INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,ref),UNIQUE(user_id,ordinal));
CREATE INDEX IF NOT EXISTS raw_user_order ON raw_events(user_id,ordinal);
CREATE TABLE IF NOT EXISTS working(
 user_id TEXT PRIMARY KEY,accepted_through INTEGER NOT NULL DEFAULT 0,
 settled_through INTEGER NOT NULL DEFAULT 0,last_session TEXT,
 state TEXT NOT NULL DEFAULT 'stopped',context TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS nodes(
 user_id TEXT,ref TEXT,kind TEXT,text TEXT,sources TEXT,status TEXT,
 time_expression TEXT,time_start TEXT,time_end TEXT,created_at TEXT,updated_at TEXT,
 PRIMARY KEY(user_id,ref));
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(user_id,kind,status);
CREATE TABLE IF NOT EXISTS edges(
 user_id TEXT,from_ref TEXT,to_ref TEXT,relation TEXT,sources TEXT,
 PRIMARY KEY(user_id,from_ref,to_ref,relation));
CREATE INDEX IF NOT EXISTS edges_in ON edges(user_id,to_ref,relation);
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
            self.db = sqlite3.connect(self.path, timeout=2, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, 2) or (version == 0 and tables):
                raise MemoryError("incompatible_database", 503)
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA user_version=2")
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

    @staticmethod
    def _raw(row):
        return {**row, "kind": "raw", "status": "tombstoned" if row["blocked"] else "active",
                "source_refs": [row["ref"]]}

    @staticmethod
    def _node(row):
        row = dict(row)
        row["source_refs"] = json.loads(row.pop("sources"))
        return row

    def ensure_working(self, user):
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO working(user_id) VALUES(?)", (user,))

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
            state = db.execute("SELECT * FROM working WHERE user_id=?", (user,)).fetchone()
            if state is None:
                db.execute("INSERT INTO working(user_id) VALUES(?)", (user,))
                state = db.execute("SELECT * FROM working WHERE user_id=?", (user,)).fetchone()
            start = db.execute("SELECT COALESCE(MAX(ordinal),0) FROM raw_events WHERE user_id=?", (user,)).fetchone()[0]
            raw_refs = []
            for index, message in enumerate(request.messages):
                ref = "raw:" + digest([user, rid, index])[:32]
                raw_refs.append(ref)
                db.execute("INSERT INTO raw_events(user_id,ref,request_id,session_id,ordinal,role,text,source_time,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (user, ref, rid, request.session_id, start + index + 1, message.role,
                            message.content, message.timestamp, now()))
                self._index(db, user, ref, message.content)
            accepted = start + len(request.messages)
            db.execute("INSERT INTO requests(user_id,request_id,payload_hash,status,response,session_id,raw_refs) VALUES(?,?,?,?,?,?,?)",
                       (user, rid, signature, "accepted", dumps(response), request.session_id, dumps(raw_refs)))
            db.execute("UPDATE working SET accepted_through=?,last_session=? WHERE user_id=?",
                       (accepted, request.session_id, user))
            row = db.execute("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid)).fetchone()
        return dict(row), "none"

    def request(self, user, rid):
        row = self.one("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid))
        if row:
            row["raw_refs"] = json.loads(row["raw_refs"])
        return row

    def require_reflection(self, user, rid, watermark):
        with self.transaction() as db:
            db.execute("UPDATE requests SET reflection_watermark=MAX(reflection_watermark,?) WHERE user_id=? AND request_id=?",
                       (watermark, user, rid))

    def is_minimum_episode(self, user, ref):
        return self.one("SELECT 1 FROM requests WHERE user_id=? AND episode_ref=?", (user, ref)) is not None

    def request_complete(self, user, rid, episode_ref, watermark=0):
        with self.transaction() as db:
            db.execute("UPDATE requests SET status='done',episode_ref=?,reflection_watermark=? WHERE user_id=? AND request_id=?",
                       (episode_ref, watermark, user, rid))

    def raw(self, user, refs=None, *, pending=False):
        args = [user]
        where = "r.user_id=? AND r.blocked=0"
        if refs is not None:
            marks = ",".join("?" for _ in refs)
            where += f" AND r.ref IN ({marks})"
            args.extend(refs)
        if pending:
            where += " AND r.ordinal > (SELECT settled_through FROM working WHERE user_id=?)"
            args.append(user)
        rows = self.rows(f"SELECT r.* FROM raw_events r WHERE {where} ORDER BY r.ordinal", args)
        return [self._raw(row) for row in rows]

    def state(self, user):
        row = self.one("SELECT * FROM working WHERE user_id=?", (user,))
        if row is None:
            self.ensure_working(user)
            row = self.one("SELECT * FROM working WHERE user_id=?", (user,))
        row["context"] = json.loads(row["context"])
        return row

    def save_workspace(self, user, *, state=None, context=None):
        with self.transaction() as db:
            fields, values = [], []
            if state is not None:
                fields.append("state=?"); values.append(state)
            if context is not None:
                fields.append("context=?"); values.append(dumps(context))
            if fields:
                values.append(user)
                db.execute(f"UPDATE working SET {','.join(fields)} WHERE user_id=?", values)

    def commit_episode(self, user, rid, episode, vector, fingerprint):
        with self.transaction() as db:
            existing = db.execute("SELECT ref FROM nodes WHERE user_id=? AND ref=?", (user, episode["ref"])).fetchone()
            if existing is None:
                db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (user, episode["ref"], episode["kind"], episode["text"], dumps(episode["source_refs"]),
                            "active", None, None, None, now(), now()))
                self._index(db, user, episode["ref"], episode["text"])
            db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)",
                       (user, episode["ref"], fingerprint, dumps(vector)))
            db.execute("UPDATE requests SET episode_ref=? WHERE user_id=? AND request_id=?",
                       (episode["ref"], user, rid))

    def get(self, user, ref, *, include_blocked=False):
        if not isinstance(ref, str) or not re.fullmatch(r"(?:raw|memory):[\w-]+", ref):
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

    def nodes(self, user):
        return [self._node(row) for row in self.rows("SELECT * FROM nodes WHERE user_id=? AND status!='tombstoned' ORDER BY ref", (user,))]

    def edges(self, user, ref, *, incoming=False):
        column = "to_ref" if incoming else "from_ref"
        other = "from_ref" if incoming else "to_ref"
        result = self.rows(f"SELECT * FROM edges WHERE user_id=? AND {column}=? ORDER BY relation,from_ref,to_ref", (user, ref))
        result += self.rows(f"SELECT * FROM edges WHERE user_id=? AND {other}=? AND relation IN ('contradicts','same_event_as') ORDER BY relation,from_ref,to_ref", (user, ref))
        visible = []
        seen = set()
        for edge in result:
            key = (edge["from_ref"], edge["to_ref"], edge["relation"])
            if key in seen or not self.get(user, edge["from_ref"]) or not self.get(user, edge["to_ref"]):
                continue
            edge["source_refs"] = json.loads(edge.pop("sources"))
            if all(self.get(user, source) for source in edge["source_refs"]):
                visible.append(edge); seen.add(key)
        return visible

    def lexical(self, user, query, limit):
        tokens = list(dict.fromkeys(terms(query)))[:64]
        if not tokens:
            return []
        match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        rows = self.rows("SELECT ref,bm25(lexical) AS rank FROM lexical WHERE lexical MATCH ? AND user_id=? AND ref LIKE 'memory:%' ORDER BY rank,ref LIMIT ?",
                         (match, user, limit))
        result = []
        for rank, row in enumerate(rows, 1):
            node = self.get(user, row["ref"])
            if node:
                result.append({**node, "score": 1 / (60 + rank), "lexical_rank": rank})
        return result

    def vector_rows(self, user, fingerprint):
        for row in self.rows("SELECT ref,vector FROM vectors WHERE user_id=? AND fingerprint=?", (user, fingerprint)):
            node = self.get(user, row["ref"])
            if node:
                yield node, json.loads(row["vector"])

    def source_states(self, user, source_ref):
        return [self._node(row) for row in self.rows("SELECT DISTINCT n.* FROM nodes n,json_each(n.sources) s WHERE n.user_id=? AND s.value=? AND n.status IN ('superseded','conflict')", (user, source_ref))]

    def commit_mutation(self, user, mutation, *, watermark, fingerprint, vectors, context=None):
        with self.transaction() as db:
            for item in mutation["items"]:
                old = db.execute("SELECT created_at,status FROM nodes WHERE user_id=? AND ref=?", (user, item["ref"])).fetchone()
                if db.execute("SELECT 1 FROM requests WHERE user_id=? AND episode_ref=?", (user, item["ref"])).fetchone():
                    raise MemoryError("minimum_episode_immutable", 502)
                db.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (user, item["ref"], item["kind"], item["text"], dumps(item["source_refs"]),
                            old["status"] if old else "active", item.get("time_expression"), item.get("time_start"), item.get("time_end"),
                            old["created_at"] if old else now(), now()))
                self._index(db, user, item["ref"], item["text"])
            for edge in mutation["links"]:
                previous = db.execute("SELECT sources FROM edges WHERE user_id=? AND from_ref=? AND to_ref=? AND relation=?",
                                      (user, edge["from_ref"], edge["to_ref"], edge["relation"])).fetchone()
                sources = list(dict.fromkeys((json.loads(previous[0]) if previous else []) + edge["source_refs"]))
                db.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)", (user, edge["from_ref"], edge["to_ref"], edge["relation"], dumps(sources)))
                if edge["relation"] == "supersedes":
                    db.execute("UPDATE nodes SET status='superseded' WHERE user_id=? AND ref=?", (user, edge["to_ref"]))
                elif edge["relation"] == "contradicts":
                    db.execute("UPDATE nodes SET status='conflict' WHERE user_id=? AND ref IN (?,?) AND status='active'",
                               (user, edge["from_ref"], edge["to_ref"]))
            for ref, vector in vectors.items():
                db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)", (user, ref, fingerprint, dumps(vector)))
            for removal in mutation["forget"]:
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
            db.execute("UPDATE working SET settled_through=MAX(settled_through,?),state='stopped',context=? WHERE user_id=?",
                       (watermark, dumps(context or {}), user))

    def finish_minimum(self, user, rid, watermark=0, *, require_vector=False):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid)).fetchone()
            node = db.execute("SELECT * FROM nodes WHERE user_id=? AND ref=?", (user, row["episode_ref"])).fetchone() if row else None
            if not node:
                raise MemoryError("minimum_episode_incomplete", 503)
            if node["status"] != "tombstoned":
                if not db.execute("SELECT 1 FROM lexical WHERE user_id=? AND ref=?", (user, node["ref"])).fetchone():
                    raise MemoryError("minimum_index_incomplete", 503)
                vector = db.execute("SELECT vector FROM vectors WHERE user_id=? AND ref=?", (user, node["ref"])).fetchone()
                if require_vector and (not vector or not json.loads(vector[0])):
                    raise MemoryError("minimum_index_incomplete", 503)
            state = db.execute("SELECT settled_through FROM working WHERE user_id=?", (user,)).fetchone()
            if state[0] < max(row["reflection_watermark"], watermark):
                raise MemoryError("reflection_incomplete", 503)
            db.execute("UPDATE requests SET status='done' WHERE user_id=? AND request_id=?", (user, rid))

    def snapshot(self, user):
        state = self.state(user)
        return {"nodes": self.nodes(user), "edges": self.rows("SELECT * FROM edges WHERE user_id=? ORDER BY from_ref,to_ref", (user,)),
                "working": state}
