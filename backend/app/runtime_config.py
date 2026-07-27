from __future__ import annotations

from collections.abc import Iterable

from .models import AgentAssignmentsConfig, ProviderProfile
from .provider_catalog import CATALOG_FIELDS, builtin_providers


LEGACY_UNVERIFIED_MODELS = frozenset(
    {
        "gpt-5.6-sol",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "glm-5.2",
        "glm-5.1",
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.6",
    }
)


def restore_provider_profiles(saved_profiles: Iterable[ProviderProfile]) -> dict[str, ProviderProfile]:
    profiles = builtin_providers()
    for saved in saved_profiles:
        if saved.id == "mock":
            continue
        catalog = profiles.get(saved.id)
        if catalog:
            for field in CATALOG_FIELDS:
                setattr(saved, field, getattr(catalog, field))
            saved.api_key_reference = saved.api_key_reference or catalog.api_key_reference
            saved.requires_api_key = catalog.requires_api_key
            if not saved.available_models:
                saved.available_models = catalog.available_models
                saved.model_source = catalog.model_source
            elif saved.model_source == "none":
                saved.model_source = "saved"
            if saved.default_model in LEGACY_UNVERIFIED_MODELS and saved.model_source != "provider":
                saved.default_model = catalog.default_model
                saved.available_models = catalog.available_models
                saved.model_source = catalog.model_source
        profiles[saved.id] = saved
    return profiles


def assignment_config_is_valid(config: AgentAssignmentsConfig | None, profiles: dict[str, ProviderProfile]) -> bool:
    return config is not None and all(
        assignment.provider_id in profiles
        and assignment.model.strip()
        and assignment.model not in LEGACY_UNVERIFIED_MODELS
        for assignment in [*config.seats, config.finalizer]
    )
