"""One-time OFFLINE export using the old trusted environment, before upgrading.

Stop all index writers first. Copies existing embeddings, documents and ACL
metadata without generation/provider calls. The legacy index is never deleted.
The application refuses to silently replace an unexported legacy index.
"""
import argparse
import os
from pathlib import Path
import uuid

from local_vectors import SQLiteVectorStore


def migrate_collection(collection, directory, batch_size=256):
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / SQLiteVectorStore.FILENAME
    if destination.exists():
        raise FileExistsError('Destination already exists; refusing to overwrite an index')
    temporary_name = '.vector-export-' + uuid.uuid4().hex + '.sqlite3'
    store = SQLiteVectorStore(directory, None, _migration=True, _filename=temporary_name)
    try:
        expected = collection.count()
        for offset in range(0, expected, batch_size):
            batch = collection.get(offset=offset, limit=batch_size,
                                   include=['embeddings', 'documents', 'metadatas'])
            store.upsert(ids=batch['ids'], embeddings=batch['embeddings'],
                         documents=batch['documents'], metadatas=batch['metadatas'])
        if store.count() != expected or collection.count() != expected:
            raise ValueError('Source changed or export is incomplete; stop writers and retry')
        with store._db() as conn:
            conn.execute("INSERT INTO settings VALUES ('legacy_complete', 'yes')")
        with store._db() as conn:
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise RuntimeError('Export database is still busy')
            conn.execute('PRAGMA journal_mode=DELETE')
        # Exclusive atomic publication; never overwrite a concurrently created DB.
        os.link(store.path, destination)
        return expected
    finally:
        for suffix in ['', '-wal', '-shm', '-journal']:
            Path(str(store.path) + suffix).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    # Available only in the OLD application environment. Not a runtime dependency.
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=args.directory, settings=Settings(anonymized_telemetry=False))
    collection = client.get_collection('topic_documents', embedding_function=None)
    print(f'Exported {migrate_collection(collection, args.directory)} vectors; legacy data retained.')


if __name__ == '__main__':
    main()
