from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiKey:
    """API-ключ Google, который нужен инструменту (PageSpeed Insights, …).

    name  — имя ключа: запись keychain `google-oauth:api_key` / `<name>`,
            значение `--provider <name>` в `auth login`, поле `<name>_key` в статусе.
    title — название API для текстов («PageSpeed Insights»).
    env   — «исторические» переменные окружения инструмента с этим ключом,
            по порядку; они приоритетнее общей `GOOGLE_OAUTH_<NAME>_API_KEY`.
    hint  — где взять ключ (для `auth login --help`).
    required — без ключа инструмент не работает: в `auth status` его отсутствие —
            код выхода 3 (иначе — только запись `missing`, §8 стандарта tools).
    """

    name: str
    title: str
    env: tuple[str, ...] = ()
    hint: str = ""
    required: bool = False


@dataclass(frozen=True)
class Profile:
    """Чем инструмент отличается в общей схеме авторизации Google.

    cli_name — имя команды (тексты подсказок, `<cli> auth login`).
    service  — название сервиса для текстов («Google Search Console»).
    scopes   — права сервисного аккаунта по умолчанию (первый — для запросов
               без явных scopes).
    service_account_env / service_account_file_env — «исторические» переменные
               инструмента с JSON ключа / путём к файлу ключа; приоритетнее общих
               `GOOGLE_OAUTH_SERVICE_ACCOUNT_JSON` / `_FILE`.
    api_keys — какие API-ключи нужны инструменту.
    login_hint — что сделать после входа (например, выдать email сервисного
               аккаунта доступ в Search Console).
    keychain_namespace — общий для всех инструментов: записи keychain
               `google-oauth:<kind>`, общие переменные `GOOGLE_OAUTH_…`.
               Один вход — все инструменты.
    provider — имя сервисного аккаунта в `--provider` и в JSON статуса.
    """

    cli_name: str
    service: str
    scopes: tuple[str, ...]
    service_account_env: tuple[str, ...] = ()
    service_account_file_env: tuple[str, ...] = ()
    api_keys: tuple[ApiKey, ...] = ()
    login_hint: str = ""
    keychain_namespace: str = "google-oauth"
    provider: str = "google"

    @property
    def login_cmd(self) -> str:
        return f"{self.cli_name} auth login --file <service-account.json>"

    def api_key_login_cmd(self, name: str) -> str:
        return f"{self.cli_name} auth login --provider {name}"

    def api_key(self, name: str) -> ApiKey:
        for key in self.api_keys:
            if key.name == name:
                return key
        raise KeyError(f"API-ключ '{name}' не объявлен в профиле {self.cli_name}")

    @property
    def providers(self) -> list[str]:
        """Допустимые значения `--provider`: сервисный аккаунт и API-ключи."""
        return [self.provider, *(key.name for key in self.api_keys)]
