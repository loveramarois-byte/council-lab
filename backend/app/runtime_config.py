from __future__ import annotations

from collections.abc import Iterable

from .models import AgentAssignmentsConfig, ProviderProfile, ProviderType
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


def model_is_verified(profile: ProviderProfile, model: str) -> bool:
    if model not in LEGACY_UNVERIFIED_MODELS:
        return True
    if model not in profile.available_models:
        return False
    return profile.model_source == "provider" or (
        profile.provider_type == ProviderType.CCSWITCH and profile.model_source == "ccswitch_history"
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
            if not model_is_verified(saved, saved.default_model):
                saved.default_model = catalog.default_model
                saved.available_models = catalog.available_models
                saved.model_source = catalog.model_source
        profiles[saved.id] = saved
    return profiles


def select_active_profile(profiles: dict[str, ProviderProfile]) -> ProviderProfile:
    active = next((profile for profile in profiles.values() if profile.is_active and profile.default_model), None)
    if active is not None:
        return active

    had_active_profile = any(profile.is_active for profile in profiles.values())
    preferred_ids = ("mock", "ccswitch") if had_active_profile else ("ccswitch", "mock")
    fallback = next(
        (
            profiles[provider_id]
            for provider_id in preferred_ids
            if provider_id in profiles and profiles[provider_id].default_model
        ),
        None,
    )
    if fallback is None:
        fallback = next((profile for profile in profiles.values() if profile.default_model), None)
    if fallback is None:
        raise RuntimeError("No provider with a configured default model is available")

    for profile in profiles.values():
        profile.is_active = profile is fallback
    return fallback


def assignment_config_is_valid(config: AgentAssignmentsConfig | None, profiles: dict[str, ProviderProfile]) -> bool:
    if config is None:
        return False
    return all(
        bool(assignment.model.strip())
        and assignment.provider_id in profiles
        and model_is_verified(profiles[assignment.provider_id], assignment.model)
        for assignment in [*config.seats, config.finalizer]
    )
