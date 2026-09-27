# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
Между релизами этот файл не правят: изменения — фрагментами в `changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "…"`), `scripts/release.py` собирает их сюда.

<!-- towncrier release notes start -->

## [0.1.0] - 2026-09-27

### Added

- Общая авторизация Google для CLI-инструментов: `Profile`, `GoogleAuth` (ключ сервисного аккаунта и API-ключи из env инструмента → общих `GOOGLE_OAUTH_…` → общего слота keychain `google-oauth:*`, access token с автообновлением через `google-auth`), `CredentialStore`, типизированные ошибки CLI и готовая Typer-команда `auth login|logout|status [--check]` (`make_auth_app`).
