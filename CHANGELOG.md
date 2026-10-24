# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## v0.2.1 — 2026-10-24

### Main

- chore(antagor): publish config (semver, remote gate, deploy by push)
- daemon: enabled
- mode: fast
- antagor init: project google-oauth (GOAUTH)
- chore: drop the core.hooksPath hook and fragment notes
- fix(deps): certifi 2026.10.19 (PYSEC-2026-4320)
- docs: AGENTS.md; ci: Gitea workflow runs the gate (template v1.27.3)
- build: [tool.rb.install] for a library, coverage core ctrace, drop towncrier
- chore: remove the old release tooling (release.py, githooks, towncrier fragments, GitHub CI)
- test: help snapshots render the same under CI env (GITHUB_ACTIONS, FORCE_COLOR, PY_COLORS)
- chore: пути ~/Projects → ~/Work после переезда
- chore(hooks): скрипты tools ищутся относительно репозитория (перенос tools не ломает хуки)
- chore(claude): при старте сессии агент берёт имя в herdr по команде
- chore(hooks): pre-push сообщает корневому агенту tools о пушнутых тегах
- docs: инструмент в системе (стандарт §13)
- docs: каждое заметное изменение выходит релизом


## [0.2.0] - 2026-09-27

### Added

- `google_oauth.health_check(auth, check=None, provider=None)` → `Health` — делегат для `Provider.health_check()` инструментов: токен сервисного аккаунта у Google + дешёвый запрос инструмента, жёсткий лимит 10 с, 401/403 и отказ Google → `invalid`, сеть/429/5xx/таймаут → `unreachable`, значения секретов вычищаются из сообщений. Также `credential_status`, `status_report`, `status_problems`, `status_exit_code`, ошибка `CredentialsUnhealthy`, `ApiKey.required` и `make_auth_app(..., api_key_checks=…)` — проверка API-ключей под `auth status --check`. Без keychain (Linux-сервер, `doppler run`) всё работает от переменных окружения (`GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON`, `GOOGLE_OAUTH_<NAME>_API_KEY`), а `auth status` называет причину недоступности keychain.

### Changed

- **Ломающее.** Дистрибутив переименован: `google-oauth` → `rb-google-oauth` (стандарт tools §10: `google-oauth` на PyPI — чужой пакет); импорт `google_oauth` не меняется. Потребителям: новое имя в `dependencies` и ключ `[tool.uv.sources]` с пином на тег (`rb-google-oauth = { git = …, tag = "v0.2.0" }`), в существующем venv — `uv sync --reinstall-package rb-google-oauth`. **Ломающее:** `auth status [--check] --json` из `make_auth_app` выдаёт отчёт §8 (`tool`, `version`, `checked_at`, `credentials[]` — сервисный аккаунт и API-ключи) в стандартном конверте вместо плоского `{google, <key>_key, account, source, detail}`; при проблеме — exit 3, `ok: false` и `error` `CREDENTIALS_UNHEALTHY`. Стандарт релизов tools: версия из git-тега, changelog из фрагментов, `scripts/release.py` из шаблона cli-generator v1.2.7, контракт справки команд `auth` (§7).


## [0.1.0] - 2026-09-27

### Added

- Общая авторизация Google для CLI-инструментов: `Profile`, `GoogleAuth` (ключ сервисного аккаунта и API-ключи из env инструмента → общих `GOOGLE_OAUTH_…` → общего слота keychain `google-oauth:*`, access token с автообновлением через `google-auth`), `CredentialStore`, типизированные ошибки CLI и готовая Typer-команда `auth login|logout|status [--check]` (`make_auth_app`).
