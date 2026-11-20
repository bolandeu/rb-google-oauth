"""Контракт `auth status` (§8 стандарта tools): форма отчёта и конверта, статусы, коды выхода.

Форма — межинструментальный контракт (tools-watch читает её у всех CLI):
менять её = ломающее изменение (§4).
"""

from __future__ import annotations

import json
import threading
from importlib import metadata
from types import SimpleNamespace

import keyring.errors
import pytest
import typer

from google_oauth import Health, credential_status, health_check, status_exit_code, status_problems, status_report
from google_oauth.auth_command import _tool_version, make_auth_app
from google_oauth.errors import CliError, NotAuthorized, TokenRequestFailed

from . import fake_output
from .conftest import PSI_KEY, SA_INFO, SA_JSON, SA_KEY, FakeCreds

ENTRY_KEYS = ["provider", "required", "fields", "source", "source_ref", "status", "expires_at", "quota", "message"]


def _json(result) -> dict:
    return json.loads(result.stdout)


class HttpError(Exception):
    """Как ошибка httpx/requests: у неё есть `response.status_code`."""

    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.response = SimpleNamespace(status_code=code)


def _wrapped(code: int) -> CliError:
    error = CliError("API_ERROR", f"HTTP {code}")
    error.__cause__ = HttpError(code)
    return error


@pytest.fixture
def fake_token(auth, monkeypatch) -> None:
    """Google выдаёт токен без сети."""
    monkeypatch.setattr(auth, "credentials", lambda scopes=None: FakeCreds())


class TestEnvelope:
    def test_ok_report_shape(self, app, runner, fake_keyring):
        fake_keyring[SA_KEY] = SA_JSON
        result = runner.invoke(app, ["auth", "status", "--json"])
        assert result.exit_code == 0, result.stdout
        data = _json(result)
        assert list(data) == ["ok", "tool", "version", "checked_at", "credentials"]
        assert data["ok"] is True and data["tool"] == "demo" and data["checked_at"].endswith("Z")
        sa, psi = data["credentials"]
        assert list(sa) == ENTRY_KEYS and list(psi) == ENTRY_KEYS
        assert sa == {
            "provider": "google",
            "required": True,
            "fields": ["service_account_json"],
            "source": "keychain",
            "source_ref": "keychain service google-oauth:service_account",
            "status": "unchecked",
            "expires_at": None,
            "quota": None,
            "message": None,
        }
        # Необязательный API-ключ без значения — запись missing, но не exit 3.
        assert (psi["provider"], psi["required"], psi["status"]) == ("pagespeed", False, "missing")

    def test_problem_report_keeps_full_report_next_to_error(self, app, runner):
        result = runner.invoke(app, ["auth", "status", "--json"])
        assert result.exit_code == 3
        data = _json(result)
        assert list(data) == ["ok", "error", "tool", "version", "checked_at", "credentials"]
        assert data["error"]["code"] == "CREDENTIALS_UNHEALTHY" and "google (missing)" in data["error"]["message"]
        assert "pagespeed" not in data["error"]["message"] and data["error"]["action"]

    def test_human_output(self, app, runner, fake_keyring):
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 3
        assert "✗ google: missing" in result.stdout and "demo auth login --provider pagespeed" in result.stdout
        assert "Error:" in result.stderr
        fake_keyring[SA_KEY] = SA_JSON
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0 and "· google: unchecked (keychain: keychain service" in result.stdout

    def test_check_with_tool_callback(self, app, checks, runner, fake_keyring, fake_token):
        fake_keyring[SA_KEY] = SA_JSON
        sa = _json(runner.invoke(app, ["auth", "status", "--check", "--json"]))["credentials"][0]
        assert sa["status"] == "ok"
        checks["raise"] = _wrapped(403)
        result = runner.invoke(app, ["auth", "status", "--check", "--json"])
        assert result.exit_code == 3 and _json(result)["credentials"][0]["status"] == "invalid"

    def test_api_key_checks(self, auth, runner, fake_keyring, fake_token):
        fake_keyring[SA_KEY] = SA_JSON
        fake_keyring[PSI_KEY] = "psi-secret"
        calls: list[str] = []

        def psi_check(ctx: typer.Context) -> None:
            calls.append("psi")
            raise CliError("API_ERROR", "key psi-secret rejected")

        root = typer.Typer()
        root.add_typer(make_auth_app(auth, fake_output, api_key_checks={"pagespeed": psi_check}), name="auth")

        @root.callback()
        def main(ctx: typer.Context) -> None:
            ctx.obj = {"json": True}

        result = runner.invoke(root, ["auth", "status", "--check"])
        psi = _json(result)["credentials"][1]
        assert calls == ["psi"] and psi["status"] == "invalid" and psi["message"] == "key *** rejected"
        assert result.exit_code == 3  # invalid — проблема и у необязательного ключа
        assert "psi-secret" not in result.stdout

    def test_api_key_without_check_is_unchecked(self, app, runner, fake_keyring, fake_token):
        fake_keyring[SA_KEY] = SA_JSON
        fake_keyring[PSI_KEY] = "k"
        psi = _json(runner.invoke(app, ["auth", "status", "--check", "--json"]))["credentials"][1]
        assert psi["status"] == "unchecked" and psi["message"]

    def test_tool_version_from_console_script(self):
        assert _tool_version("demo") == "0.0.0"  # нет такого console script
        assert _tool_version("pytest") == metadata.version("pytest")


