import types
import pytest


def google_login(auth, db, email, subject):
    from unittest.mock import patch
    exchange = types.SimpleNamespace(ok=True, json=lambda: {"access_token": "test-access"})
    identity = types.SimpleNamespace(status_code=200, json=lambda: {
        "email": email, "sub": subject, "email_verified": True,
    })
    with patch.object(auth.http_requests, "post", return_value=exchange), patch.object(auth.http_requests, "get", return_value=identity):
        return auth.complete_google_login("test-code", db.create_oauth_state(0, "google_login"))


@pytest.mark.parametrize("provider", ["google", "kakao"])
def test_social_login_never_joins_an_email_only_password_account(app_modules, provider):
    _, auth, db, _ = app_modules
    auth.signup(" Victim@Example.com ", "attacker-password")
    if provider == "google":
        assert google_login(auth, db, "victim@example.com", "google-subject")["ok"] is False
    else:
        with pytest.raises(auth.AuthError):
            auth._get_or_create_kakao_user(12345, "victim@example.com")


def test_social_identity_survives_email_change_without_joining_other_account(app_modules):
    _, auth, db, _ = app_modules
    first = google_login(auth, db, "first@example.com", "subject-A")
    auth.signup("second@example.com", "another-password")
    again = google_login(auth, db, "second@example.com", "subject-A")
    assert auth.verify_token(again["token"])["sub"] == auth.verify_token(first["token"])["sub"]
    assert google_login(auth, db, "first@example.com", "subject-B")["ok"] is False


def test_kakao_subject_without_email_is_not_a_claimable_email_alias(app_modules):
    _, auth, _, _ = app_modules
    auth.signup("kakao-12345@no-email.topicthread.local", "attacker-password")
    with pytest.raises(auth.AuthError):
        auth._get_or_create_kakao_user(12345, None)


def test_confidential_gitlab_issue_is_checked_at_issue_endpoint(app_modules, monkeypatch):
    main, _, _, _ = app_modules
    metadata = {"id": "gitlab-group/project#issue-7", "tags": "gitlab,group/project,issue",
                "permissionVersion": 1, "permissionPath": "/projects/group%2Fproject/issues/7"}
    requested = []
    def get(url, **kwargs):
        requested.append(url)
        return types.SimpleNamespace(status_code=404 if url.endswith("/issues/7") else 200, headers={})
    monkeypatch.setattr(main.http_requests, "get", get)
    resource = main._resource_of("gitlab", metadata)
    assert main._check_access("gitlab", resource, {"gitlab": "test-token"}) == main.ACCESS_DENIED
    assert requested == ["https://gitlab.com/api/v4/projects/group%2Fproject/issues/7"]


def test_team_stats_do_not_reveal_private_titles(app_modules, monkeypatch):
    main, _, db, rag = app_modules
    monkeypatch.setattr(db, "get_team_members", lambda _: [{"userId": 1}, {"userId": 2}])
    collection = types.SimpleNamespace(get=lambda **_: {"metadatas": [
        {"id": "private", "syncedBy": ",2,", "source": "gdrive", "title": "Private salary document", "date": "2026-11-13"},
        {"id": "own", "syncedBy": ",1,", "source": "gdrive", "title": "My document", "date": "2026-11-13"},
    ]})
    rag.get_vectorstore = lambda: types.SimpleNamespace(_collection=collection)
    result = main._compute_stats(1, 3)
    assert result.totalDocuments == 2  # aggregate count remains useful
    assert [topic.label for topic in result.topics] == ["My document"]


def test_legacy_gitlab_index_fails_closed_until_reindexed(app_modules):
    main, _, _, _ = app_modules
    assert main._resource_of("gitlab", {
        "id": "gitlab-group/project#issue-7", "tags": "gitlab,group/project,issue",
    }) is None


def test_repository_file_requires_file_permission_not_project_visibility(app_modules, monkeypatch):
    main, _, _, _ = app_modules
    path = "/projects/group%2Fproject/repository/files/private%2Fsecret.md/raw?ref=main"
    seen = []
    def get(url, **kwargs):
        seen.append(url)
        return types.SimpleNamespace(status_code=403, headers={})
    monkeypatch.setattr(main.http_requests, "get", get)
    resource = main._resource_of("gitlab", {
        "tags": "gitlab,group/project,file", "permissionVersion": 1, "permissionPath": path,
    })
    assert main._check_access("gitlab", resource, {"gitlab": "test-token"}) == main.ACCESS_DENIED
    assert seen == ["https://gitlab.com/api/v4" + path]


def test_internal_gitlab_notes_are_not_merged_into_parent_document(app_modules, monkeypatch):
    from connectors import gitlab_connector as connector
    monkeypatch.setattr(connector, "_paginate", lambda *args: [
        {"body": "public discussion", "created_at": "2026-11-13"},
        {"body": "internal discussion", "internal": True, "created_at": "2026-11-13"},
        {"body": "old confidential discussion", "confidential": True, "created_at": "2026-11-13"},
    ])
    assert [note["body"] for note in connector._list_notes("project", "issue", 1, "2026-01-01", {})] == ["public discussion"]


