"""Durable source, episode, graph and Reflection workspace store."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import math
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from .errors import MemoryError
from .text import digest, dumps, indexed, now, terms
from .evidence import episode_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests(
 user_id TEXT,request_id TEXT,payload_hash TEXT NOT NULL,status TEXT NOT NULL,
 response TEXT NOT NULL,session_id TEXT NOT NULL,raw_refs TEXT NOT NULL DEFAULT '[]',
 episode_ref TEXT,
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
CREATE TABLE IF NOT EXISTS reflection_plans(
 user_id TEXT,plan_id TEXT,from_ordinal INTEGER,through_ordinal INTEGER,
 groups_json TEXT NOT NULL,receipts TEXT NOT NULL DEFAULT '[]',progress TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(user_id,plan_id));
CREATE TABLE IF NOT EXISTS vectors(user_id TEXT,ref TEXT,fingerprint TEXT,vector TEXT,
 start INTEGER,end INTEGER,content_digest TEXT,PRIMARY KEY(user_id,ref,start));
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
            if version not in (0, 4) or (version == 0 and tables):
                raise MemoryError("incompatible_database", 503)
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA user_version=4")
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
    def _vectors(db, user, ref, fingerprint, parts):
        db.execute('DELETE FROM vectors WHERE user_id=? AND ref=?', (user, ref))
        for part in parts:
            db.execute('INSERT INTO vectors VALUES(?,?,?,?,?,?,?)',
                (user, ref, fingerprint, dumps(part['vector']), part['start'], part['end'], part['content_digest']))

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

    def prepare_add(self, request):
        """Prepare a write without exposing any material before indexing succeeds."""
        user, rid = request.user_id, request.request_id
        signature = digest(request.model_dump())
        response = {"success": True, "request_id": rid, "user_id": user, "session_id": request.session_id}
        with self.mutex:
            old = self.one("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid))
            if old:
                if old["payload_hash"] != signature:
                    raise MemoryError("idempotency_payload_conflict", 422)
                return dict(old), []
            start = self.one("SELECT COALESCE(MAX(ordinal),0) AS n FROM raw_events WHERE user_id=?", (user,))["n"]
            sources = []
            for index, message in enumerate(request.messages):
                ref = "raw:" + digest([user, rid, index])[:32]
                sources.append(dict(user_id=user, ref=ref, request_id=rid, session_id=request.session_id,
                    ordinal=start + index + 1, role=message.role, text=message.content,
                    source_time=message.timestamp, created_at=now(), kind='raw', source_refs=[ref]))
        return dict(user_id=user, request_id=rid, payload_hash=signature, status='prepared',
                    response=dumps(response), session_id=request.session_id, raw_refs=dumps([s['ref'] for s in sources])), sources

    def accept_add(self, prepared, sources, episode, vector, fingerprint, *, forgetting=(), retained_episodes=()):
        """The receipt, original, buffer and both indexes have ONE commit point."""
        user, rid = prepared['user_id'], prepared['request_id']
        with self.transaction() as db:
            old = db.execute('SELECT payload_hash FROM requests WHERE user_id=? AND request_id=?', (user, rid)).fetchone()
            if old:
                if old[0] != prepared['payload_hash']:
                    raise MemoryError('idempotency_payload_conflict', 422)
                return
            db.execute('INSERT OR IGNORE INTO working(user_id) VALUES(?)', (user,))
            for source in sources:
                db.execute("INSERT INTO raw_events(user_id,ref,request_id,session_id,ordinal,role,text,source_time,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           tuple(source[k] for k in ('user_id','ref','request_id','session_id','ordinal','role','text','source_time','created_at')))
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)", (user, episode['ref'], 'episode', episode['text'],
                       dumps(episode['source_refs']), 'active', None, None, None, now(), now()))
            self._index(db, user, episode['ref'], episode['text'])
            if vector:
                self._vectors(db, user, episode['ref'], fingerprint, vector)
            db.execute("INSERT INTO requests(user_id,request_id,payload_hash,status,response,session_id,raw_refs,episode_ref) VALUES(?,?,?,?,?,?,?,?)",
                       (user, rid, prepared['payload_hash'], 'done', prepared['response'], prepared['session_id'], prepared['raw_refs'], episode['ref']))
            db.execute("UPDATE working SET accepted_through=?,last_session=? WHERE user_id=?",
                       (sources[-1]['ordinal'], prepared['session_id'], user))
            self._forget(db, user, forgetting)
            for retained in retained_episodes:
                item=retained['episode']
                db.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (user,item['ref'],'episode',item['text'],dumps(item['source_refs']),'active',None,None,None,now(),now()))
                self._index(db,user,item['ref'],item['text'])
                if retained['vectors']:
                    self._vectors(db,user,item['ref'],fingerprint,retained['vectors'])

    def request(self, user, rid):
        row = self.one("SELECT * FROM requests WHERE user_id=? AND request_id=?", (user, rid))
        if row:
            row["raw_refs"] = json.loads(row["raw_refs"])
        return row

    def is_minimum_episode(self, user, ref):
        return self.one("SELECT 1 FROM requests WHERE user_id=? AND episode_ref=?", (user, ref)) is not None

    def old_scope_empty(self, user, before):
        # Conservative: any active node with a valid old source makes the scope
        # nonempty, including a mixed minimum episode's old projection.
        return self.one("""SELECT 1 FROM nodes n,json_each(n.sources) s
            JOIN raw_events r ON r.ref=s.value AND r.user_id=n.user_id
            WHERE n.user_id=? AND n.status!='tombstoned' AND r.blocked=0
            AND r.ordinal<? LIMIT 1""", (user, before)) is None

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

    def lexical(self, user, query, limit, *, before=None):
        tokens = list(dict.fromkeys(terms(query)))[:64]
        if not tokens:
            return []
        match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        eligible = "" if before is None else " AND ref IN (SELECT n.ref FROM nodes n,json_each(n.sources) s JOIN raw_events r ON r.ref=s.value AND r.user_id=n.user_id WHERE n.user_id=? AND r.ordinal<? AND r.blocked=0)"
        args = (match, user, limit) if before is None else (match, user, user, before, -1)
        rows = self.rows("SELECT ref,bm25(lexical) AS rank FROM lexical WHERE lexical MATCH ? AND user_id=? AND ref LIKE 'memory:%'" + eligible + " ORDER BY rank,ref LIMIT ?", args)
        if before is not None:
            scoped = []
            for row in rows:
                node = self.get(user, row["ref"])
                if not node:
                    continue
                sources = self.raw(user, node["source_refs"])
                old = [source for source in sources if source["ordinal"] < before]
                if len(old) != len(sources):
                    if not self.is_minimum_episode(user, node["ref"]):
                        continue
                    node = {**node, "text": episode_text(old), "source_refs": [source["ref"] for source in old]}
                words = Counter(terms(node["text"]))
                if set(tokens).intersection(words):
                    scoped.append((node, words))
            # Mixed episodes must be ranked using only their old projection;
            # future keyword frequency must not influence old-memory top-N.
            count = len(scoped)
            avg = sum(sum(words.values()) for _, words in scoped) / max(1, count)
            frequency = Counter(word for _, words in scoped for word in set(words))
            def score(pair):
                node, words = pair
                length = sum(words.values())
                return sum(math.log(1 + (count - frequency[word] + .5) / (frequency[word] + .5)) *
                    (words[word] * 2.2) / (words[word] + 1.2 * (.25 + .75 * length / max(1, avg)))
                    for word in tokens if words[word])
            ordered = sorted(scoped, key=lambda pair: (-score(pair), pair[0]["ref"]))[:limit]
            return [{**node, "score": 1 / (60 + rank), "lexical_rank": rank, "scope_before": before}
                    for rank, (node, _) in enumerate(ordered, 1)]
        result = []
        for rank, row in enumerate(rows, 1):
            node = self.get(user, row["ref"])
            if node:
                result.append({**node, "score": 1 / (60 + rank), "lexical_rank": rank})
        return result

    def vector_rows(self, user, fingerprint, *, before=None, refs=None):
        for row in self.rows("SELECT * FROM vectors WHERE user_id=? AND fingerprint=? ORDER BY ref,start", (user, fingerprint)):
            if refs is not None and row['ref'] not in refs:
                continue
            node = self.get(user, row["ref"])
            if node and (before is None or (sources := self.raw(user, node["source_refs"])) and all(source["ordinal"] < before for source in sources)):
                if row['content_digest'] != digest(node['text']):
                    raise MemoryError('vector_content_mismatch', 503)
                yield {**node, 'embedding_range': {k: row[k] for k in ('start', 'end', 'content_digest')}}, json.loads(row["vector"])

    def source_states(self, user, source_ref):
        return [self._node(row) for row in self.rows("SELECT DISTINCT n.* FROM nodes n,json_each(n.sources) s WHERE n.user_id=? AND s.value=? AND n.status IN ('superseded','conflict')", (user, source_ref))]

    def reflection_plan(self, user, plan_id=None):
        plans = self.reflection_plans(user)
        return next((p for p in plans if p['plan_id'] == plan_id), None) if plan_id else next(
            (p for p in plans if len(p['receipts']) < len(p['groups'])), None)

    def reflection_plans(self, user):
        rows = self.rows('SELECT * FROM reflection_plans WHERE user_id=? ORDER BY from_ordinal', (user,))
        for row in rows:
            row['groups'] = json.loads(row.pop('groups_json'))
            row['receipts'] = json.loads(row['receipts'])
            row['progress'] = json.loads(row['progress'])
        return rows

    def unplanned(self, user):
        assigned = {ref for p in self.reflection_plans(user) for g in p['groups'] for ref in g['source_refs']}
        return [row for row in self.raw(user, pending=True) if row['ref'] not in assigned]

    def maintenance_summary(self, user):
        plans = self.reflection_plans(user)
        return {'groups_completed': sum(len(p['receipts']) for p in plans),
                'groups_unfinished': sum(len(p['groups']) - len(p['receipts']) for p in plans),
                'groups_with_committed_nodes': sum(bool(g.get('context', {}).get('committed_node_refs'))
                    for p in plans for g in p['progress'].values()),
                'unplanned_messages': len(self.unplanned(user)),
                'settled_through': self.state(user)['settled_through']}

    def group_progress(self, user, group, progress):
        with self.transaction() as db:
            row = db.execute('SELECT progress FROM reflection_plans WHERE user_id=? AND plan_id=?',
                             (user, group['plan_id'])).fetchone()
            if row is None:
                raise MemoryError('reflection_plan_missing', 503)
            values = json.loads(row[0])
            values[str(group['index'])] = progress
            db.execute('UPDATE reflection_plans SET progress=? WHERE user_id=? AND plan_id=?',
                       (dumps(values), user, group['plan_id']))

    def freeze_plan(self, user, plan):
        with self.transaction() as db:
            db.execute('INSERT INTO reflection_plans VALUES(?,?,?,?,?,?,?)',
                       (user, plan['plan_id'], plan['from_ordinal'], plan['through_ordinal'], dumps(plan['groups']), '[]', '{}'))

    @staticmethod
    def _forget(db, user, removals):
        for removal in removals:
            blocked = set(removal['source_refs']) | set(removal['instruction_refs'])
            for ref in blocked:
                db.execute('INSERT OR IGNORE INTO blocks VALUES(?,?,?)', (user, ref, dumps(removal['instruction_refs'])))
                db.execute('UPDATE raw_events SET blocked=1 WHERE user_id=? AND ref=?', (user, ref))
                db.execute('DELETE FROM lexical WHERE user_id=? AND ref=?', (user, ref))
            memories = set(removal['memory_refs'])
            for node in db.execute('SELECT ref,sources FROM nodes WHERE user_id=?', (user,)).fetchall():
                if blocked.intersection(json.loads(node['sources'])):
                    memories.add(node['ref'])
            for ref in memories:
                db.execute("UPDATE nodes SET status='tombstoned' WHERE user_id=? AND ref=?", (user, ref))
                db.execute('DELETE FROM lexical WHERE user_id=? AND ref=?', (user, ref))
                db.execute('DELETE FROM vectors WHERE user_id=? AND ref=?', (user, ref))

    def _advance_watermark(self, db, user):
        # Completed groups above a gap stay complete, but never conceal the gap.
        settled = db.execute('SELECT settled_through FROM working WHERE user_id=?', (user,)).fetchone()[0]
        for plan in db.execute('SELECT * FROM reflection_plans WHERE user_id=? AND through_ordinal>? ORDER BY from_ordinal', (user, settled)):
            if len(json.loads(plan['receipts'])) != len(json.loads(plan['groups_json'])):
                break
            if db.execute('SELECT 1 FROM raw_events WHERE user_id=? AND blocked=0 AND ordinal>? AND ordinal<? LIMIT 1',
                          (user, settled, plan['from_ordinal'])).fetchone():
                break
            settled = plan['through_ordinal']
        return settled

    def commit_mutation(self, user, mutation, *, watermark, fingerprint, vectors, context=None, group=None, checkpoint=None):
        with self.transaction() as db:
            if checkpoint:
                if group or mutation['links'] or mutation['forget']:
                    raise MemoryError('reflection_checkpoint_not_independent', 409)
                row = db.execute('SELECT progress,receipts FROM reflection_plans WHERE user_id=? AND plan_id=?',
                                 (user, checkpoint['plan_id'])).fetchone()
                if row is None or any(r['index']==checkpoint['index'] for r in json.loads(row['receipts'])):
                    raise MemoryError('reflection_checkpoint_plan_invalid', 409)
                progress = json.loads(row['progress'])
                entry = progress.setdefault(str(checkpoint['index']), {})
                entry.update(context=context, committed_node_refs=context.get('committed_node_refs', []),
                             node_checkpoint=True, input_signature=checkpoint.get('input_signature'))
                db.execute('UPDATE reflection_plans SET progress=? WHERE user_id=? AND plan_id=?',
                           (dumps(progress), user, checkpoint['plan_id']))
                watermark = self.state(user)['settled_through']
            if group:
                plan = db.execute('SELECT * FROM reflection_plans WHERE user_id=? AND plan_id=?', (user, group['plan_id'])).fetchone()
                if plan is None:
                    raise MemoryError('reflection_plan_missing', 409)
                receipts = json.loads(plan['receipts'])
                if (type(group['index']) is not int or not 0 <= group['index'] < len(json.loads(plan['groups_json']))
                        or any(r['index'] == group['index'] for r in receipts)):
                    raise MemoryError('reflection_group_already_committed_or_invalid', 409)
                receipts.append({'index': group['index'], 'refs': list(dict.fromkeys(
                    [i['ref'] for i in mutation['items']] + group.get('committed_node_refs', []))),
                                 'mutation_digest': digest(mutation), 'completion': group.get('completion', {'outcome': 'mutation'})})
                progress = json.loads(plan['progress'])
                progress.pop(str(group['index']), None)
                db.execute('UPDATE reflection_plans SET receipts=?,progress=? WHERE user_id=? AND plan_id=?',
                           (dumps(receipts), dumps(progress), user, group['plan_id']))
                watermark = self._advance_watermark(db, user)
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
                self._vectors(db, user, ref, fingerprint, vector)
            self._forget(db, user, mutation["forget"])
            db.execute("UPDATE working SET settled_through=MAX(settled_through,?),state='stopped',context=? WHERE user_id=?",
                       (watermark, dumps(context or {}), user))

    def snapshot(self, user):
        state = self.state(user)
        return {"nodes": self.nodes(user), "edges": self.rows("SELECT * FROM edges WHERE user_id=? ORDER BY from_ref,to_ref", (user,)),
                "working": state}
