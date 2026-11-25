"""OAuth 토큰 저장 암호화와 Slack 첨부 다운로드 검증 (4-3, 4-10)."""
import pathlib
import sys

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from connectors import slack_connector  # noqa: E402


def test_tokens_are_encrypted_at_rest(app_modules, monkeypatch):
    _, _, db, _ = app_modules
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    db.link_account(1, "slack", "me@example.com", access_token="xoxp-secret", refresh_token="refresh-secret")

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT access_token, refresh_token FROM linked_accounts WHERE user_id = 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["access_token"].startswith("enc:v1:")
    assert row["refresh_token"].startswith("enc:v1:")
    assert "xoxp-secret" not in row["access_token"]

    assert db.get_linked_access_token(1, "slack") == "xoxp-secret"
    assert db.get_linked_refresh_token(1, "slack") == "refresh-secret"
    accounts = db.get_all_accounts_with_tokens(["slack"])
    assert [a["access_token"] for a in accounts] == ["xoxp-secret"]


def test_plaintext_rows_stay_readable_and_get_migrated(app_modules, monkeypatch):
    _, _, db, _ = app_modules
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    db.link_account(2, "github", "me@example.com", access_token="gho_plain")
    assert db.get_linked_access_token(2, "github") == "gho_plain"  # 키 없으면 기존과 동일

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert db.get_linked_access_token(2, "github") == "gho_plain"  # 기존 평문 호환

    assert db.migrate_plaintext_tokens() >= 1
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT access_token FROM linked_accounts WHERE user_id = 2"
        ).fetchone()
    finally:
        conn.close()
    assert row["access_token"].startswith("enc:v1:")
    assert db.get_linked_access_token(2, "github") == "gho_plain"
    assert db.migrate_plaintext_tokens() == 0  # 이미 암호화된 행은 건드리지 않음


def test_encrypted_token_without_key_fails_loudly(app_modules, monkeypatch):
    _, _, db, _ = app_modules
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db.link_account(3, "notion", "me@example.com", access_token="secret-token")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        db.get_linked_access_token(3, "notion")


class _FakeResponse:
    def __init__(self, content=b"", location=None, headers=None):
        self._content = content
        self.location = location
        self.headers = dict(headers or {})
        if location:
            self.headers.setdefault("Location", location)

    @property
    def is_redirect(self):
        return self.location is not None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_slack_download_rejects_foreign_host(monkeypatch):
    with pytest.raises(ValueError):
        slack_connector._download_slack_file("https://evil.example.com/file.pdf", {})
    with pytest.raises(ValueError):
        slack_connector._download_slack_file("http://files.slack.com/file.pdf", {})
    assert slack_connector._download_slack_file.__doc__


def test_slack_download_follows_only_slack_redirects(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResponse(location="https://files.slack.com/files-pri/T1-F1/download")
        if len(calls) == 2:
            return _FakeResponse(content=b"hello")
        raise AssertionError("추가 요청이 발생했습니다")

    monkeypatch.setattr(slack_connector.requests, "get", fake_get)
    assert slack_connector._download_slack_file(
        "https://files.slack.com/files-pri/T1-F1/private", {"Authorization": "Bearer x"}
    ) == b"hello"

    calls.clear()

    def fake_get_bad(url, **kwargs):
        calls.append(url)
        return _FakeResponse(location="http://169.254.169.254/latest/meta-data/")

    monkeypatch.setattr(slack_connector.requests, "get", fake_get_bad)
    with pytest.raises(ValueError):
        slack_connector._download_slack_file("https://files.slack.com/x", {})


def test_slack_download_stops_at_size_limit(monkeypatch):
    big = b"a" * (slack_connector._MAX_ATTACHMENT_BYTES + 1)

    def fake_get(url, **kwargs):
        assert kwargs.get("stream") is True
        return _FakeResponse(content=big)

    monkeypatch.setattr(slack_connector.requests, "get", fake_get)
    with pytest.raises(ValueError):
        slack_connector._download_slack_file("https://files.slack.com/x", {})


def test_slack_download_rejects_declared_oversize(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(headers={"Content-Length": str(slack_connector._MAX_ATTACHMENT_BYTES + 1)})

    monkeypatch.setattr(slack_connector.requests, "get", fake_get)
    with pytest.raises(ValueError):
        slack_connector._download_slack_file("https://files.slack.com/x", {})
    assert len(calls) == 1
