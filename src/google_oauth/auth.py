"""Ключ сервисного аккаунта, API-ключи, access token и статус — всё неинтерактивно.

`google-auth` импортируется лениво (внутри функций): импорт пакета не тянет
его и не ходит ни в сеть, ни в keychain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NamedTuple

from .credentials import API_KEY, SERVICE_ACCOUNT, CredentialStore
from .errors import InvalidArguments, NotAuthorized, TokenRequestFailed
from .profile import Profile

Source = Literal["env", "file", "keychain"]


class Found(NamedTuple):
    """Найденный секрет: значение, тип источника и откуда именно (имя переменной / путь / запись keychain)."""

    value: str
    source: Source
    origin: str


@dataclass
class AuthStatus:
    """Готовность авторизации без исключений — для `auth status` и `doctor` инструментов.

    state: ok — ключ сервисного аккаунта есть и разбирается; missing — нет или
    битый; expired — Google отверг ключ (только при check=True: без сети не узнать).
    """

    provider: str
    state: Literal["ok", "missing", "expired"]
    account: str | None = None  # email сервисного аккаунта
    source: Source | None = None
    detail: str | None = None  # почему не ok
    api_keys: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Плоский JSON: {"<provider>": state, "<key>_key": bool, "account", "source", "detail"}."""
        return {
            self.provider: self.state,
            **{f"{name}_key": present for name, present in self.api_keys.items()},
            "account": self.account,
            "source": self.source,
            "detail": self.detail,
        }


def parse_service_account(text: str) -> dict[str, Any]:
    """Разобрать и проверить JSON ключа сервисного аккаунта; ошибка — InvalidArguments."""
    try:
        info = json.loads(text)
    except ValueError as exc:
        raise InvalidArguments(f"Ключ сервисного аккаунта — не JSON: {exc}") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise InvalidArguments('Это не ключ сервисного аккаунта: нужен JSON с "type": "service_account".')
    missing = [f for f in ("client_email", "private_key", "token_uri") if not info.get(f)]
    if missing:
        raise InvalidArguments(f"В ключе сервисного аккаунта нет полей: {', '.join(missing)}.")
    return info


def refresh_credentials(creds: Any, *, provider: str, action: str) -> str:
    """Получить/обновить access token у Google. Отказ → NotAuthorized, сеть → TokenRequestFailed."""
    import google.auth.exceptions
    import google.auth.transport.requests

    try:
        creds.refresh(google.auth.transport.requests.Request())
    except google.auth.exceptions.RefreshError as exc:
        raise NotAuthorized(provider, f"Google отверг ключ сервисного аккаунта: {exc}", action=action) from exc
    except google.auth.exceptions.TransportError as exc:
        raise TokenRequestFailed(provider, f"не удалось получить токен: {exc}") from exc
    return creds.token


