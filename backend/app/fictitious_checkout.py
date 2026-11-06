"""Explicit opt-in for synthetic commercial documents; never a production offer."""
from fastapi import HTTPException


def enabled(settings):
    from app.stripe_checkout import enabled as stripe_enabled
    return (
        settings.auth_environment == "development"
        and settings.stripe_fictitious_enabled
        and stripe_enabled(settings)
    )


def require_scope(document, settings=None):
    if not document.get("stripe_test_only", False):
        return
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    if not enabled(settings):
        raise HTTPException(503, "fictitious_stripe_test_configuration_forbidden")


def require_snapshot(snapshot, settings):
    require_scope(snapshot, settings)
    require_scope(snapshot.get("checkout", {}), settings)
