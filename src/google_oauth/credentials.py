"""Keychain ОС + переменные окружения — где лежат ключи Google.

Пространство имён общее для всех инструментов (`Profile.keychain_namespace`, по умолчанию `google-oauth`).
Запись keychain — пара (service, username):

- ключ сервисного аккаунта: `google-oauth:service_account` / `default`, значение — JSON ключа как есть;
- API-ключ: `google-oauth:api_key` / `<имя ключа>` (`pagespeed`, …), значение — ключ.

Сам keychain, «прочитать один раз, предупредить один раз» и разбор недоступности — в общем `rb-credentials`;
здесь остаются имена Google, переменные окружения и маппинг ошибок на `CredentialStoreUnavailable`.

Переменные окружения переопределяют keychain: сначала «исторические» переменные инструмента из профиля,
затем общие `GOOGLE_OAUTH_…`.
"""

from __future__ import annotations

import os

import keyring  # noqa: F401 — реэкспорт: тесты подменяют `google_oauth.credentials.keyring.*`
from keyring.backends import fail
from rb_credentials import Store, StoreUnavailable

from .errors import CredentialStoreUnavailable
from .profile import ApiKey, Profile

SERVICE_ACCOUNT = "service_account"
API_KEY = "api_key"
DEFAULT = "default"


class CredentialStore:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._store = Store(profile.keychain_namespace)

    # --- имена ---------------------------------------------------------------

    def service_name(self, kind: str) -> str:
        return self._store.service_name(kind)

    @property
    def unavailable_reason(self) -> str | None:
        """Почему keychain не прочитался при последнем обращении (None — прочитался)."""
        return self._store.unavailable_reason

    @property
    def env_prefix(self) -> str:
        return self.profile.keychain_namespace.upper().replace("-", "_")

    def service_account_json_env(self) -> list[str]:
        return [*self.profile.service_account_env, f"{self.env_prefix}_SERVICE_ACCOUNT_JSON"]

    def service_account_file_env(self) -> list[str]:
        return [*self.profile.service_account_file_env, f"{self.env_prefix}_SERVICE_ACCOUNT_FILE"]

    def api_key_env(self, key: ApiKey) -> list[str]:
        return [*key.env, f"{self.env_prefix}_{key.name.upper()}_API_KEY"]

    @staticmethod
    def first_env(names: list[str]) -> tuple[str, str] | None:
        """(значение, имя переменной) первой непустой переменной из списка."""
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                return value, name
        return None

    # --- keychain --------------------------------------------------------------

    def get(self, kind: str, name: str = DEFAULT) -> str | None:
        """Значение из keychain; недоступный keychain — не ошибка (остаются переменные окружения)."""
        return self._store.get_value(kind, name)

    def set(self, kind: str, value: str, name: str = DEFAULT) -> None:
        try:
            self._store.set_value(kind, value, name)
        except StoreUnavailable as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    def delete(self, kind: str, name: str = DEFAULT) -> None:
        try:
            self._store.delete_value(kind, name)
        except StoreUnavailable as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    @staticmethod
    def backend() -> str | None:
        """Имя активного бэкенда keyring или None, если пользоваться нечем (headless Linux без Secret Service)."""
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return None
        return f"{type(backend).__module__}.{type(backend).__name__}"
