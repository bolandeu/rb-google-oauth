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
from datetime import UTC, datetime

from rb_credentials.status import (
    Health,
    HealthStatus,
    Quota,  # noqa: F401 — public here since 0.1 (`google_oauth.Quota`)
    entry,
    exit_code,
    iso,
    problems,
    report,
    scrub,
)

from .auth import GoogleAuth, parse_service_account
from .credentials import CredentialStore
from .errors import CliError, InvalidArguments, NotAuthorized

CHECK_TIMEOUT = 10.0  # §8: жёсткий лимит на проверку одного провайдера, без повторов

# Форма отчёта — одна на весь набор пакетов (rb-credentials, ADR 0017); ниже имена, которые зовут с 0.1.
status_report = report
status_problems = problems
status_exit_code = exit_code


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
        return Health(status="unreachable", message=f"No response within {timeout:g} s.")
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
        return Health(status=_failure_status(exc), message=scrub(_message(exc), secrets))
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


def _now() -> datetime:
    return datetime.now(UTC)


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
    record = entry(provider, required=required, fields=["service_account_json" if is_sa else "api_key"])

    if is_sa:
        env_names = store.service_account_json_env() + store.service_account_file_env()
        keychain_ref = f"keychain service {store.service_name('service_account')}"
        login = profile.login_cmd
        try:
            found = auth.find_service_account()
        except NotAuthorized as exc:  # переменная указывает на несуществующий файл
            record.update(source="file", source_ref=_file_env(store), message=exc.message)
            return record
    else:
        key = profile.api_key(provider)
        env_names = store.api_key_env(key)
        keychain_ref = f"keychain service {store.service_name('api_key')}/{provider}"
        login = profile.api_key_login_cmd(provider)
        found = auth.find_api_key(provider)

    if found is None:
        reason = store.unavailable_reason
        record["source_ref"] = " or ".join([*env_names, keychain_ref])
        record["message"] = (f"Keychain unavailable ({reason}). " if reason else "") + (
            f"No key: run '{login}' or set {env_names[0]}."
        )
        return record

    source_ref = {"env": found.origin, "file": found.origin, "keychain": f"keychain service {found.origin}"}
    record.update(source=found.source, source_ref=source_ref[found.source])
    if is_sa:
        try:
            parse_service_account(found.value)
        except InvalidArguments as exc:
            record.update(status="invalid", message=exc.message)
            return record

    if not live:
        record["status"] = "unchecked"
        return record
    if check is None and not is_sa:
        record.update(status="unchecked", message="The tool set no API check.")
        return record

    health = health_check(auth, check, provider=provider)
    record.update(
        status=health.status,
        expires_at=iso(health.expires_at),
        quota=vars(health.quota) if health.quota else None,
        message=health.message,
    )
    return record


def _file_env(store: CredentialStore) -> str:
    """Имя переменной с путём к файлу ключа, которая задана (для source_ref)."""
    found = store.first_env(store.service_account_file_env())
    return found[1] if found else ", ".join(store.service_account_file_env())
