from __future__ import annotations

from .profile import Profile


class CliError(Exception):
    """Базовая ошибка для всех ожидаемых, показываемых пользователю сбоев CLI.

    Единая для всех инструментов, использующих google-oauth: их `output.guard`
    ловит именно этот класс, поэтому ошибки общего кода (ключи, keychain,
    получение токена) выводятся так же, как собственные ошибки инструмента.

    Каждая несёт стабильный `code`, человекочитаемое `message`, необязательное
    `action` (что сделать, чтобы разблокироваться) и код выхода процесса.
    """

    def __init__(self, code: str, message: str, *, action: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.action:
            payload["action"] = self.action
        return payload


class InvalidArguments(CliError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, exit_code=2)


class NotAuthorized(CliError):
    """Нет учётных данных, они битые или Google их отверг. `action` — команда, которая это исправит."""

    def __init__(self, provider: str, reason: str, *, action: str) -> None:
        super().__init__("AUTH_REQUIRED", reason, action=action, exit_code=3)
        self.provider = provider


class TokenRequestFailed(CliError):
    """Не удалось получить access token из-за сети/сервера Google (ключ при этом может быть исправен)."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(
            "PROVIDER_ERROR",
            f"Provider '{provider}': {message}",
            action="Повторите позже; если не проходит — проверьте сеть и status.cloud.google.com.",
            exit_code=5,
        )
        self.provider = provider

    def to_dict(self) -> dict:
        return {**super().to_dict(), "provider": self.provider}


class CredentialStoreUnavailable(CliError):
    def __init__(self, profile: Profile, reason: str) -> None:
        super().__init__(
            "CREDENTIAL_STORE_UNAVAILABLE",
            f"Не удалось обратиться к системному хранилищу ключей: {reason}",
            action=f"Задайте ключ переменной окружения вместо 'auth login' (см. '{profile.cli_name} auth login --help').",
            exit_code=1,
        )


class CredentialsUnhealthy(CliError):
    """`auth status` нашёл проблему (§8 стандарта tools): отчёт выводится целиком, рядом — эта ошибка, exit 3."""

    def __init__(self, profile: Profile, problems: dict[str, str]) -> None:
        listed = ", ".join(f"{provider} ({status})" for provider, status in problems.items())
        super().__init__(
            "CREDENTIALS_UNHEALTHY",
            f"Учётные данные требуют внимания: {listed}.",
            action=f"Подробности — в `message` каждой записи; войти заново: '{profile.login_cmd}'.",
            exit_code=3,
        )
