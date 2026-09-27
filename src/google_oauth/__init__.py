"""google-oauth — общая авторизация Google для CLI-инструментов.

Один набор ключей Google (сервисный аккаунт, API-ключи) — в общем слоте
keychain `google-oauth:*` для всех инструментов (gsc, …): вход в одном
авторизует остальные. Инструмент описывает себя `Profile` и получает:

- `GoogleAuth(profile)` — найти ключи (env инструмента → общие env → keychain),
  выдать access token с автообновлением (`bearer().headers()`), API-ключ, статус;
- `CredentialStore(profile)` — keychain ОС + имена переменных окружения;
- `status` — отчёт для `<cli> auth status --json` по контракту §8 стандарта tools и
  `health_check()` — делегат для `Provider.health_check()` инструментов по шаблону cli-generator;
- `make_auth_app(auth, output)` (модуль `auth_command`) — готовая Typer-команда
  `auth login|logout|status [--check]`.

Без keychain (Linux-сервер, `doppler run`) всё работает от переменных окружения
(`GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON`, `GOOGLE_OAUTH_<NAME>_API_KEY`, …).

Импорт не трогает сеть, keychain, google-auth и typer.
"""

from __future__ import annotations

from .auth import AuthStatus, BearerToken, Found, GoogleAuth, parse_service_account, refresh_credentials
from .credentials import CredentialStore
from .errors import (
    CliError,
    CredentialStoreUnavailable,
    CredentialsUnhealthy,
    InvalidArguments,
    NotAuthorized,
    TokenRequestFailed,
)
from .profile import ApiKey, Profile
from .status import Health, Quota, credential_status, health_check, status_exit_code, status_problems, status_report

__all__ = [
    "ApiKey",
    "AuthStatus",
    "BearerToken",
    "CliError",
    "CredentialStore",
    "CredentialStoreUnavailable",
    "CredentialsUnhealthy",
    "Found",
    "GoogleAuth",
    "Health",
    "InvalidArguments",
    "NotAuthorized",
    "Profile",
    "Quota",
    "TokenRequestFailed",
    "credential_status",
    "health_check",
    "parse_service_account",
    "refresh_credentials",
    "status_exit_code",
    "status_problems",
    "status_report",
]
