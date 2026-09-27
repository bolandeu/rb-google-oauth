"""Готовая Typer-команда `auth login|logout|status` — одна на все Google-инструменты.

Инструмент передаёт свой `output`-модуль (guard/emit_success/опции — из общей
CLI-архитектуры), чтобы вывод, JSON-конверт и обработка ошибок были ровно
такими же, как у его собственных команд.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import typer

from .auth import GoogleAuth
from .errors import CliError, InvalidArguments


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
) -> typer.Typer:
    """Собрать sub-app `auth` для инструмента.

    check — необязательный живой запрос к API инструмента для `auth status --check`
    (поверх получения токена); должен бросать CliError при отказе API.
    """
    profile = auth.profile
    store = auth.store
    human = output.human
    app = typer.Typer(help=f"Доступы Google для {profile.service}: ключ сервисного аккаунта и API-ключи (keychain ОС).")

    key_help = "; ".join(f"{k.name} — API-ключ {k.title}" for k in profile.api_keys)
    provider_option = typer.Option(
        profile.provider,
        "--provider",
        help=f"{profile.provider} — сервисный аккаунт" + (f"; {key_help}." if key_help else "."),
    )

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

    sa_env = " / ".join(store.service_account_json_env() + store.service_account_file_env())
    key_lines = "\n\n    ".join(
        f"{k.name}: API-ключ {k.title} из {' / '.join(store.api_key_env(k))}, иначе спросит скрытым вводом."
        + (f" {k.hint}" if k.hint else "")
        for k in profile.api_keys
    )
    login.__doc__ = f"""Сохранить доступ Google в общий слот keychain ОС (один на все Google-инструменты).

    {profile.provider}: JSON-ключ сервисного аккаунта — из --file, иначе из
    {sa_env}, иначе спросит путь к файлу.
    {profile.login_hint}

    {key_lines}

    --json: {{"ok": true, "provider", "account", "stored"}}.

    \b
    Примеры:
      {profile.cli_name} auth login --file ~/Downloads/service-account.json
    """ + "".join(f"      {profile.api_key_login_cmd(k.name)}\n" for k in profile.api_keys)
    app.command("login")(output.guard(login))

    # --- logout --------------------------------------------------------------------

    def logout(
        ctx: typer.Context,
        provider: str = provider_option,
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        """Удалить доступ из общего слота keychain — для всех Google-инструментов (переменные окружения не трогает).

        --json: {"ok": true, "provider"}.
        """
        provider = _provider(provider)
        auth.logout(provider)
        output.emit_success(ctx, {"provider": provider}, lambda d: human.echo(f"Удалено из keychain: {d['provider']}"))

    app.command("logout")(output.guard(logout))

    # --- status --------------------------------------------------------------------

    def status(
        ctx: typer.Context,
        check_flag: bool = typer.Option(
            False, "--check", help="Ещё и получить токен у Google — проверка, что ключ не отозван."
        ),
        json_output: bool = output.JsonOption,
        quiet: bool = output.QuietOption,
    ) -> None:
        result = auth.status(check=check_flag)
        payload = result.to_dict()
        if check_flag and check is not None and result.state == "ok":
            try:
                check(ctx)
                payload["valid"] = True
            except CliError as exc:
                payload["valid"] = False
                payload["error"] = exc.message

        def render(d: dict) -> None:
            line = f"Сервисный аккаунт: {d[profile.provider]}"
            if d["account"]:
                line += f" ({d['account']}, {d['source']})"
            human.echo(line)
            for key in profile.api_keys:
                present = d[f"{key.name}_key"]
                human.echo(
                    f"{key.title}: "
                    + ("ключ есть" if present else f"ключа нет — {profile.api_key_login_cmd(key.name)}")
                )
            if d["detail"]:
                human.echo(f"Подробности: {d['detail']}")
            if "valid" in d:
                human.echo("API принимает доступ." if d["valid"] else f"API отверг доступ: {d['error']}")

        output.emit_success(ctx, payload, render)

    status.__doc__ = f"""Что есть из доступов: сервисный аккаунт (email, откуда взят) и API-ключи.

    {profile.provider}: ok | missing | expired (expired — только с --check: Google отверг ключ).

    --json: {{"ok": true, "{profile.provider}", {", ".join(f'"{k.name}_key"' for k in profile.api_keys)}{", " if profile.api_keys else ""}"account", "source", "detail"}}.

    \b
      {profile.cli_name} auth status --json
      {profile.cli_name} auth status --check
    """
    app.command("status")(output.guard(status))

    return app
