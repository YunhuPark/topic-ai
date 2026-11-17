import importlib
import sys
import types

import pytest


@pytest.fixture
def app_modules(tmp_path, monkeypatch):
    """Run real auth/SQLite/routes; isolate only remote embedding/model startup."""
    monkeypatch.syspath_prepend(str(__import__('pathlib').Path(__file__).parents[1]))
    monkeypatch.setenv("JWT_SECRET", "test-only-secret-" * 4)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "accounts.db"))
    monkeypatch.delenv("SIGNUP_ALLOWED_DOMAINS", raising=False)
    for name in ("main", "auth", "db", "models"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    rag = types.ModuleType("rag_pipeline")
    llm = types.ModuleType("llm_backend")
    llm.is_ollama_backend = lambda: False
    docs = types.ModuleType("langchain_core.documents")
    docs.Document = lambda **kwargs: types.SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "rag_pipeline", rag)
    monkeypatch.setitem(sys.modules, "llm_backend", llm)
    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.documents", docs)
    main = importlib.import_module("main")
    yield main, importlib.import_module("auth"), importlib.import_module("db"), rag

