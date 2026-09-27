"""Keychain ОС + переменные окружения — где лежат ключи Google.

Пространство имён общее для всех инструментов (`Profile.keychain_namespace`,
по умолчанию `google-oauth`). Запись keychain — пара (service, username):

- ключ сервисного аккаунта: `google-oauth:service_account` / `default`, значение — JSON ключа как есть;
- API-ключ: `google-oauth:api_key` / `<имя ключа>` (`pagespeed`, …), значение — ключ.

Вид (kind) в имени сервиса оставляет место для OAuth пользователя позже
(`google-oauth:authorized_user`) без переделки схемы.

Переменные окружения переопределяют keychain: сначала «исторические»
переменные инструмента из профиля, затем общие `GOOGLE_OAUTH_…`.
"""

from __future__ import annotations

import logging
import os

import keyring
import keyring.errors
from keyring.backends import fail

from .errors import CredentialStoreUnavailable
from .profile import ApiKey, Profile

SERVICE_ACCOUNT = "service_account"
API_KEY = "api_key"
DEFAULT = "default"

log = logging.getLogger(__name__)


class CredentialStore:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        # Почему keychain не прочитался при последнем обращении (None — прочитался).
        self.unavailable_reason: str | None = None

    # --- имена ---------------------------------------------------------------

    def service_name(self, kind: str) -> str:
        return f"{self.profile.keychain_namespace}:{kind}"

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
        try:
            value = keyring.get_password(self.service_name(kind), name) or None
        except keyring.errors.KeyringError as exc:
            # Headless Linux/CI без Secret Service не должен блокировать путь через env.
            if self.unavailable_reason is None:  # предупредить один раз, а не на каждое чтение
                log.warning("Хранилище ключей ОС недоступно (%s); только переменные окружения", exc)
            self.unavailable_reason = str(exc) or type(exc).__name__
            return None
        self.unavailable_reason = None
        return value

    def set(self, kind: str, value: str, name: str = DEFAULT) -> None:
        try:
            keyring.set_password(self.service_name(kind), name, value)
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    def delete(self, kind: str, name: str = DEFAULT) -> None:
        try:
            keyring.delete_password(self.service_name(kind), name)
        except keyring.errors.PasswordDeleteError:
            pass  # уже отсутствует — удаление не ошибка
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable(self.profile, str(exc)) from exc

    @staticmethod
    def backend() -> str | None:
        """Имя активного бэкенда keyring или None, если пользоваться нечем (headless Linux без Secret Service)."""
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return None
        return f"{type(backend).__module__}.{type(backend).__name__}"
