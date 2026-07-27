from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError

from .models import ProviderProfile


SERVICE_NAME = "Council Lab Provider Credentials"


class CredentialStoreError(RuntimeError):
    pass


def get_provider_secret(profile: ProviderProfile) -> str:
    if profile.api_key_reference:
        environment_value = os.getenv(profile.api_key_reference, "").strip()
        if environment_value:
            return environment_value
    if not profile.credential_saved:
        return ""
    try:
        return keyring.get_password(SERVICE_NAME, profile.id) or ""
    except KeyringError as exc:
        raise CredentialStoreError("无法读取系统凭据库，请检查 Keychain 或系统密钥服务。") from exc


def save_provider_secret(provider_id: str, secret: str) -> None:
    value = secret.strip()
    if not value:
        raise CredentialStoreError("API Key 不能为空。")
    try:
        keyring.set_password(SERVICE_NAME, provider_id, value)
    except KeyringError as exc:
        raise CredentialStoreError("无法写入系统凭据库，请检查 Keychain 或系统密钥服务。") from exc


def delete_provider_secret(provider_id: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, provider_id)
    except keyring.errors.PasswordDeleteError:
        return
    except KeyringError as exc:
        raise CredentialStoreError("无法从系统凭据库删除 API Key。") from exc
