"""SQLite truth store. No model calls or semantic mutations live here."""
from __future__ import annotations
import json
import os
import sqlite3
import struct
import threading
from contextlib import contextmanager
from pathlib import Path
from .errors import MemoryError
from .text import digest, dumps, now

VERSION=301
SCHEMA="""
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE requests(user_id TEXT,request_id TEXT,payload_hash TEXT,response TEXT,PRIMARY KEY(user_id,request_id));
CREATE TABLE sources(sequence INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,id TEXT UNIQUE,body TEXT,status TEXT NOT NULL);
CREATE INDEX sources_scope ON sources(user_id,sequence);
CREATE TABLE items(user_id TEXT,ref TEXT,kind TEXT,body TEXT,vector BLOB,status TEXT NOT NULL,PRIMARY KEY(user_id,ref));
CREATE INDEX items_scope ON items(user_id,status,kind);
CREATE TABLE working(user_id TEXT,ref TEXT,session_id TEXT,request_id TEXT,state TEXT,batch_id TEXT,PRIMARY KEY(user_id,ref));
CREATE TABLE batches(user_id TEXT,id TEXT,status TEXT,count INTEGER,error TEXT,created_at TEXT,PRIMARY KEY(user_id,id));
"""

class Store:
    def __init__(self,path):
        self.path=str(path)
        self.mutex=threading.RLock()
        self.owner=None
        self.db=None
        if self.path != ':memory:':
            file=Path(path).resolve()
            file.parent.mkdir(parents=True,exist_ok=True)
            self.owner=file.with_suffix(file.suffix+'.owner').open('a+b')
            try:
                self.owner.seek(0)
                if not self.owner.read(1):
                    self.owner.write(b'0'); self.owner.flush()
                self.owner.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.owner.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                self.owner.close(); self.owner=None
                raise MemoryError('database_already_owned_use_one_worker',503) from None
        try:
            self.db=sqlite3.connect(self.path,timeout=2,check_same_thread=False)
            self.db.row_factory=sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            version=self.db.execute('PRAGMA user_version').fetchone()[0]
            tables=self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version==0 and not tables:
                self.db.executescript(SCHEMA)
                self.db.execute(f'PRAGMA user_version={VERSION}')
            elif version != VERSION:
                raise MemoryError('incompatible_database_use_new_path',503)
            # A crashed one-shot batch is diagnostic, not silently retried on the next Add.
            self.db.execute("UPDATE batches SET status='interrupted',error='process_interrupted' WHERE status='running'")
            self.db.execute("UPDATE working SET state='unorganized' WHERE state='running'")
            self.db.commit()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.db is not None:
            self.db.close(); self.db=None
        if self.owner is not None:
            self.owner.close(); self.owner=None

    @contextmanager
    def transaction(self):
        with self.mutex:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def rows(self,sql,args=()):
        with self.mutex:
            return [dict(r) for r in self.db.execute(sql,args).fetchall()]

    def fingerprint(self,value):
        with self.transaction() as db:
            old=db.execute("SELECT value FROM meta WHERE key='embedding'").fetchone()
            if old and old[0]!=value:
                raise MemoryError('embedding_fingerprint_mismatch',503)
            db.execute("INSERT OR IGNORE INTO meta VALUES('embedding',?)",(value,))

    def replay(self,request):
        rows=self.rows('SELECT payload_hash,response FROM requests WHERE user_id=? AND request_id=?',
                       (request.user_id,request.request_id))
        if not rows:
            return None
        if rows[0]['payload_hash'] != digest(request.model_dump(mode='json')):
            raise MemoryError('idempotency_conflict',422)
        return json.loads(rows[0]['response'])

    @staticmethod
    def _insert_item(db,user,item):
        vector=item['vector']
        if len(vector)!=1024:
            raise MemoryError('embedding_dimensions',502)
        body={k:v for k,v in item.items() if k!='vector'}
        db.execute('INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,?)',
                   (user,item['ref'],item['kind'],dumps(body),struct.pack('<1024f',*vector),'active'))

    def confirmation(self,user):
        rows=self.rows('SELECT value FROM meta WHERE key=?',('confirmation:'+digest(user),))
        return json.loads(rows[0]['value']) if rows else None

    def accept(self,request,sources,items,blocked,confirmation=None):
        response=dict(success=True,request_id=request.request_id,user_id=request.user_id,session_id=request.session_id)
        with self.transaction() as db:
            old=self.replay(request)
            if old:
                return old
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',
                       (request.user_id,request.request_id,digest(request.model_dump(mode='json')),dumps(response)))
            key='confirmation:'+digest(request.user_id)
            if confirmation is None:
                db.execute('DELETE FROM meta WHERE key=?',(key,))
            else:
                db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key,dumps(confirmation)))
            for source in sources:
                status='blocked' if source['id'] in blocked else 'instruction' if source.get('instruction') else 'active'
                cursor=db.execute('INSERT INTO sources(user_id,id,body,status) VALUES(?,?,?,?)',
                           (request.user_id,source['id'],dumps(source),status))
                source['sequence']=cursor.lastrowid
                db.execute('UPDATE sources SET body=? WHERE id=?',(dumps(source),source['id']))
            sequences={s['id']:s['sequence'] for s in sources}
            for item in items:
                item['sequence']=sequences[item['sources'][0]]
                self._insert_item(db,request.user_id,item)
                db.execute('INSERT INTO working VALUES(?,?,?,?,?,?)',
                           (request.user_id,item['ref'],request.session_id,request.request_id,'pending',None))
            if blocked:
                for row in db.execute("SELECT ref,body FROM items WHERE user_id=? AND status='active'",(request.user_id,)).fetchall():
                    if set(json.loads(row['body'])['sources']) & set(blocked):
                        db.execute("UPDATE items SET status='blocked',vector=NULL WHERE user_id=? AND ref=?",(request.user_id,row['ref']))
                        db.execute("UPDATE working SET state='blocked' WHERE user_id=? AND ref=?",(request.user_id,row['ref']))
                for source in blocked:
                    db.execute("UPDATE sources SET status='blocked' WHERE user_id=? AND id=?",(request.user_id,source))
        return response

    def corpus(self,user):
        rows=self.rows("SELECT body,vector FROM items WHERE user_id=? AND status='active'",(user,))
        return [json.loads(r['body'])|{'vector':struct.unpack('<1024f',r['vector'])} for r in rows]

    def active_sources(self,user):
        return [json.loads(r['body']) for r in self.rows("SELECT body FROM sources WHERE user_id=? AND status='active' ORDER BY sequence",(user,))]

    def pending(self,user):
        rows=self.rows("""SELECT i.body,i.vector FROM working w JOIN items i ON w.user_id=i.user_id AND w.ref=i.ref
                          WHERE w.user_id=? AND w.state='pending' AND i.status='active' ORDER BY w.rowid""",(user,))
        return [json.loads(r['body'])|{'vector':struct.unpack('<1024f',r['vector'])} for r in rows]

    def begin_batch(self,user,items):
        refs=[x['ref'] for x in items]
        ident=digest(refs)[:24]
        with self.transaction() as db:
            db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(user,ident,'running',len(refs),None,now()))
            for ref in refs:
                db.execute("UPDATE working SET state='running',batch_id=? WHERE user_id=? AND ref=? AND state='pending'",
                           (ident,user,ref))
        return ident

    def finish_batch(self,user,batch,items,error=None):
        with self.transaction() as db:
            for item in items:
                self._insert_item(db,user,item)
            state='unorganized' if error else 'organized'
            db.execute('UPDATE working SET state=? WHERE user_id=? AND batch_id=?',(state,user,batch))
            db.execute('UPDATE batches SET status=?,error=? WHERE user_id=? AND id=?',
                       ('failed' if error else 'completed',error,user,batch))

    def stats(self,user):
        return {
            'sources':self.rows('SELECT status,COUNT(*) AS count FROM sources WHERE user_id=? GROUP BY status',(user,)),
            'items':self.rows('SELECT kind,status,COUNT(*) AS count FROM items WHERE user_id=? GROUP BY kind,status',(user,)),
            'working':self.rows('SELECT state,COUNT(*) AS count FROM working WHERE user_id=? GROUP BY state',(user,)),
            'batches':self.rows('SELECT status,COUNT(*) AS count FROM batches WHERE user_id=? GROUP BY status',(user,))
        }
