"""Flask CLI commands.

`flask --app run create-admin` creates an administrator account interactively
and safely: the password is typed hidden (with confirmation), checked against
the complexity policy, then stored HASHED (never in clear text).

Usage:
    flask --app run create-admin
    flask --app run create-admin --email admin@example.org
"""
import re

import click
from flask.cli import with_appcontext

from app import db
from app.models.user import User
from app.services.password_policy import password_errors

ADMIN_ROLE = "admin"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register_cli(app):
    """Register the CLI commands on the application."""

    @app.cli.command("create-admin")
    @click.option("--email", prompt="Admin email",
                  help="Email of the administrator account to create.")
    @click.password_option(
        help="Admin password (prompted, hidden, with confirmation).")
    @with_appcontext
    def create_admin(email, password):
        """Create an administrator account (hashed password, interactive)."""
        email = email.strip().lower()

        if not _EMAIL_RE.match(email):
            raise click.ClickException(f"Invalid email address: {email!r}")

        # Complexity policy (off-request -> English, without gettext).
        errors = password_errors(password, translate=False)
        if errors:
            raise click.ClickException(
                "Weak password:\n  - " + "\n  - ".join(errors))

        if User.query.filter_by(email=email).first():
            raise click.ClickException(
                f"A user with email {email!r} already exists.")

        username = email.split("@")[0]
        if User.query.filter_by(username=username).first():
            raise click.ClickException(
                f"Username {username!r} is already taken.")

        user = User(username=username, email=email, role=ADMIN_ROLE)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        click.secho(
            f"Administrator account created: {email} (role={ADMIN_ROLE}).",
            fg="green")