def test_kakao_subject_stays_bound_after_email_is_provided(app_modules):
    _, auth, _, _ = app_modules
    user_id = auth._get_or_create_kakao_user(12345, None)
    auth.signup("owned@example.com", "another-password")
    assert auth._get_or_create_kakao_user(12345, "owned@example.com") == user_id


@pytest.mark.parametrize("claims", [
    {"email": "valid@example.com", "email_verified": False, "sub": "subject"},
    {"email": "valid@example.com", "email_verified": True},
    {"email": "valid@example.com", "email_verified": True, "sub": {}},
    {"email": "valid@example.com", "email_verified": True, "sub": {"bad": "subject"}},
])
def test_google_rejects_unverified_or_missing_subject(app_modules, monkeypatch, claims):
    _, auth, db, _ = app_modules
    monkeypatch.setattr(auth.http_requests, "post", lambda *a, **k: types.SimpleNamespace(ok=True, json=lambda: {"access_token": "test"}))
    monkeypatch.setattr(auth.http_requests, "get", lambda *a, **k: types.SimpleNamespace(status_code=200, json=lambda: claims))
    assert auth.complete_google_login("code", db.create_oauth_state(0, "google_login"))["ok"] is False


def test_password_signup_does_not_grant_team_membership_based_on_domain(app_modules, monkeypatch):
    _, auth, db, _ = app_modules
    monkeypatch.setenv("SIGNUP_ALLOWED_DOMAINS", "example.com")
    token, _ = auth.signup("unverified@example.com", "test-password")
    assert db.get_teams_for_user(int(auth.verify_token(token)["sub"])) == []


@pytest.fixture
def real_rag(app_modules, monkeypatch):
    import importlib.util
    from pathlib import Path
    documents = types.ModuleType("langchain_core.documents")
    documents.Document = lambda **kwargs: types.SimpleNamespace(**kwargs)
    embeddings = types.ModuleType("langchain_core.embeddings")
    embeddings.Embeddings = object
    vectors = types.ModuleType("langchain_community.vectorstores")
    vectors.Chroma = object
    provider = types.ModuleType("openai")
    provider.OpenAI = object
    provider.RateLimitError = RuntimeError
    monkeypatch.setitem(__import__('sys').modules, "openai", provider)
    monkeypatch.setitem(__import__('sys').modules, "langchain_core.documents", documents)
    monkeypatch.setitem(__import__('sys').modules, "langchain_core.embeddings", embeddings)
    monkeypatch.setitem(__import__('sys').modules, "langchain_community.vectorstores", vectors)
    spec = importlib.util.spec_from_file_location("tested_rag", Path(__file__).parents[1] / "rag_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_acl_is_refetched_and_metadata_rewritten_even_when_content_unchanged(real_rag, monkeypatch):
    rag = real_rag
    doc = {"id": "gitlab-group/project#issue-7", "source": "gitlab", "title": "title", "content": "body",
           "author": "author", "date": "2026-11-13", "tags": ["gitlab", "group/project", "issue"],
           "permissionVersion": 1, "permissionPath": "/projects/group%2Fproject/issues/7"}
    previous = {"id": doc["id"], "syncedBy": ",1,", "sourceUpdatedAt": "same", "contentHash": rag.content_hash("title", "body")}
    writes = []
    collection = types.SimpleNamespace(get=lambda **k: {"ids": [doc["id"]], "metadatas": [previous]},
        upsert=lambda **k: writes.extend(k["metadatas"]))
    monkeypatch.setattr(rag, "get_vectorstore", lambda: types.SimpleNamespace(_collection=collection))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-provider-key")
    monkeypatch.setattr(rag.embeddings, "embed_documents", lambda texts: [[0.0]] * len(texts))
    assert rag._known_documents("gitlab", 1) == {}
    assert rag.ingest_documents([doc], 1) == 1
    assert writes[0]["permissionPath"] == doc["permissionPath"]
    previous.update(writes[0])
    assert rag._known_documents("gitlab", 1) == {doc["id"]: ""}


def test_changed_repository_ref_rewrites_acl_with_identical_content(real_rag, monkeypatch):
    rag = real_rag
    doc = {"id": "file", "source": "gitlab", "title": "title", "content": "body", "author": "a", "date": "2026-11-13",
           "permissionVersion": 1, "permissionPath": "/projects/test/repository/files/a/raw?ref=new"}
    previous = dict(doc, contentHash=rag.content_hash("title", "body"), permissionPath="/projects/test/repository/files/a/raw?ref=old", syncedBy=",1,")
    writes = []
    collection = types.SimpleNamespace(get=lambda **k: {"ids": ["file"], "metadatas": [previous]}, upsert=lambda **k: writes.extend(k["metadatas"]))
    monkeypatch.setattr(rag, "get_vectorstore", lambda: types.SimpleNamespace(_collection=collection))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-provider-key")
    monkeypatch.setattr(rag.embeddings, "embed_documents", lambda texts: [[0.0]] * len(texts))
    assert rag.ingest_documents([doc], 1) == 1
    assert writes[0]["permissionPath"].endswith("ref=new")
