"""Команда auth: login/logout/status на нейтральном профиле."""

from __future__ import annotations

import json
from pathlib import Path

from google_oauth.errors import CliError

from .conftest import PSI_KEY, SA_INFO, SA_JSON, SA_KEY, FakeCreds


def _json(result) -> dict:
    return json.loads(result.stdout)


class TestLoginServiceAccount:
    def test_from_file_then_status_and_logout(self, app, runner, fake_keyring, tmp_path: Path) -> None:
        key = tmp_path / "key.json"
        key.write_text(SA_JSON)
        result = runner.invoke(app, ["auth", "login", "--file", str(key), "--json"])
        assert result.exit_code == 0, result.stdout
        assert _json(result) == {
            "ok": True,
            "provider": "google",
            "account": SA_INFO["client_email"],
            "stored": "keychain",
        }
        assert fake_keyring[SA_KEY] == SA_JSON

        data = _json(runner.invoke(app, ["auth", "status", "--json"]))
        assert (data["google"], data["source"], data["pagespeed_key"]) == ("ok", "keychain", False)

        assert runner.invoke(app, ["auth", "logout"]).exit_code == 0
        assert SA_KEY not in fake_keyring

    def test_human_output_shows_hint(self, app, runner, tmp_path: Path) -> None:
        key = tmp_path / "key.json"
        key.write_text(SA_JSON)
        result = runner.invoke(app, ["auth", "login", "--file", str(key)])
        assert SA_INFO["client_email"] in result.stdout and "Добавьте email" in result.stdout

    def test_rejects_non_service_account(self, app, runner, tmp_path: Path, fake_keyring) -> None:
        key = tmp_path / "key.json"
        key.write_text(json.dumps({"type": "authorized_user"}))
        result = runner.invoke(app, ["auth", "login", "--file", str(key), "--json"])
        assert result.exit_code == 2 and _json(result)["error"]["code"] == "INVALID_ARGUMENTS"
        assert not fake_keyring

    def test_missing_file(self, app, runner, tmp_path: Path) -> None:
        result = runner.invoke(app, ["auth", "login", "--file", str(tmp_path / "nope.json"), "--json"])
        assert result.exit_code == 2 and "не найден" in _json(result)["error"]["message"]

    def test_copies_env_to_keychain(self, app, runner, fake_keyring, monkeypatch) -> None:
        monkeypatch.setenv("DEMO_SA_JSON", SA_JSON)
        result = runner.invoke(app, ["--non-interactive", "auth", "login", "--json"])
        assert result.exit_code == 0, result.stdout
        assert fake_keyring[SA_KEY] == SA_JSON

    def test_non_interactive_without_source(self, app, runner) -> None:
        result = runner.invoke(app, ["--non-interactive", "auth", "login", "--json"])
        assert result.exit_code == 2 and "--file" in _json(result)["error"]["message"]

    def test_prompts_for_path(self, app, runner, fake_keyring, tmp_path: Path) -> None:
        key = tmp_path / "ключ.json"
        key.write_text(SA_JSON)
        result = runner.invoke(app, ["auth", "login", "--json"], input=f"  {key}\n")
        assert result.exit_code == 0, result.output
        assert _json(result)["account"] == SA_INFO["client_email"]  # вопрос ушёл в stderr, stdout — чистый JSON

    def test_prompt_aborted(self, app, runner) -> None:
        assert runner.invoke(app, ["auth", "login"], input="").exit_code != 0


class TestLoginApiKey:
    def test_prompt(self, app, runner, fake_keyring) -> None:
        result = runner.invoke(app, ["auth", "login", "--provider", "pagespeed", "--json"], input="  psi \n")
        assert result.exit_code == 0, result.output
        assert fake_keyring[PSI_KEY] == "psi"
        assert _json(runner.invoke(app, ["auth", "status", "--json"]))["pagespeed_key"] is True

    def test_env_and_non_interactive(self, app, runner, fake_keyring, monkeypatch) -> None:
        result = runner.invoke(app, ["auth", "login", "--provider", "pagespeed", "--non-interactive", "--json"])
        assert result.exit_code == 2 and "DEMO_PSI_KEY" in _json(result)["error"]["message"]
        monkeypatch.setenv("GOOGLE_OAUTH_PAGESPEED_API_KEY", "env-key")
        result = runner.invoke(app, ["auth", "login", "--provider", "pagespeed", "--non-interactive"])
        assert result.exit_code == 0 and fake_keyring[PSI_KEY] == "env-key"

    def test_file_only_for_service_account(self, app, runner, tmp_path: Path) -> None:
        result = runner.invoke(app, ["auth", "login", "--provider", "pagespeed", "--file", str(tmp_path), "--json"])
        assert result.exit_code == 2

    def test_unknown_provider(self, app, runner) -> None:
        assert runner.invoke(app, ["auth", "login", "--provider", "nope"]).exit_code == 2

    def test_logout(self, app, runner, fake_keyring) -> None:
        fake_keyring[PSI_KEY] = "k"
        data = _json(runner.invoke(app, ["auth", "logout", "--provider", "pagespeed", "--json"]))
        assert data == {"ok": True, "provider": "pagespeed"} and PSI_KEY not in fake_keyring


class TestStatus:
    def test_human_missing(self, app, runner) -> None:
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "missing" in result.stdout and "demo auth login --provider pagespeed" in result.stdout

    def test_check_with_tool_callback(self, app, checks, runner, auth, fake_keyring, monkeypatch) -> None:
        fake_keyring[SA_KEY] = SA_JSON
        monkeypatch.setattr(auth, "credentials", lambda scopes=None: FakeCreds())
        data = _json(runner.invoke(app, ["auth", "status", "--check", "--json"]))
        assert data["google"] == "ok" and data["valid"] is True
        checks["raise"] = CliError("API_ERROR", "403 нет доступа")
        result = runner.invoke(app, ["auth", "status", "--check"])
        assert "API отверг доступ: 403 нет доступа" in result.stdout
        assert SA_INFO["client_email"] in result.stdout
