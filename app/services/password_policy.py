from flask_babel import gettext

# Minimum length (same for admin/users).
PASSWORD_MIN_LENGTH = 8

# Set of accepted special characters
SPECIAL_CHARS = "!@#$%^&*(),.?\":{}|<>"


def _plain(message, **variables):
    """gettext replacement without translation for flask CLI
    when admin create an account.
    """
    return message % variables if variables else message


def password_errors(password, min_length=PASSWORD_MIN_LENGTH, translate=True):
    """Return the list of error messages for a too-weak password.
    """
    _ = gettext if translate else _plain
    errors = []
    if len(password) < min_length:
        errors.append(
            _("Password must be at least %(n)d characters long.", n=min_length))
    if not any(c.isupper() for c in password):
        errors.append(
            _("Password must contain at least one uppercase letter."))
    if not any(c.islower() for c in password):
        errors.append(
            _("Password must contain at least one lowercase letter."))
    if not any(c.isdigit() for c in password):
        errors.append(_("Password must contain at least one digit."))
    if not any(c in SPECIAL_CHARS for c in password):
        errors.append(
            _("Password must contain at least one special character."))
    return errors
