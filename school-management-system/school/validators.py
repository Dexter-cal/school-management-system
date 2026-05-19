import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class StrongSchoolPasswordValidator:
    """
    Require mixed-character passwords for manually chosen credentials.
    Generated temporary passwords already satisfy this validator.
    """

    def validate(self, password, user=None):
        value = str(password or "")
        errors = []
        if len(value) < 10:
            errors.append(_("Password must contain at least 10 characters."))
        if not re.search(r"[A-Z]", value):
            errors.append(_("Password must include at least one uppercase letter."))
        if not re.search(r"[a-z]", value):
            errors.append(_("Password must include at least one lowercase letter."))
        if not re.search(r"\d", value):
            errors.append(_("Password must include at least one number."))
        if not re.search(r"[^A-Za-z0-9]", value):
            errors.append(_("Password must include at least one symbol."))
        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Your password must be at least 10 characters long and include uppercase, lowercase, number, and symbol characters."
        )
