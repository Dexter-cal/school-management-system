from __future__ import annotations

from django.conf import settings

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp


class APICredentialSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Allows the super admin to manage Google OAuth credentials in APICredential without
    querying the database from settings.py at import time.
    """

    def get_app(self, request, provider, client_id=None):
        if getattr(provider, "id", None) != "google":
            return super().get_app(request, provider, client_id=client_id)

        cred = None
        try:
            from .models import APICredential  # Import locally to avoid app-loading cycles.

            cred = (
                APICredential.objects.filter(service_name="google_oauth", is_active=True)
                .order_by("-updated_at")
                .first()
            )
        except Exception:
            cred = None

        client_id_val = (cred.client_id if cred and cred.client_id else None) or settings.SOCIALACCOUNT_PROVIDERS.get(
            "google", {}
        ).get("APP", {}).get("client_id")
        secret_val = (cred.client_secret if cred and cred.client_secret else None) or settings.SOCIALACCOUNT_PROVIDERS.get(
            "google", {}
        ).get("APP", {}).get("secret")

        # Build an in-memory SocialApp. allauth accepts this from the adapter.
        app = SocialApp(provider="google", name="Google OAuth (APICredential)")
        app.client_id = client_id_val or ""
        app.secret = secret_val or ""
        app.key = ""
        return app

