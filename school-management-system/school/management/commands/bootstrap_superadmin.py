from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Create/ensure a default super admin user (dev bootstrap)."

    def handle(self, *args, **options):
        enabled = config("BOOTSTRAP_SUPERADMIN", default=False, cast=bool)
        if not enabled:
            self.stdout.write("bootstrap_superadmin: disabled (set BOOTSTRAP_SUPERADMIN=True to enable).")
            return

        username = str(config("BOOTSTRAP_SUPERADMIN_USERNAME", default="admin"))
        password = str(config("BOOTSTRAP_SUPERADMIN_PASSWORD", default=""))
        email = str(config("BOOTSTRAP_SUPERADMIN_EMAIL", default=""))

        if not password:
            self.stderr.write("bootstrap_superadmin: missing BOOTSTRAP_SUPERADMIN_PASSWORD.")
            return

        User = get_user_model()
        with transaction.atomic():
            user, created = User.objects.get_or_create(username=username, defaults={"email": email})
            # Always enforce superuser/staff flags for the bootstrap account.
            user.is_staff = True
            user.is_superuser = True
            if email:
                user.email = email
            user.set_password(password)
            user.save()

            # Create/ensure profile role alignment.
            try:
                from school.models import UserProfile, SecurityAuditLog

                UserProfile.objects.update_or_create(
                    user=user,
                    defaults={"role": "superadmin", "avatar": (user.first_name[:2] if user.first_name else "SA")},
                )
                SecurityAuditLog.objects.create(
                    user=user,
                    event_type="SUPERADMIN_BOOTSTRAPPED",
                    ip_address=None,
                    details=f"Bootstrap super admin ensured for username={username} (created={created}).",
                )
            except Exception:
                # Profile/audit are best-effort; user is still created.
                pass

        self.stdout.write(f"bootstrap_superadmin: ensured super admin '{username}' (created={created}).")

