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


def validate_phone_number(value):
    raw = str(value or '').strip().replace(' ', '').replace('-', '')
    if not raw:
        return True
    # Match Ugandan/East African formats: 07xxxxxxxx, 03xxxxxxxx, +2567xxxxxxxx, +2563xxxxxxxx, 2567xxxxxxxx, or 10-13 digits
    if re.match(r'^(?:\+?256|0)[379]\d{8}$', raw) or (raw.isdigit() and 9 <= len(raw) <= 15):
        return True
    raise ValidationError(_('Enter a valid phone number (e.g., 0701234567 or +256701234567).'))
