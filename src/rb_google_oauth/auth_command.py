"""Готовая Typer-команда `auth login|logout|status [--check]` — одна на все Google-инструменты.

Инструмент передаёт свой `output`-модуль (guard/emit_success/опции — из общей
CLI-архитектуры), чтобы вывод, JSON-конверт и обработка ошибок были ровно
такими же, как у его собственных команд.
"""

from __future__ import annotations

import getpass
import inspect
import json
import sys
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path
from types import ModuleType

import typer

from . import status as status_mod
from .auth import GoogleAuth
from .errors import CredentialsUnhealthy, InvalidArguments


def _ask(text: str, *, hide: bool = False) -> str:
    """Спросить строку. Вопрос — в stderr (stdout чист для --json); скрытый ввод — только в терминале."""
    if hide and sys.stdin.isatty():
        return getpass.getpass(f"{text}: ", stream=sys.stderr).strip()
    sys.stderr.write(f"{text}: ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise typer.Abort()
    return line.strip()


def _read_key_file(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        raise InvalidArguments(f"Файл не найден: {file}")
    return file.read_text(encoding="utf-8")


def make_auth_app(
    auth: GoogleAuth,
    output: ModuleType,
    *,
    check: Callable[[typer.Context], None] | None = None,
    api_key_checks: Mapping[str, Callable[[typer.Context], None]] | None = None,
) -> typer.Typer:
    """Собрать sub-app `auth` для инструмента.

    check — необязательный живой запрос к API инструмента для `auth status --check`
    (поверх получения токена сервисного аккаунта); должен бросать CliError при отказе API.
    api_key_checks — имя API-ключа → такой же запрос с этим ключом; без него ключ
    под `--check` остаётся `unchecked`.

    Docstring'и команд — это их `--help`: подстановки `{cli}`, `{provider}` и т.п.
    заполняет `_help`, строка `Example:` обязательна (стандарт tools §7).
    """
    profile = auth.profile
    store = auth.store
    human = output.human
    key_checks = dict(api_key_checks or {})
    app = typer.Typer(help=f"Доступы Google для {profile.service}: ключ сервисного аккаунта и API-ключи (keychain ОС).")

    key_help = "; ".join(f"{k.name} — API-ключ {k.title}" for k in profile.api_keys)
    provider_option = typer.Option(
        profile.provider,
        "--provider",
        help=f"{profile.provider} — сервисный аккаунт" + (f"; {key_help}." if key_help else "."),
    )
    placeholders = {
        "{cli}": profile.cli_name,
        "{provider}": profile.provider,
        "{login_hint}": profile.login_hint,
        "{sa_env}": " / ".join(store.service_account_json_env() + store.service_account_file_env()),
        "{key_lines}": "\n\n".join(
            f"{k.name}: API-ключ {k.title} из {' / '.join(store.api_key_env(k))}, иначе спросит скрытым вводом."
            + (f" {k.hint}" if k.hint else "")
            for k in profile.api_keys
        ),
        "{key_examples}": "".join(f"\n  {profile.api_key_login_cmd(k.name)}" for k in profile.api_keys),
    }

    def _help(func: Callable) -> Callable:
        # Отступ убран до подстановки: многострочные значения вставляются без отступа
        # (Python 3.13+ и так убирает его при компиляции, 3.11–3.12 — нет).
        doc = inspect.cleandoc(func.__doc__ or "")
        for key, value in placeholders.items():
            doc = doc.replace(key, value)
        func.__doc__ = doc
        return func

    def _provider(value: str) -> str:
        if value not in profile.providers:
            raise InvalidArguments(f"Неизвестный --provider '{value}': допустимо {', '.join(profile.providers)}.")
        return value

    def _non_interactive(ctx: typer.Context, flag: bool) -> bool:
        return bool(ctx.obj.get("non_interactive") or flag)

    def _login_service_account(file: Path | None, non_interactive: bool) -> dict:
        if file is not None:
            text = _read_key_file(str(file))
        else:
            found = auth.find_service_account()
            if found and found.source in ("env", "file"):
                text = found.value
            elif non_interactive:
                raise InvalidArguments(
                    f"Нужен --file <service-account.json> (или {store.service_account_json_env()[0]} в окружении): "
                    "задан --non-interactive."
                )
            else:
                text = _read_key_file(_ask("Путь к JSON-ключу сервисного аккаунта"))
        info = auth.store_service_account(text)
        return {"provider": profile.provider, "account": info["client_email"], "stored": "keychain"}

    def _login_api_key(name: str, non_interactive: bool) -> dict:
        key = profile.api_key(name)
        found = auth.find_api_key(name)
        if found and found.source == "env":
            value = found.value
        elif non_interactive:
            raise InvalidArguments(f"Нет {' / '.join(store.api_key_env(key))} в окружении, а задан --non-interactive.")
        else:
            value = _ask(f"API-ключ {key.title}", hide=True)
        auth.store_api_key(name, value)
        return {"provider": name, "account": None, "stored": "keychain"}

    # --- login ---------------------------------------------------------------------

    @app.command("login")
    @output.guard
    @_help
    def login(
        ctx: typer.Context,
        provider: str = provider_option,
        file: Path | None = typer.Option(
            None, "--file", "-f", dir_okay=False, help="JSON-ключ сервисного аккаунта (для --provider по умолчанию)."
        ),
        non_interactive: bool = output.NonInteractiveOption,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        """Сохранить доступ Google в общий слот keychain ОС (один на все Google-инструменты).

        {provider}: JSON-ключ сервисного аккаунта — из --file, иначе из
        {sa_env}, иначе спросит путь к файлу.
        {login_hint}

        {key_lines}

        --json: {"ok": true, "provider", "account", "stored"}.

        \b
        Примеры:
          {cli} auth login --file ~/Downloads/service-account.json{key_examples}

        Example: {cli} auth login --file ~/Downloads/service-account.json
        """
        non_int = _non_interactive(ctx, non_interactive)
        provider = _provider(provider)
        if provider == profile.provider:
            result = _login_service_account(file, non_int)
        else:
            if file is not None:
                raise InvalidArguments(f"--file только для --provider {profile.provider}.")
            result = _login_api_key(provider, non_int)

        def render(d: dict) -> None:
            if d["account"]:
                human.echo(f"Сохранено в keychain: сервисный аккаунт {d['account']}")
                if profile.login_hint:
                    human.echo(profile.login_hint)
            else:
                human.echo(f"Сохранено в keychain: API-ключ {d['provider']}")

        output.emit_success(ctx, result, render)

    # --- logout --------------------------------------------------------------------

    @app.command("logout")
    @output.guard
    @_help
    def logout(
        ctx: typer.Context,
        provider: str = provider_option,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        """Удалить доступ из общего слота keychain — для всех Google-инструментов (переменные окружения не трогает).

        --json: {"ok": true, "provider"}.

        Example: {cli} auth logout
        """
        provider = _provider(provider)
        auth.logout(provider)
        output.emit_success(ctx, {"provider": provider}, lambda d: human.echo(f"Удалено из keychain: {d['provider']}"))

    # --- status --------------------------------------------------------------------

    @app.command("status")
    @output.guard
    @_help
    def auth_status(
        ctx: typer.Context,
        check_flag: bool = typer.Option(
            False, "--check", help="Проверить ключи у Google и одним дешёвым запросом к API (не дольше 10 с на ключ)."
        ),
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        """Откуда берутся ключи и работают ли они — отчёт в общей для всех инструментов форме. Значений не печатает.

        Записи: {provider} (сервисный аккаунт, обязателен) и API-ключи инструмента.
        Без --check — только наличие (`unchecked`, `missing`, `invalid` — битый JSON), без сети.
        Код выхода 0 — всё в порядке, 3 — обязательного ключа нет или Google/API его не принимает.
        --json — контракт для tools-watch (стандарт tools §8): `tool`, `version`,
        `checked_at`, `credentials[]` с `provider`, `required`, `fields`, `source`,
        `source_ref`, `status`, `expires_at`, `quota`, `message`; при коде 3 —
        `ok: false` и `error` CREDENTIALS_UNHEALTHY рядом с отчётом.

        Example: {cli} auth status --check --json
        """
        entries = [
            status_mod.credential_status(
                auth, live=check_flag, check=(lambda: check(ctx)) if check is not None else None
            )
        ]
        for key in profile.api_keys:
            key_check = key_checks.get(key.name)
            entries.append(
                status_mod.credential_status(
                    auth,
                    key.name,
                    live=check_flag,
                    check=(lambda c=key_check: c(ctx)) if key_check is not None else None,
                )
            )
        report = status_mod.status_report(profile.cli_name, _tool_version(profile.cli_name), entries)
        problems = status_mod.status_problems(report)
        if not problems:
            output.emit_success(ctx, report, _render_status)
            return
        error = CredentialsUnhealthy(profile, problems)
        if ctx.obj.get("json"):
            typer.echo(json.dumps({"ok": False, "error": error.to_dict(), **report}, ensure_ascii=False))
        else:
            if not ctx.obj.get("quiet"):
                _render_status(report)
            typer.echo(f"Error: {error.message}", err=True)
            typer.echo(error.action, err=True)
        raise typer.Exit(code=error.exit_code)

    def _render_status(report: dict) -> None:
        for entry in report["credentials"]:
            mark = {"ok": "✓", "unchecked": "·"}.get(entry["status"], "✗")
            detail = f" — {entry['message']}" if entry["message"] else ""
            line = f"{entry['provider']}: {entry['status']} ({entry['source']}: {entry['source_ref']}){detail}"
            human.echo(f"{mark} {_escape(line)}")

    return app


def _tool_version(cli_name: str) -> str:
    """Версия инструмента-потребителя: дистрибутив, который ставит console script `cli_name`.

    По entry point, а не по имени пакета: так работает и для editable-установки.
    """
    for entry_point in metadata.entry_points(group="console_scripts", name=cli_name):
        if entry_point.dist is not None:
            return entry_point.dist.version
    return "0.0.0"


def _escape(text: str) -> str:
    """Экранировать `[` для rich-разметки `human.echo` (в source_ref/message бывают скобки)."""
    return text.replace("[", "\\[")
