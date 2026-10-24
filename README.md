# google-oauth (`rb-google-oauth`)

Общая авторизация Google для CLI-инструментов (`gsc`, …) — аналог [yandex-oauth](https://github.com/bolandeu/yandex-oauth) для Google. Один набор ключей — **в общем слоте keychain `google-oauth:*`** для всех инструментов: вход в любом из них авторизует остальные. Без дублирования кода и без `.env`-файлов.

Сейчас поддерживаются ключ **сервисного аккаунта** (access token получается и обновляется сам через `google-auth`) и **API-ключи** (PageSpeed Insights и другие). Вход пользователя через браузер (OAuth) пока не нужен, но схема хранения к нему готова (см. «Как добавить OAuth пользователя»).

Только macOS и Linux.

## Что даёт

| Объект | Назначение |
|---|---|
| `Profile` | Чем инструмент отличается: имя CLI, название сервиса, scopes, «исторические» env-переменные инструмента, нужные API-ключи (`ApiKey`), подсказка после входа |
| `GoogleAuth(profile)` | Найти ключ сервисного аккаунта / API-ключ, `credentials(scopes)` (google-auth), `refresh(creds)`, `bearer(scopes).headers()` — токен с автообновлением для каждого запроса, `status(check=)`, `store_*`, `logout` |
| `CredentialStore(profile)` | Keychain ОС через `keyring` + имена переменных окружения; `backend()` для `doctor` |
| `make_auth_app(auth, output, check=None, api_key_checks=None)` | Готовая Typer-команда `auth login / logout / status [--check]` (модуль `google_oauth.auth_command`); `auth status` — отчёт §8 стандарта tools |
| `health_check(auth, check=None, provider=None)` → `Health` | Делегат для `Provider.health_check()` инструмента по шаблону cli-generator (см. «Проверка доступов») |
| `credential_status`, `status_report`, `status_problems`, `status_exit_code` | Сборка отчёта `auth status --json` для инструмента со своей командой `auth` |
| Ошибки | `CliError` (базовый — его ловит `output.guard` инструмента), `InvalidArguments` (exit 2), `NotAuthorized` (exit 3), `TokenRequestFailed` (exit 5), `CredentialStoreUnavailable`, `CredentialsUnhealthy` (exit 3) |

Импорт `google_oauth` не трогает сеть, keychain, `google-auth` и `typer`.

## Где лежат ключи

| Что | Keychain (service / account) | Переменные окружения (по приоритету) |
|---|---|---|
| Ключ сервисного аккаунта (JSON) | `google-oauth:service_account` / `default` | env инструмента из профиля (например `GSC_GOOGLE_SERVICE_ACCOUNT_JSON`) → `GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON` → env инструмента с путём к файлу → `GOOGLE_OAUTH_SERVICE_ACCOUNT_FILE` |
| API-ключ `<name>` | `google-oauth:api_key` / `<name>` | env инструмента (например `GSC_PAGESPEED_API_KEY`) → `GOOGLE_OAUTH_<NAME>_API_KEY` |

Любая переменная окружения приоритетнее keychain. Недоступный keychain (headless Linux без Secret Service) при чтении — не ошибка: работают переменные окружения, `auth status` называет причину. На сервере ключи задаются окружением, например через Doppler — `doppler run -- gsc …` с `GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON` (JSON ключа целиком) и `GOOGLE_OAUTH_<NAME>_API_KEY`; ничего не записывается, `auth login` не нужен.

## Подключение к инструменту

`pyproject.toml` инструмента:

```toml
dependencies = ["rb-google-oauth>=0.2,<0.3", ...]

[tool.uv.sources]
rb-google-oauth = { git = "https://github.com/bolandeu/google-oauth.git", tag = "v0.2.0" }
```

Дистрибутив — `rb-google-oauth` (`google-oauth` на PyPI — чужой пакет), импорт — `google_oauth`. Пин — на тег релиза, обновление: новый `tag` + `uv lock --upgrade-package rb-google-oauth`. После переименования в существующем venv: `uv sync --reinstall-package rb-google-oauth`.

Профиль:

```python
from google_oauth import ApiKey, GoogleAuth, Profile

PROFILE = Profile(
    cli_name="gsc",
    service="Google Search Console",
    scopes=("https://www.googleapis.com/auth/webmasters.readonly", "https://www.googleapis.com/auth/webmasters"),
    service_account_env=("GSC_GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON"),
    service_account_file_env=("GOOGLE_SERVICE_ACCOUNT_FILE",),
    api_keys=(ApiKey("pagespeed", "PageSpeed Insights", env=("GSC_PAGESPEED_API_KEY", "GOOGLE_PAGESPEED_API_KEY")),),
)
auth = GoogleAuth(PROFILE)
```

Клиент API:

```python
bearer = auth.bearer(scopes)  # ключ читается при первом запросе
headers = bearer.headers()  # {"Authorization": "Bearer …"}, обновляется сам
psi_key = auth.api_key("pagespeed")  # или None
```

Команда: `app.add_typer(make_auth_app(auth, output), name="auth")`. `core/errors.py` инструмента импортирует `CliError`/`InvalidArguments`/`NotAuthorized` отсюда, чтобы `output.guard` ловил ошибки общего кода. Тесты инструмента подменяют `google_oauth.credentials.keyring.*` (или тот же модуль через реэкспорт).

## Проверка доступов (`auth status`, §8 стандарта tools)

`make_auth_app` выдаёт `auth status [--check] --json` в общей для всех инструментов форме: запись `google` (сервисный аккаунт, обязателен) и по записи на API-ключ (`ApiKey(required=…)`, по умолчанию необязателен). `source` — `env` / `file` / `keychain` / `missing`, `source_ref` — имя переменной, путь к файлу или слот keychain, значений нет. Под `--check` сервисный аккаунт проверяется получением access token у Google (бесплатно), затем запросом `check` инструмента; API-ключ — запросом из `api_key_checks={"pagespeed": …}`, без него `unchecked`. Код выхода 3 — обязательный ключ не в порядке или любой ключ `invalid`.

Инструмент по шаблону cli-generator делегирует `Provider.health_check()`:

```python
import google_oauth


def health_check(self) -> Health:
    return google_oauth.health_check(GOOGLE_AUTH, check=lambda: self.get_json("/sites"))
    # API-ключ: google_oauth.health_check(GOOGLE_AUTH, check, provider="pagespeed")
```

Лимит 10 с на всю проверку, без повторов; 401/403 и отказ Google → `invalid`, сеть/429/5xx/таймаут → `unreachable`; значения секретов вычищаются из `message`. `expires_at` — `None`: у ключей нет срока.

## Почему так: готовые библиотеки

По правилу «сначала готовое» сравнивались (сентябрь 2026):

| Библиотека | Решение |
|---|---|
| **`google-auth`** (Google, Apache 2.0) | **Берём.** Сервисный аккаунт с автообновлением токена, `api_key.Credentials`, токен пользователя из JSON (`from_authorized_user_info`), ADC, impersonation — вся криптография и работа с токенами |
| **`keyring`** (MIT) | **Берём.** Keychain macOS / Secret Service Linux, как в yandex-oauth |
| `google-auth-oauthlib` (Google) | Позже — для входа пользователя через браузер (`InstalledAppFlow`) |
| `google-api-python-client` (Google) | Нет: это клиенты API, а не авторизация |
| `oauth2client` (Google) | Нет: устарел с 2018, заменён google-auth |
| `pydata-google-auth` | Нет: только вход пользователя, токен в файле, без сервисных аккаунтов и keychain |
| `gcloud-aio-auth` | Нет: асинхронный, инструменты синхронные |
| `Authlib` | Нет: универсальный OAuth, для Google избыточен |

Своё здесь только то, чего нет ни в одной из них: общий слот keychain и порядок env-переменных, `Profile`, Typer-команда, статус и типизированные ошибки CLI.

ADC (`google.auth.default()`, доступы `gcloud`) намеренно не подхватывается: он молча берёт чужие доступы с машины, и можно работать не под тем аккаунтом.

## Как добавить OAuth пользователя

Вид учётных данных уже в имени записи keychain (`google-oauth:<kind>`). Для OAuth: запись `google-oauth:authorized_user` / `default` с JSON формата google-auth (`Credentials.to_json()`), вход — `google-auth-oauthlib` `InstalledAppFlow.run_local_server`, чтение — `google.oauth2.credentials.Credentials.from_authorized_user_info`, после обновления токена — перезапись JSON в keychain. `BearerToken` уже работает с любыми google-auth Credentials.

## Разработка и релизы

```bash
uv sync
uvx --from "git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git@v1.27.3#subdirectory=gate" rb-release check   # гейт: lock, ruff, ty, pytest, wheel, osv-scanner, gitleaks
```

Версия — из git-тега `vX.Y.Z`; релиз — `antagor publish` (стандарт: https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md, «Release»). Справка команд `auth` — контракт: `uv run pytest --snapshot-update` после её изменения.
