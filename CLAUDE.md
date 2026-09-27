# CLAUDE.md

## Commands

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

## Что это

Общая библиотека авторизации Google для CLI-инструментов `~/Projects/tools/` (`gsc`, …), построенных по единой CLI-архитектуре (skill `cli-generator:cli-builder`). Аналог `yandex-oauth`. Не CLI сама по себе — подключается git-источником в `[tool.uv.sources]` инструмента, см. README.

**Source layout:** `src/google_oauth/`

- `profile.py` — `Profile` (cli_name, service, scopes, env инструмента, `api_keys: tuple[ApiKey]`, login_hint, `keychain_namespace="google-oauth"`, provider=`google`) — единственное, чем инструменты отличаются
- `errors.py` — `CliError` (общий базовый: `output.guard` инструментов ловит его), `InvalidArguments`, `NotAuthorized(provider, reason, action=)`, `TokenRequestFailed`, `CredentialStoreUnavailable`
- `credentials.py` — `CredentialStore`: keychain `google-oauth:<kind>` / `<name>` через `keyring`, имена env (`<tool env…>` → `GOOGLE_OAUTH_…`), `backend()`
- `auth.py` — `GoogleAuth` (find/load/store сервисного аккаунта и API-ключей, `credentials`, `refresh`, `bearer`, `status`, `logout`), `AuthStatus.to_dict()`, `BearerToken`, `parse_service_account`, `refresh_credentials`
- `auth_command.py` — `make_auth_app(auth, output, check=None)`: `auth login|logout|status [--check]`; вопросы в stderr, stdout чист для `--json`

**Никаких `.env` и ADC:** секреты только в keychain и переменных окружения; `google.auth.default()` не используется намеренно (подхватил бы доступы gcloud).

**Инварианты, которые нельзя ломать (на них завязаны тесты инструментов):**
- `keyring.get_password/set_password/delete_password` вызываются через атрибут модуля `google_oauth.credentials.keyring` — тесты инструментов патчат его (напрямую или через реэкспорт).
- Импорт `google_oauth` не тянет `typer` и `google.auth` (есть тест); `auth_command` импортируется отдельно.
- `AuthStatus.to_dict()` — плоский JSON `{"<provider>", "<key>_key"…, "account", "source", "detail"}`: это формат `gsc auth status --json`.
- Чтение из недоступного keychain — не ошибка (warning в лог), запись/удаление — `CredentialStoreUnavailable`.

**Тесты:** `tests/fake_output.py` — минимальный `output`-модуль; `conftest.py` подменяет keyring словарём (ключи `("google-oauth:service_account", "default")`, `("google-oauth:api_key", "pagespeed")`) и чистит env `DEMO_*`/`GOOGLE_OAUTH_*`.
