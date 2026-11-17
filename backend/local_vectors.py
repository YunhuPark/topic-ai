"""Local-only vector persistence. No HTTP server, plugins or model deserialization.

Implements the small collection interface used by this application. Distances
retain Chroma's default squared L2 semantics. Exact search streams vectors from
SQLite, trading approximate-index throughput for a smaller trust boundary.
"""
from contextlib import contextmanager
import heapq
import json
from pathlib import Path
import sqlite3

import numpy as np
from langchain_core.documents import Document


class LegacyIndexNeedsExport(RuntimeError):
    pass


class SQLiteVectorStore:
    FILENAME = 'topic-vectors.sqlite3'

    def __init__(self, directory, embedding_function, *, _migration=False, _filename=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / (_filename or self.FILENAME)
        self.embedding_function = embedding_function
        self._collection = self
        if not _migration and (self.directory / 'chroma.sqlite3').exists():
            ready = False
            if self.path.exists():
                with self._db() as conn:
                    try:
                        ready = conn.execute("select value from settings where key='legacy_complete'").fetchone() == ('yes',)
                    except sqlite3.OperationalError:
                        pass
            if not ready:
                raise LegacyIndexNeedsExport(
                    'Legacy index preserved. Stop writers and run migrate_vectors.py with the OLD environment before upgrading.')
        with self._db() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS vectors '
                         '(id TEXT PRIMARY KEY, document TEXT NOT NULL, metadata TEXT NOT NULL, vector BLOB NOT NULL)')

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _vector(value):
        vector = np.asarray(value, dtype='<f4')
        if vector.ndim != 1 or not 0 < vector.size <= 65536 or not np.isfinite(vector).all():
            raise ValueError('Expected a finite, nonempty one-dimensional embedding')
        return vector

    def upsert(self, *, ids, embeddings, documents, metadatas):
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise ValueError('Batch lengths differ')
        if not ids:
            return
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
            raise ValueError('IDs must be distinct nonempty strings')
        vectors = [self._vector(v) for v in embeddings]
        dimension = vectors[0].size
        if any(v.size != dimension for v in vectors):
            raise ValueError('Embedding dimensions differ')
        rows = [(i, text, json.dumps(meta, ensure_ascii=False, allow_nan=False), v.tobytes())
                for i, text, meta, v in zip(ids, documents, metadatas, vectors)]
        if any(not isinstance(text, str) or not isinstance(meta, dict)
               for text, meta in zip(documents, metadatas)):
            raise ValueError('Invalid document or metadata')
        with self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute("SELECT value FROM settings WHERE key='dimension'").fetchone()
            if existing and int(existing[0]) != dimension:
                raise ValueError('Embedding model/dimension differs from the existing index')
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('dimension', ?)", (str(dimension),))
            conn.executemany('INSERT INTO vectors VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
                             'document=excluded.document, metadata=excluded.metadata, vector=excluded.vector', rows)

    @staticmethod
    def _where(ids=None, where=None, where_document=None):
        clauses, params = [], []
        if ids is not None:
            if not ids:
                clauses.append('0')
            else:
                clauses.append('id IN (' + ','.join('?' for _ in ids) + ')')
                params.extend(ids)
        if where is not None:
            if not isinstance(where, dict):
                raise ValueError('Invalid metadata filter')
            for key, value in where.items():
                if not isinstance(key, str) or key.startswith('$') or not isinstance(value, (str, int, float, bool)):
                    raise ValueError('Only scalar metadata equality is supported')
                clauses.append('json_extract(metadata, ?) = ?')
                params.extend(['$.' + json.dumps(key), value])
        if where_document is not None:
            if set(where_document) != {'$contains'} or not isinstance(where_document['$contains'], str):
                raise ValueError('Only document $contains is supported')
            clauses.append('instr(document, ?) > 0')
            params.append(where_document['$contains'])
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), params

    def get(self, *, ids=None, include=None, limit=None, offset=0, where=None, where_document=None):
        include = ['documents', 'metadatas'] if include is None else include
        if not set(include).issubset({'documents', 'metadatas', 'embeddings'}):
            raise ValueError('Unsupported include field')
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError('Negative pagination')
        sql, params = self._where(ids, where, where_document)
        result = {'ids': [], **{field: [] for field in include}}
        with self._db() as conn:
            rows = conn.execute('SELECT id, document, metadata, vector FROM vectors' + sql +
                                ' ORDER BY id LIMIT ? OFFSET ?', [*params, -1 if limit is None else limit, offset])
            for ident, text, meta, blob in rows:
                result['ids'].append(ident)
                if 'documents' in include:
                    result['documents'].append(text)
                if 'metadatas' in include:
                    result['metadatas'].append(json.loads(meta))
                if 'embeddings' in include:
                    result['embeddings'].append(np.frombuffer(blob, dtype='<f4').tolist())
        return result

    def update(self, *, ids, metadatas):
        if len(ids) != len(metadatas):
            raise ValueError('Batch lengths differ')
        with self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for ident, updates in zip(ids, metadatas):
                row = conn.execute('SELECT metadata FROM vectors WHERE id=?', (ident,)).fetchone()
                if row is not None:
                    meta = json.loads(row[0])
                    meta.update(updates)
                    conn.execute('UPDATE vectors SET metadata=? WHERE id=?',
                                 (json.dumps(meta, ensure_ascii=False, allow_nan=False), ident))

    def delete(self, *, ids):
        with self._db() as conn:
            conn.executemany('DELETE FROM vectors WHERE id=?', [(i,) for i in ids])

    def count(self):
        with self._db() as conn:
            return conn.execute('SELECT count(*) FROM vectors').fetchone()[0]

    def similarity_search_with_score(self, query, k=4):
        if k <= 0:
            return []
        query_vector = self._vector(self.embedding_function.embed_query(query))
        def candidates(conn):
            for ident, text, meta, blob in conn.execute('SELECT id, document, metadata, vector FROM vectors'):
                vector = np.frombuffer(blob, dtype='<f4')
                if vector.size != query_vector.size:
                    raise ValueError('Query embedding dimension differs from stored embeddings')
                delta = vector.astype(np.float64) - query_vector
                yield float(np.dot(delta, delta)), ident, text, meta
        with self._db() as conn:
            nearest = heapq.nsmallest(k, candidates(conn))
        return [(Document(page_content=text, metadata=json.loads(meta)), score)
                for score, _, text, meta in nearest]
