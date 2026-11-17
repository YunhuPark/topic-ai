# Security upgrade (2026-11)

Back up `app.db` and the Chroma directory before upgrading. `db.init_db()` adds
`login_identities` transactionally; it does not guess identities from email.

## Existing login accounts

New Google and Kakao accounts are keyed by provider and stable subject. Provider
email changes never switch a session into another user's account. A verified
provider email does not prove who created an existing password account, so an
email collision is rejected with a recovery message. Password login continues
to work for existing password accounts. Google/Kakao accounts created before
this version have no trustworthy provider subject recorded: their social login
is intentionally blocked until ownership is independently established.

Email/password signup remains an **unverified identity**. This change does not
implement email verification or claim that the user owns the supplied address.
`SIGNUP_ALLOWED_DOMAINS` only filters strings; it is not proof of organization
membership. Teams require an explicit invite code and membership is keyed by
user ID, never a matching email or domain. Never grant trusted privileges based
on these unverified addresses.

For recovery, the administrator must verify the **existing account** and the
provider's subject independently (for example, organization identity checks and
the provider's authenticated profile). Never bind an identity on an emailed
address or a subject supplied without validation. Back up the database, revoke
existing sessions by rotating `JWT_SECRET`, and reset an account's password to
an unusable random hash if it was created/controlled by an attacker. Only then
insert the verified `(provider, subject, user_id)` into `login_identities` in a
transaction. Investigate external linked accounts and access history before
restoring a previously merged account. Automatic migration based only on email
would recreate the vulnerability; this operational recovery is not performed
by this source change.

## Existing GitLab index

Old GitLab metadata has project-only ACLs and can contain internal notes or
repository README content. It is denied until reindexed. The next source sync
ignores its old incremental timestamps and rebuilds versioned permissions;
operators may trigger **Sync now** after deploying. Do not manually set the
permission version on old records. New issue/MR results are checked at their
exact resource, repository files at their exact file/ref, and project metadata
contains only the project description. Internal notes are excluded because their
permissions can be narrower than their parent issue. Exact permission paths are
also used for re-summarization and permission cache keys.

## Team dashboard

Team totals remain aggregate counts. Topic titles list only documents imported
by the viewing user; team membership does not grant access to another member's
personal source titles. Search still checks original-source access for content.


## Remove the vulnerable Chroma runtime

The application now persists vectors in `topic-vectors.sqlite3`, using SQLite and
NumPy. No vector HTTP API, dynamic embedding plugin, remote model repository,
trusted-code switch or pickle format is provided. Squared L2 distances match the
previous default; exact scanning uses memory bounded by one vector plus the top-k
results, and is intended for this application's local corpus. Very large indexes
may need a separately reviewed scalable backend.

### Existing index: export BEFORE upgrading

1. Stop the API and all sync/index writers. Back up `app.db` and the entire
   `CHROMA_PERSIST_DIR` directory. Keep the old trusted virtual environment.
2. Using that OLD environment (which already has Chroma, NumPy and LangChain), run
   the new offline tool from the backend directory:
   `python migrate_vectors.py --directory /absolute/path/to/chroma_db`
3. The exporter copies existing vectors, documents and metadata including source
   ACL paths and owner lists. It calls no embedding/model provider. Source data is
   retained, partial exports are not published, and an existing destination is
   never overwritten. Writers must remain stopped until export completes.
4. Create a CLEAN new environment from the updated `requirements.txt`; do not
   reuse an old environment that retains unlisted vulnerable packages. Then start
   the API with the same `CHROMA_PERSIST_DIR`. Keep the old backup offline until
   search and source access are validated. Do not expose the old Chroma server.

A fresh installation needs no export. If a legacy `chroma.sqlite3` is present
without a completed export, startup of the vector store fails closed with a clear
migration error; it does not erase the old index, silently start an empty index,
or regenerate paid embeddings. The one-time exporter imports Chroma only in the
old offline environment; Chroma is absent from application runtime requirements.

Verification: local store persistence/filters/atomic writes/parallel connections,
incremental real ingestion and existing auth/ACL tests pass. An actual Chroma
1.5.9 temporary collection was exported and checked for retained vectors,
documents, ACL metadata and distances without provider calls. Live production
index export requires access to that host and is not implied by these tests.
