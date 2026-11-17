import concurrent.futures
import importlib.util
import json
from pathlib import Path

import pytest

from local_vectors import SQLiteVectorStore, LegacyIndexNeedsExport
from migrate_vectors import migrate_collection


class Embeddings:
    def embed_query(self, query):
        return [1.0, 0.0]


def store(path):
    return SQLiteVectorStore(path, Embeddings())


def seed(db):
    db._collection.upsert(ids=['a', 'b'], embeddings=[[1, 0], [0, 1]],
                          documents=['Alpha policy', 'Beta policy'],
                          metadatas=[{'id': 'a', 'source': 'gitlab', 'syncedBy': ',1,'},
                                     {'id': 'b', 'source': 'slack', 'syncedBy': ',2,'}])


def test_persistence_and_existing_squared_l2_distance(tmp_path):
    seed(store(tmp_path))
    result = store(tmp_path).similarity_search_with_score('query', k=2)
    assert [(d.metadata['id'], score) for d, score in result] == [('a', 0.0), ('b', 2.0)]
    assert result[0][0].page_content == 'Alpha policy'


def test_filters_pagination_and_parameterized_values(tmp_path):
    db = store(tmp_path)
    seed(db)
    assert db._collection.get(where={'source': 'gitlab'})['ids'] == ['a']
    assert db._collection.get(where_document={'$contains': 'Beta'})['ids'] == ['b']
    assert db._collection.get(limit=1, offset=1)['ids'] == ['b']
    assert db._collection.get(where={'source': "' OR 1=1 --"})['ids'] == []
    assert db._collection.get(ids=['a'])['metadatas'][0]['syncedBy'] == ',1,'
    with pytest.raises(ValueError):
        db._collection.get(where_document={'$unsupported': 'Alpha'})


def test_metadata_update_preserves_vector_and_document_and_delete(tmp_path):
    db = store(tmp_path)
    seed(db)
    db._collection.update(ids=['a'], metadatas=[{'syncedBy': ',1,3,'}])
    hit, score = db.similarity_search_with_score('query', k=1)[0]
    assert hit.metadata['source'] == 'gitlab'
    assert hit.metadata['syncedBy'] == ',1,3,'
    assert hit.page_content == 'Alpha policy' and score == 0
    db.delete(ids=['a'])
    assert db._collection.get()['ids'] == ['b']


@pytest.mark.parametrize('bad', [[1], [float('nan'), 0], [float('inf'), 0]])
def test_invalid_batches_do_not_partially_write(tmp_path, bad):
    db = store(tmp_path)
    seed(db)
    with pytest.raises(ValueError):
        db._collection.upsert(ids=['new', 'bad'], embeddings=[[1, 0], bad],
                              documents=['new', 'bad'], metadatas=[{}, {}])
    assert db._collection.get()['ids'] == ['a', 'b']


def test_independent_connections_share_persistent_writes(tmp_path):
    db = store(tmp_path)
    def write(i):
        store(tmp_path)._collection.upsert(ids=[str(i)], embeddings=[[1, 0]],
                                           documents=[str(i)], metadatas=[{'id': str(i)}])
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write, range(20)))
    assert len(db._collection.get()['ids']) == 20


class LegacyCollection:
    def __init__(self, bad=False):
        self.bad = bad
    def count(self):
        return 2
    def get(self, offset, limit, include):
        data = {'ids': ['a', 'b'], 'embeddings': [[1, 0], [0, 1]],
                'documents': ['Alpha policy', 'Beta policy'],
                'metadatas': [{'id': 'a', 'permissionPath': '/exact', 'syncedBy': ',1,'}, {'id': 'b'}]}
        if self.bad:
            data['embeddings'][1] = [float('nan'), 0]
        return {key: value[offset:offset+limit] for key, value in data.items()}


def test_legacy_export_preserves_vectors_acl_and_original_database(tmp_path):
    old = tmp_path / 'chroma.sqlite3'
    old.write_bytes(b'original database remains untouched')
    with pytest.raises(LegacyIndexNeedsExport):
        store(tmp_path)
    migrate_collection(LegacyCollection(), tmp_path, batch_size=1)
    assert old.read_bytes() == b'original database remains untouched'
    db = store(tmp_path)
    result = db._collection.get(ids=['a'])
    assert result['metadatas'][0]['permissionPath'] == '/exact'
    assert result['metadatas'][0]['syncedBy'] == ',1,'
    assert db.similarity_search_with_score('query', k=1)[0][1] == 0
    with pytest.raises(FileExistsError):
        migrate_collection(LegacyCollection(), tmp_path)


def test_failed_migration_never_marks_an_incomplete_index_ready(tmp_path):
    (tmp_path / 'chroma.sqlite3').write_bytes(b'original')
    with pytest.raises(ValueError):
        migrate_collection(LegacyCollection(bad=True), tmp_path, batch_size=1)
    with pytest.raises(LegacyIndexNeedsExport):
        store(tmp_path)
