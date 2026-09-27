"""Контракт `<cli> auth status [--check] --json` (tools/docs/standard-release.md §8).

Два способа встроиться — оба дают одинаковые статусы у всех Google-инструментов:

- инструмент по шаблону cli-generator: его `Provider.health_check()` делегирует сюда,
  а `source`/`required` запись отчёта добавляет сам CLI —

      def health_check(self) -> Health:
          return google_oauth.health_check(GOOGLE_AUTH, check=lambda: self.get_json("/sites"))

  (`google_oauth.Health` совпадает по полям с `providers.base.Health` шаблона);
  для API-ключа — `health_check(GOOGLE_AUTH, check, provider="pagespeed")`;
- инструмент на `make_auth_app`: команда `auth status` собирает весь отчёт из
  `credential_status` + `status_report`, а exit-код и ошибку `CREDENTIALS_UNHEALTHY` —
  из `status_exit_code` / `status_problems`.

Значения секретов в отчёт не попадают — только имена переменных, путь к файлу
и слот keychain; сообщения ошибок от них очищаются.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .auth import GoogleAuth, parse_service_account
from .credentials import CredentialStore
from .errors import CliError, InvalidArguments, NotAuthorized

EXIT_OK = 0
EXIT_PROBLEM = 3
CHECK_TIMEOUT = 10.0  # §8: жёсткий лимит на проверку одного провайдера, без повторов
HEALTHY = frozenset({"ok", "unchecked"})
# Проблема даже для необязательного провайдера: учётные данные есть, но негодные.
ALWAYS_PROBLEMS = frozenset({"invalid", "expired"})

HealthStatus = Literal["ok", "invalid", "expired", "quota_exhausted", "unreachable"]


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    limit: int | None = None
    unit: str = "requests"


@dataclass(frozen=True)
class Health:
    """Итог живой проверки — поля как у `providers.base.Health` шаблона cli-generator."""

    status: HealthStatus = "ok"
    expires_at: datetime | None = None
    quota: Quota | None = None
    message: str | None = None


def health_check(
    auth: GoogleAuth,
    check: Callable[[], object] | None = None,
    *,
    provider: str | None = None,
    timeout: float = CHECK_TIMEOUT,
) -> Health:
    """Живая проверка для `Provider.health_check()` инструмента: статус и сообщение.

    provider — сервисный аккаунт (по умолчанию) или имя API-ключа из профиля.
    Сервисный аккаунт: access token у Google (бесплатно, заодно проверка ключа),
    затем `check`, если задан. API-ключ: только `check` — самый дешёвый read-only
    запрос инструмента с этим ключом (без него проверять нечем → ValueError).
    Всё вместе ограничено `timeout` секундами. Ошибки → статус: 401/403 и отказ
    Google выдать токен → `invalid`; сеть, HTTP 429/5xx, CliError с exit_code 5,
    таймаут → `unreachable`; прочие CliError → `invalid`.
    Наличие ключа (`missing`) решает вызывающий — сюда приходят, когда он есть.
    `expires_at` всегда None: у ключей сервисного аккаунта и API-ключей нет срока,
    а час жизни access token — не срок учётных данных.
    """
    provider = provider or auth.profile.provider
    if provider != auth.profile.provider:
        auth.profile.api_key(provider)  # неизвестное имя — KeyError сразу, а не статус
        if check is None:
            raise ValueError(f"health_check для API-ключа '{provider}' требует check — запрос с этим ключом.")
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_probe, auth, provider, check).result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return Health(status="unreachable", message=f"Нет ответа за {timeout:g} с.")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _probe(auth: GoogleAuth, provider: str, check: Callable[[], object] | None) -> Health:
    secrets: list[str | None] = []
    try:
        if provider == auth.profile.provider:
            info = auth.load_service_account()
            secrets.append(info.get("private_key"))
            creds = auth.credentials()
            secrets.append(auth.refresh(creds))
        else:
            secrets.append(auth.api_key(provider))
        if check is not None:
            check()
    except Exception as exc:
        return Health(status=_failure_status(exc), message=_scrub(_message(exc), secrets))
    return Health(status="ok")


def _http_status(exc: BaseException | None) -> int | None:
    """Код HTTP-ответа из исключения клиента (httpx, requests) — без импорта самих клиентов."""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _failure_status(exc: Exception) -> HealthStatus:
    code = _http_status(exc) or _http_status(exc.__cause__)
    if code is not None:
        return "invalid" if code in (401, 403) else "unreachable"
    if isinstance(exc, NotAuthorized | InvalidArguments):
        return "invalid"
    if isinstance(exc, CliError):
        return "unreachable" if exc.exit_code == 5 else "invalid"
    return "unreachable"


def _message(exc: Exception) -> str:
    return exc.message if isinstance(exc, CliError) else f"{type(exc).__name__}: {exc}"


def _scrub(message: str, secrets: list[str | None]) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if moment else None


def credential_status(
    auth: GoogleAuth,
    provider: str | None = None,
    *,
    live: bool = False,
    check: Callable[[], object] | None = None,
    required: bool | None = None,
) -> dict:
    """Один элемент `credentials` отчёта: откуда ключ и (под `live`) принимает ли его Google/API.

    provider — сервисный аккаунт (по умолчанию) или имя API-ключа.
    live     — флаг `--check`: без него только наличие (`unchecked`/`missing`/`invalid`), без сети.
    check    — запрос к API инструмента. Сервисный аккаунт под `live` проверяется и без него
               (получением токена); API-ключ без него — `unchecked`.
    required — по умолчанию: сервисный аккаунт обязателен, API-ключ — как `ApiKey.required`.
    """
    profile, store = auth.profile, auth.store
    provider = provider or profile.provider
    is_sa = provider == profile.provider
    if required is None:
        required = True if is_sa else profile.api_key(provider).required
    entry: dict = {
        "provider": provider,
        "required": required,
        "fields": ["service_account_json" if is_sa else "api_key"],
        "source": "missing",
        "source_ref": None,
        "status": "missing",
        "expires_at": None,
        "quota": None,
        "message": None,
    }

    if is_sa:
        env_names = store.service_account_json_env() + store.service_account_file_env()
        keychain_ref = f"keychain service {store.service_name('service_account')}"
        login = profile.login_cmd
        try:
            found = auth.find_service_account()
        except NotAuthorized as exc:  # переменная указывает на несуществующий файл
            entry.update(source="file", source_ref=_file_env(store), message=exc.message)
            return entry
    else:
        key = profile.api_key(provider)
        env_names = store.api_key_env(key)
        keychain_ref = f"keychain service {store.service_name('api_key')}/{provider}"
        login = profile.api_key_login_cmd(provider)
        found = auth.find_api_key(provider)

    if found is None:
        reason = store.unavailable_reason
        entry["source_ref"] = " or ".join([*env_names, keychain_ref])
        entry["message"] = (f"Keychain недоступен ({reason}). " if reason else "") + (
            f"Нет ключа: выполните '{login}' или задайте {env_names[0]}."
        )
        return entry

    source_ref = {"env": found.origin, "file": found.origin, "keychain": f"keychain service {found.origin}"}
    entry.update(source=found.source, source_ref=source_ref[found.source])
    if is_sa:
        try:
            parse_service_account(found.value)
        except InvalidArguments as exc:
            entry.update(status="invalid", message=exc.message)
            return entry

    if not live:
        entry["status"] = "unchecked"
        return entry
    if check is None and not is_sa:
        entry.update(status="unchecked", message="Инструмент не задал проверочного запроса к API.")
        return entry

    health = health_check(auth, check, provider=provider)
    entry.update(
        status=health.status,
        expires_at=_iso(health.expires_at),
        quota=vars(health.quota) if health.quota else None,
        message=health.message,
    )
    return entry


def _file_env(store: CredentialStore) -> str:
    """Имя переменной с путём к файлу ключа, которая задана (для source_ref)."""
    found = store.first_env(store.service_account_file_env())
    return found[1] if found else ", ".join(store.service_account_file_env())


def status_report(tool: str, version: str, credentials: list[dict]) -> dict:
    """Весь отчёт `auth status` по §8: инструмент, версия, время проверки, список учётных данных.

    Конверт (`ok`, а при exit 3 — ещё `error` CREDENTIALS_UNHEALTHY) добавляет команда.
    """
    return {
        "tool": tool,
        "version": version,
        "checked_at": _iso(_now()),
        "credentials": credentials,
    }


def is_problem(entry: dict) -> bool:
    """Запись валит `auth status`: invalid/expired — всегда, прочее не ok/unchecked — если провайдер обязателен."""
    if entry["status"] in ALWAYS_PROBLEMS:
        return True
    return entry["required"] and entry["status"] not in HEALTHY


def status_problems(report: dict) -> dict[str, str]:
    """Провайдер → статус для всех проблемных записей (для ошибки CREDENTIALS_UNHEALTHY)."""
    return {entry["provider"]: entry["status"] for entry in report["credentials"] if is_problem(entry)}


def status_exit_code(report: dict) -> int:
    """0 — нет проблемных записей (см. `is_problem`), иначе 3."""
    return EXIT_PROBLEM if status_problems(report) else EXIT_OK
