from functools import wraps
from flask_jwt_extended import (get_jwt_identity, verify_jwt_in_request,
                                current_user)
from flask import Flask, redirect, url_for, request, jsonify
from apiflask import abort
from flask_babel import gettext as _

ADMIN_ROLE = "admin"


def inject_authentication_status():
    is_authenticated = False
    is_admin = False
    try:
        # Check whether a JWT token is present and valid
        verify_jwt_in_request(locations="cookies")
        is_authenticated = True
        # Expose the admin flag to templates (nav shows admin-only links).
        is_admin = getattr(current_user, "role", None) == ADMIN_ROLE
    except Exception:
        # If the token is invalid or missing
        is_authenticated = False
    return {'is_authenticated': is_authenticated, 'is_admin': is_admin}


def jwt_required_or_redirect():
    """
    If the user is logged in, retrieve their identity.
    Else :
      - Redirect to the login page if it's a web request.
      - Return a JSON response if it's an API request.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                verify_jwt_in_request(locations="cookies")
            except Exception as e:
                print(e)
                return redirect(url_for("auth.loginPage"))

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def verify_jwt_api():
    """JWT check for API (non-browser) endpoints (returns instead of redirecting).

    It's like jwt_required_or_redirect() for non-browser callers: accepts the
    token from an `Authorization: Bearer` header OR the cookie. Returns `None` on
    success (call continues).
    """
    try:
        verify_jwt_in_request()  # headers OR cookies (per JWT_TOKEN_LOCATION)
        return None
    except Exception:
        return jsonify({"error": "authentication required"}), 401


def admin_required():
    """Like jwt_required_or_redirect() but also requires the `admin` role.

    - Not authenticated -> redirect to the login page.
    - Authenticated but not admin -> 403 
      Admin-only links are hidden from non-admins anyway.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                verify_jwt_in_request(locations="cookies")
            except Exception as e:
                print(e)
                return redirect(url_for("auth.loginPage"))

            if getattr(current_user, "role", None) != ADMIN_ROLE:
                abort(403, message=_("Administrator privileges required."))

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def register_jwt_callbacks(jwt):
    """Record the JWT callback that binds the tokens to the User model.
    """
    @jwt.user_lookup_loader
    def _user_lookup(_jwt_header, jwt_data):
        # Late import: because when loading security.py,
        # the model and `db` are not ready yet
        from app.models.user import User
        return User.query.filter_by(username=jwt_data["sub"]).one_or_none()
