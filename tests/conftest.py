"""Тесты никогда не трогают настоящий keychain, сеть и окружение разработчика."""

from __future__ import annotations

import json
import os

import pytest
import typer
from typer.testing import CliRunner

from google_oauth import ApiKey, GoogleAuth, Profile
from google_oauth.auth_command import make_auth_app

from . import fake_output

PROFILE = Profile(
    cli_name="demo",
    service="Демо",
    scopes=("https://www.googleapis.com/auth/demo.readonly", "https://www.googleapis.com/auth/demo"),
    service_account_env=("DEMO_SA_JSON",),
    service_account_file_env=("DEMO_SA_FILE",),
    api_keys=(ApiKey("pagespeed", "PageSpeed Insights", env=("DEMO_PSI_KEY",)),),
    login_hint="Добавьте email в Демо.",
)
SA_KEY = ("google-oauth:service_account", "default")  # общий слот для всех инструментов
PSI_KEY = ("google-oauth:api_key", "pagespeed")

SA_INFO = {
    "type": "service_account",
    "client_email": "reader@demo.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
}
SA_JSON = json.dumps(SA_INFO)


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("google_oauth.credentials.keyring.set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr("google_oauth.credentials.keyring.get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr("google_oauth.credentials.keyring.delete_password", lambda s, u: store.pop((s, u), None))
    for var in list(os.environ):
        if var.startswith(("DEMO_", "GOOGLE_OAUTH_")):
            monkeypatch.delenv(var)
    return store


@pytest.fixture
def auth() -> GoogleAuth:
    return GoogleAuth(PROFILE)


class FakeCreds:
    """Вместо google-auth: токен без похода в oauth2.googleapis.com."""

    def __init__(self) -> None:
        self.valid = False
        self.token: str | None = None
        self.refreshes = 0

    def refresh(self, request) -> None:
        self.refreshes += 1
        self.valid, self.token = True, f"token-{self.refreshes}"


@pytest.fixture
def app_checks(auth: GoogleAuth):
    """Корневое приложение с глобальными --json/--non-interactive и sub-app auth."""
    checks: dict = {"raise": None}

    def check(ctx: typer.Context) -> None:
        if checks["raise"]:
            raise checks["raise"]

    root = typer.Typer()
    root.add_typer(make_auth_app(auth, fake_output, check=check), name="auth")

    @root.callback()
    def main(
        ctx: typer.Context,
        json_output: bool = typer.Option(False, "--json"),
        non_interactive: bool = typer.Option(False, "--non-interactive"),
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj.update({"json": json_output, "non_interactive": non_interactive, "quiet": False})

    return root, checks


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def app(app_checks):
    return app_checks[0]


@pytest.fixture
def checks(app_checks) -> dict:
    return app_checks[1]