class TestSources:
    def test_env_json(self, auth, monkeypatch):
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON", SA_JSON)
        entry = credential_status(auth)
        assert (entry["source"], entry["source_ref"]) == ("env", "GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON")
        assert SA_INFO["private_key"] not in json.dumps(entry)

    def test_file(self, auth, monkeypatch, tmp_path):
        key = tmp_path / "sa.json"
        key.write_text(SA_JSON)
        monkeypatch.setenv("DEMO_SA_FILE", str(key))
        entry = credential_status(auth)
        assert (entry["source"], entry["source_ref"], entry["status"]) == ("file", str(key), "unchecked")

    def test_file_not_found(self, auth, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_FILE", str(tmp_path / "nope.json"))
        entry = credential_status(auth)
        assert (entry["source"], entry["source_ref"], entry["status"]) == (
            "file",
            "GOOGLE_OAUTH_SERVICE_ACCOUNT_FILE",
            "missing",
        )

    def test_broken_json_is_invalid(self, auth, monkeypatch):
        monkeypatch.setenv("DEMO_SA_JSON", "{nope")
        entry = credential_status(auth)
        assert (entry["source"], entry["status"]) == ("env", "invalid") and "не JSON" in entry["message"]

    def test_missing_names_where_to_put_it(self, auth):
        entry = credential_status(auth)
        assert entry["source_ref"] == (
            "DEMO_SA_JSON or GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON or DEMO_SA_FILE or GOOGLE_OAUTH_SERVICE_ACCOUNT_FILE"
            " or keychain service google-oauth:service_account"
        )
        psi = credential_status(auth, "pagespeed")
        assert (
            psi["source_ref"]
            == "DEMO_PSI_KEY or GOOGLE_OAUTH_PAGESPEED_API_KEY or keychain service google-oauth:api_key/pagespeed"
        )
        assert psi["required"] is False and credential_status(auth, "pagespeed", required=True)["required"] is True


class TestWithoutKeychain:
    """Linux-сервер без Secret Service, ключи из env (запуск с переменными из секрет-менеджера)."""

    @pytest.fixture(autouse=True)
    def _no_keychain(self, monkeypatch):
        def broken(*args):
            raise keyring.errors.NoKeyringError("No recommended backend was available")

        for name in ("get_password", "set_password", "delete_password"):
            monkeypatch.setattr(f"google_oauth.credentials.keyring.{name}", broken)

    def test_env_only_works(self, app, runner, monkeypatch, fake_token):
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON", SA_JSON)
        monkeypatch.setenv("GOOGLE_OAUTH_PAGESPEED_API_KEY", "psi")
        result = runner.invoke(app, ["auth", "status", "--check", "--json"])
        assert result.exit_code == 0, result.stdout
        sa, psi = _json(result)["credentials"]
        assert (sa["source"], sa["status"], psi["source"]) == ("env", "ok", "env")

    def test_missing_mentions_keychain(self, auth):
        entry = credential_status(auth)
        assert entry["status"] == "missing" and "Keychain unavailable (No recommended backend" in entry["message"]

    def test_bearer_from_env(self, auth, monkeypatch, fake_token):
        monkeypatch.setenv("GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON", SA_JSON)
        assert auth.bearer().headers() == {"Authorization": "Bearer token-1"}


class TestHealthCheck:
    @pytest.fixture(autouse=True)
    def _key(self, fake_keyring):
        fake_keyring[SA_KEY] = SA_JSON
        fake_keyring[PSI_KEY] = "psi-secret"

    def test_ok(self, auth, fake_token):
        assert health_check(auth) == Health(status="ok")
        assert health_check(auth, check=lambda: None, provider="pagespeed") == Health(status="ok")

    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (_wrapped(401), "invalid"),
            (_wrapped(403), "invalid"),
            (_wrapped(429), "unreachable"),
            (_wrapped(503), "unreachable"),
            (HttpError(403), "invalid"),
            (CliError("PROVIDER_ERROR", "down", exit_code=5), "unreachable"),
            (CliError("API_ERROR", "bad request"), "invalid"),
            (ConnectionError("no route"), "unreachable"),
        ],
    )
    def test_failure_mapping(self, auth, fake_token, error, status):
        def check() -> None:
            raise error

        assert health_check(auth, check=check).status == status

    def test_google_rejects_key(self, auth, monkeypatch, fake_token):
        def revoked(creds) -> str:
            raise NotAuthorized("google", "invalid_grant", action="…")

        monkeypatch.setattr(auth, "refresh", revoked)
        assert health_check(auth) == Health(status="invalid", message="invalid_grant")

    def test_token_network_error(self, auth, monkeypatch, fake_token):
        def down(creds) -> str:
            raise TokenRequestFailed("google", "timeout")

        monkeypatch.setattr(auth, "refresh", down)
        assert health_check(auth).status == "unreachable"

    def test_timeout(self, auth, fake_token):
        release = threading.Event()
        health = health_check(auth, check=lambda: release.wait(5), timeout=0.05)
        release.set()
        assert health.status == "unreachable" and "0.05" in (health.message or "")

    def test_scrubs_secret_values(self, auth, fake_token):
        def check() -> None:
            raise CliError("API_ERROR", f"bad token token-1, key {SA_INFO['private_key']}")

        assert health_check(auth, check=check).message == "bad token ***, key ***"

    def test_api_key_needs_check(self, auth):
        with pytest.raises(ValueError, match="pagespeed"):
            health_check(auth, provider="pagespeed")
        with pytest.raises(KeyError):
            health_check(auth, check=lambda: None, provider="nope")


class TestExitCode:
    @staticmethod
    def _report(*entries: tuple[bool, str]) -> dict:
        credentials = [{"provider": f"p{i}", "required": req, "status": st} for i, (req, st) in enumerate(entries)]
        return status_report("demo", "1.0.0", credentials)

    @pytest.mark.parametrize(
        ("entries", "code"),
        [
            ([(True, "ok"), (True, "unchecked")], 0),
            ([(False, "missing"), (False, "unreachable"), (False, "quota_exhausted")], 0),
            ([(True, "missing")], 3),
            ([(True, "unreachable")], 3),
            ([(False, "invalid")], 3),  # необязательный, но неверный — проблема
            ([(False, "expired")], 3),
        ],
    )
    def test_rules(self, entries, code):
        assert status_exit_code(self._report(*entries)) == code

    def test_problems_name_provider_and_status(self):
        assert status_problems(self._report((True, "ok"), (False, "invalid"))) == {"p1": "invalid"}
