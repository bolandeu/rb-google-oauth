"""GoogleAuth: источники ключей, токен, статус — без сети и настоящего keychain."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import keyring.errors
import pytest

from google_oauth import GoogleAuth, NotAuthorized, TokenRequestFailed, parse_service_account

from .conftest import PSI_KEY, SA_INFO, SA_JSON, SA_KEY, FakeCreds


class TestServiceAccountSources:
    def test_missing(self, auth: GoogleAuth) -> None:
        assert auth.find_service_account() is None
        with pytest.raises(NotAuthorized) as exc:
            auth.load_service_account()
        assert exc.value.exit_code == 3 and "demo auth login --file" in (exc.value.action or "")

    def test_keychain(self, auth: GoogleAuth, fake_keyring) -> None:
        fake_keyring[SA_KEY] = SA_JSON
        found = auth.find_service_account()
        assert found and (found.source, found.origin) == ("keychain", "google-oauth:service_account")
        assert auth.load_service_account()["client_email"] == SA_INFO["client_email"]

    @pytest.mark.parametrize("var", ["DEMO_SA_JSON", "GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON"])
    def test_env_overrides_keychain(self, auth: GoogleAuth, fake_keyring, monkeypatch, var: str) -> None:
        fake_keyring[SA_KEY] = "{broken"
        monkeypatch.setenv(var, SA_JSON)
        found = auth.find_service_account()
        assert found and (found.source, found.origin) == ("env", var)

    def test_tool_env_before_shared_env(self, auth: GoogleAuth, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON", "shared")
        monkeypatch.setenv("DEMO_SA_JSON", "tool")
        found = auth.find_service_account()
        assert found and found.value == "tool"

    def test_file_env(self, auth: GoogleAuth, monkeypatch, tmp_path: Path) -> None:
        key = tmp_path / "key.json"
        key.write_text(SA_JSON)
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_FILE", str(key))
        found = auth.find_service_account()
        assert found and (found.source, found.origin) == ("file", str(key))
        monkeypatch.setenv("DEMO_SA_FILE", str(tmp_path / "nope.json"))
        with pytest.raises(NotAuthorized, match="DEMO_SA_FILE"):
            auth.find_service_account()

    def test_broken_key_is_not_authorized(self, auth: GoogleAuth, monkeypatch) -> None:
        monkeypatch.setenv("DEMO_SA_JSON", json.dumps({"type": "authorized_user"}))
        with pytest.raises(NotAuthorized, match="DEMO_SA_JSON"):
            auth.load_service_account()

    def test_keychain_unavailable_falls_back_to_env(self, auth: GoogleAuth, monkeypatch) -> None:
        def broken(service: str, username: str) -> str | None:
            raise keyring.errors.NoKeyringError("no backend")

        monkeypatch.setattr("google_oauth.credentials.keyring.get_password", broken)
        assert auth.find_service_account() is None
        monkeypatch.setenv("DEMO_PSI_KEY", "k")
        assert auth.api_key("pagespeed") == "k"


def test_parse_service_account_errors() -> None:
    with pytest.raises(Exception, match="не JSON"):
        parse_service_account("{nope")
    with pytest.raises(Exception, match="type"):
        parse_service_account("[]")
    with pytest.raises(Exception, match="client_email"):
        parse_service_account(json.dumps({"type": "service_account"}))


class TestApiKeys:
    def test_order_tool_env_shared_env_keychain(self, auth: GoogleAuth, fake_keyring, monkeypatch) -> None:
        assert auth.api_key("pagespeed") is None
        fake_keyring[PSI_KEY] = "from-keychain"
        found = auth.find_api_key("pagespeed")
        assert found and found.source == "keychain"
        monkeypatch.setenv("GOOGLE_OAUTH_PAGESPEED_API_KEY", "shared")
        assert auth.api_key("pagespeed") == "shared"
        monkeypatch.setenv("DEMO_PSI_KEY", "tool")
        assert auth.api_key("pagespeed") == "tool"

    def test_store_and_logout(self, auth: GoogleAuth, fake_keyring) -> None:
        auth.store_api_key("pagespeed", "  k \n")
        assert fake_keyring[PSI_KEY] == "k"
        auth.logout("pagespeed")
        assert PSI_KEY not in fake_keyring
        with pytest.raises(Exception, match="Пустой"):
            auth.store_api_key("pagespeed", " ")
        with pytest.raises(KeyError):
            auth.store_api_key("unknown", "k")


class TestToken:
    def test_credentials_default_and_explicit_scopes(self, auth: GoogleAuth, monkeypatch) -> None:
        from google.oauth2 import service_account

        monkeypatch.setenv("DEMO_SA_JSON", SA_JSON)
        captured: list = []
        monkeypatch.setattr(
            service_account.Credentials,
            "from_service_account_info",
            classmethod(lambda cls, info, scopes: captured.append((info["client_email"], scopes)) or "creds"),
        )
        assert auth.credentials() == "creds"
        auth.credentials(["x"])
        assert captured == [
            (SA_INFO["client_email"], ["https://www.googleapis.com/auth/demo.readonly"]),
            (SA_INFO["client_email"], ["x"]),
        ]

    def test_refresh_maps_google_auth_errors(self, auth: GoogleAuth) -> None:
        import google.auth.exceptions

        class Failing:
            def __init__(self, exc: Exception) -> None:
                self.exc = exc

            def refresh(self, request) -> None:
                raise self.exc

        with pytest.raises(NotAuthorized, match="invalid_grant"):
            auth.refresh(Failing(google.auth.exceptions.RefreshError("invalid_grant")))
        with pytest.raises(TokenRequestFailed) as exc:
            auth.refresh(Failing(google.auth.exceptions.TransportError("offline")))
        assert exc.value.exit_code == 5 and exc.value.to_dict()["provider"] == "google"

    def test_bearer_reads_key_once_and_refreshes_when_invalid(self, auth: GoogleAuth, monkeypatch) -> None:
        creds = FakeCreds()
        calls: list = []
        monkeypatch.setattr(auth, "credentials", lambda scopes=None: calls.append(scopes) or creds)
        bearer = auth.bearer(["s"])
        assert bearer.headers() == {"Authorization": "Bearer token-1"}
        assert bearer.headers() == {"Authorization": "Bearer token-1"}  # валиден — без нового запроса
        creds.valid = False
        assert bearer.token() == "token-2"
        assert calls == [["s"]]


class TestStatus:
    def test_missing(self, auth: GoogleAuth) -> None:
        status = auth.status()
        assert (status.state, status.account, status.api_keys) == ("missing", None, {"pagespeed": False})
        assert "demo auth login" in (status.detail or "")
        assert status.to_dict() == {
            "google": "missing",
            "pagespeed_key": False,
            "account": None,
            "source": None,
            "detail": status.detail,
        }

    def test_broken_key(self, auth: GoogleAuth, monkeypatch) -> None:
        monkeypatch.setenv("DEMO_SA_JSON", "{nope")
        status = auth.status()
        assert status.state == "missing" and "не JSON" in (status.detail or "")

    def test_ok_and_check(self, auth: GoogleAuth, fake_keyring, monkeypatch) -> None:
        fake_keyring[SA_KEY] = SA_JSON
        status = auth.status()
        assert (status.state, status.account, status.source) == ("ok", SA_INFO["client_email"], "keychain")

        monkeypatch.setattr(auth, "credentials", lambda scopes=None: FakeCreds())
        assert auth.status(check=True).state == "ok"

        def revoked(creds) -> str:
            raise NotAuthorized("google", "invalid_grant", action="…")

        monkeypatch.setattr(auth, "refresh", revoked)
        status = auth.status(check=True)
        assert (status.state, status.detail) == ("expired", "invalid_grant")


def test_backend_name() -> None:
    from google_oauth import CredentialStore

    assert CredentialStore.backend() is None or "." in (CredentialStore.backend() or "")


def test_import_has_no_side_effects() -> None:
    """import google_oauth не тянет typer и google-auth — отдельный процесс, чистый sys.modules."""
    code = "import sys, google_oauth; print('typer' in sys.modules, 'google.auth' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    assert out.stdout.split() == ["False", "False"]