class GoogleAuth:
    """Всё об авторизации одного инструмента: найти ключи, выдать токен, сохранить, показать статус."""

    def __init__(self, profile: Profile, store: CredentialStore | None = None) -> None:
        self.profile = profile
        self.store = store or CredentialStore(profile)

    @property
    def login_action(self) -> str:
        return f"Выполните '{self.profile.login_cmd}'."

    # --- сервисный аккаунт ---------------------------------------------------------

    def find_service_account(self) -> Found | None:
        """JSON ключа и откуда он, или None. Порядок: env с JSON → env с путём к файлу → keychain.

        Содержимое не проверяет. Переменная с путём к несуществующему файлу — NotAuthorized.
        """
        env = self.store.first_env(self.store.service_account_json_env())
        if env:
            return Found(env[0], "env", env[1])
        path_env = self.store.first_env(self.store.service_account_file_env())
        if path_env:
            file = Path(path_env[0]).expanduser()
            if not file.is_file():
                raise NotAuthorized(
                    self.profile.provider,
                    f"{path_env[1]} указывает на несуществующий файл: {file}",
                    action=self.login_action,
                )
            return Found(file.read_text(encoding="utf-8"), "file", str(file))
        stored = self.store.get(SERVICE_ACCOUNT)
        if stored:
            return Found(stored, "keychain", self.store.service_name(SERVICE_ACCOUNT))
        return None

    def load_service_account(self) -> dict[str, Any]:
        """Словарь ключа сервисного аккаунта; нет или битый — NotAuthorized с командой-исправлением."""
        found = self.find_service_account()
        if found is None:
            raise NotAuthorized(
                self.profile.provider, "Нет ключа сервисного аккаунта Google.", action=self.login_action
            )
        try:
            return parse_service_account(found.value)
        except InvalidArguments as exc:
            raise NotAuthorized(
                self.profile.provider,
                f"Ключ из {found.source} ({found.origin}): {exc.message}",
                action=self.login_action,
            ) from exc

    def credentials(self, scopes: list[str] | tuple[str, ...] | None = None) -> Any:
        """google-auth Credentials сервисного аккаунта (токен ещё не получен). scopes по умолчанию — первый из профиля."""
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(
            self.load_service_account(), scopes=list(scopes or self.profile.scopes[:1])
        )

    def refresh(self, creds: Any) -> str:
        """Получить/обновить access token для creds (см. `refresh_credentials`)."""
        return refresh_credentials(
            creds, provider=self.profile.provider, action=f"Выполните '{self.profile.login_cmd}' с новым ключом."
        )

    def bearer(self, scopes: list[str] | tuple[str, ...] | None = None) -> BearerToken:
        """Держатель токена для клиента API: `headers()` на каждый запрос, обновление — само."""
        return BearerToken(self, scopes)

    def store_service_account(self, text: str) -> dict[str, Any]:
        """Проверить JSON ключа и положить в общий слот keychain. Возвращает разобранный ключ."""
        info = parse_service_account(text)
        self.store.set(SERVICE_ACCOUNT, text)
        return info

    # --- API-ключи ---------------------------------------------------------------------

    def find_api_key(self, name: str) -> Found | None:
        """API-ключ и откуда он. Порядок: переменные инструмента → общая `GOOGLE_OAUTH_<NAME>_API_KEY` → keychain."""
        key = self.profile.api_key(name)
        env = self.store.first_env(self.store.api_key_env(key))
        if env:
            return Found(env[0], "env", env[1])
        stored = self.store.get(API_KEY, name)
        if stored:
            return Found(stored, "keychain", f"{self.store.service_name(API_KEY)}/{name}")
        return None

    def api_key(self, name: str) -> str | None:
        found = self.find_api_key(name)
        return found.value if found else None

    def store_api_key(self, name: str, value: str) -> None:
        self.profile.api_key(name)  # неизвестное имя — KeyError, а не мусор в keychain
        value = value.strip()
        if not value:
            raise InvalidArguments("Пустой API-ключ.")
        self.store.set(API_KEY, value, name)

    # --- выход и статус ------------------------------------------------------------------

    def logout(self, provider: str) -> None:
        """Удалить из общего слота keychain ключ сервисного аккаунта или API-ключ (env не трогает)."""
        if provider == self.profile.provider:
            self.store.delete(SERVICE_ACCOUNT)
        else:
            self.profile.api_key(provider)
            self.store.delete(API_KEY, provider)

    def status(self, *, check: bool = False) -> AuthStatus:
        """Что есть из авторизации. Без check — без сети; check=True — ещё и получает токен у Google."""
        api_keys = {key.name: self.find_api_key(key.name) is not None for key in self.profile.api_keys}
        status = AuthStatus(provider=self.profile.provider, state="missing", api_keys=api_keys)
        try:
            found = self.find_service_account()
            if found is None:
                status.detail = f"выполните '{self.profile.login_cmd}'"
                return status
            info = parse_service_account(found.value)
        except (NotAuthorized, InvalidArguments) as exc:
            status.detail = exc.message
            return status
        status.state, status.account, status.source = "ok", info["client_email"], found.source
        if check:
            try:
                self.refresh(self.credentials())
            except NotAuthorized as exc:
                status.state, status.detail = "expired", exc.message
        return status


class BearerToken:
    """Access token сервисного аккаунта для заголовка Authorization.

    Ключ читается при первом `headers()`, токен обновляется, когда google-auth
    считает его невалидным (истёк или истекает с запасом по времени).
    """

    def __init__(self, auth: GoogleAuth, scopes: list[str] | tuple[str, ...] | None = None) -> None:
        self.auth = auth
        self.scopes = scopes
        self._creds: Any = None

    def token(self) -> str:
        if self._creds is None:
            self._creds = self.auth.credentials(self.scopes)
        if not self._creds.valid:
            self.auth.refresh(self._creds)
        return self._creds.token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}
