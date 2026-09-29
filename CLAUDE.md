# CLAUDE.md

## Commands

```bash
uv sync
uv run scripts/release.py --check   # гейт перед каждым коммитом
```

## Что это

Дистрибутив `rb-google-oauth` (импорт `google_oauth`). Общая библиотека авторизации Google для CLI-инструментов `~/Projects/tools/` (`gsc`, …), построенных по единой CLI-архитектуре (skill `cli-generator:cli-builder`). Аналог `yandex-oauth`. Не CLI сама по себе — подключается git-источником в `[tool.uv.sources]` инструмента, см. README.

**Source layout:** `src/google_oauth/`

- `profile.py` — `Profile` (cli_name, service, scopes, env инструмента, `api_keys: tuple[ApiKey]`, login_hint, `keychain_namespace="google-oauth"`, provider=`google`) — единственное, чем инструменты отличаются
- `errors.py` — `CliError` (общий базовый: `output.guard` инструментов ловит его), `InvalidArguments`, `NotAuthorized(provider, reason, action=)`, `TokenRequestFailed`, `CredentialStoreUnavailable`
- `credentials.py` — `CredentialStore`: keychain `google-oauth:<kind>` / `<name>` через `keyring`, имена env (`<tool env…>` → `GOOGLE_OAUTH_…`), `backend()`
- `auth.py` — `GoogleAuth` (find/load/store сервисного аккаунта и API-ключей, `credentials`, `refresh`, `bearer`, `status`, `logout`), `AuthStatus.to_dict()`, `BearerToken`, `parse_service_account`, `refresh_credentials`
- `status.py` — контракт `auth status` (§8 стандарта tools): `health_check` (делегат для `Provider.health_check()` инструментов), `credential_status`, `status_report`, `status_problems`, `status_exit_code`
- `auth_command.py` — `make_auth_app(auth, output, check=None, api_key_checks=None)`: `auth login|logout|status [--check]`; вопросы в stderr, stdout чист для `--json`; docstring'и команд — их `--help` (плейсхолдеры `{cli}` и т.п., строка `Example:` обязательна, снапшоты в `tests/snapshots/help/`)

**Никаких `.env` и ADC:** секреты только в keychain и переменных окружения; `google.auth.default()` не используется намеренно (подхватил бы доступы gcloud).

**Инварианты, которые нельзя ломать (на них завязаны тесты инструментов):**
- `keyring.get_password/set_password/delete_password` вызываются через атрибут модуля `google_oauth.credentials.keyring` — тесты инструментов патчат его (напрямую или через реэкспорт).
- Импорт `google_oauth` не тянет `typer` и `google.auth` (есть тест); `auth_command` импортируется отдельно.
- Форма `auth status --json` — §8 стандарта tools (`tests/test_status.py`); её изменение — ломающее. `GoogleAuth.status()`/`AuthStatus` — старый плоский статус, им пользуется gsc (`core/auth.py`).
- Чтение из недоступного keychain — не ошибка (warning в лог), запись/удаление — `CredentialStoreUnavailable`.

**Тесты:** `tests/fake_output.py` — минимальный `output`-модуль; `conftest.py` подменяет keyring словарём (ключи `("google-oauth:service_account", "default")`, `("google-oauth:api_key", "pagespeed")`) и чистит env `DEMO_*`/`GOOGLE_OAUTH_*`.

## Каждое заметное изменение выходит релизом

Серверы, другие инструменты и Mac ставят только по тегам, не из `main`:
влитое без релиза изменение для них не существует. Изменение с фрагментом
changelog закончено только после релиза: влить в `main` →
`uv run scripts/release.py patch|minor|major` → попросить пользователя
сделать push с `--follow-tags` → назвать новый тег в отчёте. Служебные коммиты
(без фрагмента) ждут следующего релиза. Не оставлять фрагмент на `main` без
релиза, не назвав причину (`~/Projects/tools/docs/standard-release.md` §3).

## Инструмент в системе

Инструмент — один из сервисов `~/Projects/tools/`: корневой агент его
деплоит, хранит ключи (Doppler) и бэкапит данные (S3). Полные правила —
`~/Projects/tools/docs/standard-release.md` §13.

- **Сообщать корневому агенту** (в отчёте пользователю, рядом с тегом
  релиза): новая или переименованная переменная окружения / ключ, новая
  локальная база или новый путь к данным, новая или убранная зависимость от
  другого инструмента, обновлённый токен сохраняется локально, ломающий релиз.
- **Потребители**: перед ломающим изменением проверить, кто пользуется
  инструментом (корневой `AGENTS.md` → Service map), и назвать их в отчёте.
- **Серверы Linux без экрана**: сначала переменные окружения, keychain
  необязателен (его отсутствие при заданной переменной — не ошибка); имена
  переменных — уже существующие; без TTY никаких вопросов; без путей только для Mac.
- **Локальные данные** — в `platformdirs.user_data_dir("<tool>")`, не в
  репозитории; всё состояние — в файле базы, миграции делает сам инструмент;
  сам инструмент данные никуда не выгружает.
