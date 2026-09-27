"""google-oauth — общая авторизация Google для CLI-инструментов.

Один набор ключей Google (сервисный аккаунт, API-ключи) — в общем слоте
keychain `google-oauth:*` для всех инструментов (gsc, …): вход в одном
авторизует остальные. Инструмент описывает себя `Profile` и получает:

- `GoogleAuth(profile)` — найти ключи (env инструмента → общие env → keychain),
  выдать access token с автообновлением (`bearer().headers()`), API-ключ, статус;
- `CredentialStore(profile)` — keychain ОС + имена переменных окружения;
- `make_auth_app(auth, output)` (модуль `auth_command`) — готовая Typer-команда
  `auth login|logout|status [--check]`.

Импорт не трогает сеть, keychain, google-auth и typer.
"""

from __future__ import annotations

from .auth import AuthStatus, BearerToken, Found, GoogleAuth, parse_service_account, refresh_credentials
from .credentials import CredentialStore
from .errors import CliError, CredentialStoreUnavailable, InvalidArguments, NotAuthorized, TokenRequestFailed
from .profile import ApiKey, Profile

__all__ = [
    "ApiKey",
    "AuthStatus",
    "BearerToken",
    "CliError",
    "CredentialStore",
    "CredentialStoreUnavailable",
    "Found",
    "GoogleAuth",
    "InvalidArguments",
    "NotAuthorized",
    "Profile",
    "TokenRequestFailed",
    "parse_service_account",
    "refresh_credentials",
]
