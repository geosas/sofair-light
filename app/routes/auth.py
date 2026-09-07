from flask import (jsonify, render_template, after_this_request,
                   url_for, redirect)
from apiflask import APIBlueprint, abort
from flask_jwt_extended import create_access_token
from flask_jwt_extended import current_user
from flask_jwt_extended import jwt_required
from flask_jwt_extended import set_access_cookies
from flask_jwt_extended import unset_jwt_cookies
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError


from app import db
from app import jwt
from app import limiter

from app.config import Config
from app.models.user import User
from app.models.invitation import Invitation
from app.schemas.authentification import (
    LoginSchema, InviteSchema, SetPasswordSchema,
    TokenOut, RegisterOut, InviteOut)
from app.services.security import admin_required
from app.services.orcid import oauth, orcid_enabled


auth_bp = APIBlueprint("auth", __name__, tag="Auth")


def _issue_jwt_cookie(user):
    """Set the session JWT cookie and return the token.
    For local login and the ORCID callback. Identity =
    username (see user_lookup_loader); 
    cookie set via @after_this_request.

    """
    access_token = create_access_token(identity=user.username)

    @after_this_request
    def _set_cookie(response):
        set_access_cookies(response, access_token)
        return response

    return access_token


@auth_bp.get("/login")
def loginPage():
    # `auth_mode` controls the display of the ORCID button ;
    # displays a server message (e.g., ORCID login without a valid invitation).
    from flask import request
    return render_template("auth/login.html",
                           auth_mode=Config.AUTH_MODE,
                           orcid_enabled=orcid_enabled(),
                           sso_error=request.args.get("sso_error"))


@auth_bp.post("/login")
@limiter.limit("10 per minute")
@auth_bp.input(LoginSchema)
@auth_bp.output(TokenOut, status_code=201)
@auth_bp.doc(summary='Login', description='Authenticate a user and return a JWT (cookie + token).')
def connexion(json_data):

    print("login attempt")
    email = json_data.email
    password = json_data.password

    user = User.query.filter_by(email=email).first()
    # Intentional generic message: do not reveal whether the email exists
    # (account enumeration prevention).
    if not user or not user.check_password(password):
        abort(401, message=_("Invalid email or password."))

    access_token = _issue_jwt_cookie(user)
    return {"access_token": access_token}


@auth_bp.get("/admin/invite")
@admin_required()
def invitePage():
    # Admin page for  generate an invitation
    return render_template("admin/invite.html")


@auth_bp.post("/admin/invitations")
@admin_required()
@auth_bp.input(InviteSchema)
@auth_bp.output(InviteOut, status_code=201)
@auth_bp.doc(summary="Create an invitation",
             description="Admin-only. Generates a single-use link (24 h) for a "
                         "new account with the given email and role.")
def create_invitation(json_data):
    email = json_data.email.lower()

    if User.query.filter_by(email=email).first():
        abort(409, message=_("An account with this email already exists."),
              detail={"json": {"email": [_("This email is already registered.")]}})

    if json_data.auth_provider == "orcid" and \
            User.query.filter_by(orcid_id=json_data.orcid_id).first():
        abort(409, message=_("An account with this ORCID iD already exists."),
              detail={"json": {"orcid_id": [_("This ORCID iD is already registered.")]}})

    invited_by = getattr(current_user, "username", None)
    invite, raw_token = Invitation.create(
        email=email, role=json_data.role, invited_by=invited_by,
        auth_provider=json_data.auth_provider, orcid_id=json_data.orcid_id)
    db.session.add(invite)
    db.session.commit()

    if json_data.auth_provider == "orcid":
        # No set-password link: the invitee signs in with ORCID and is matched
        # on the pre-registered orcid_id (strong binding).
        return {
            "msg": _("ORCID invitation created. The user can now sign in with ORCID."),
            "email": email,
            "role": json_data.role,
            "auth_provider": "orcid",
            "invite_url": None,
            "orcid_id": json_data.orcid_id,
            "expires_at": invite.expires_at.isoformat() + "Z",
        }

    invite_url = url_for("auth.set_password_page",
                         token=raw_token, _external=True)
    return {
        "msg": _("Invitation created."),
        "email": email,
        "role": json_data.role,
        "auth_provider": "local",
        "invite_url": invite_url,
        "orcid_id": None,
        "expires_at": invite.expires_at.isoformat() + "Z",
    }


@auth_bp.get("/set-password/<token>")
def set_password_page(token):
    # User page for  generate a password
    invite = Invitation.find_valid(token)
    if invite is None:
        return render_template("auth/set_password.html",
                               valid=False, token=token, email=None), 410
    return render_template("auth/set_password.html",
                           valid=True, token=token, email=invite.email)


@auth_bp.post("/set-password/<token>")
@auth_bp.input(SetPasswordSchema)
@auth_bp.output(RegisterOut, status_code=201)
@auth_bp.doc(summary="Set password from an invitation",
             description="Public but token-gated. Consumes a single-use "
                         "invitation and creates the account.")
def set_password(token, json_data):
    invite = Invitation.find_valid(token)
    if invite is None:
        abort(410, message=_(
            "This invitation link is invalid, already used or expired."))

    # in case user already in db (if he use the same token twice)
    if User.query.filter_by(email=invite.email).first():
        invite.mark_used()
        db.session.commit()
        abort(409, message=_("An account with this email already exists."))

    username = invite.email.split("@")[0]
    if User.query.filter_by(username=username).first():
        abort(409, message=_("Username is already taken."),
              detail={"json": {"username": [_("This username is already taken.")]}})

    try:
        new_user = User(username=username,
                        email=invite.email, role=invite.role)
        new_user.set_password(json_data.password)
        db.session.add(new_user)
        invite.mark_used()
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, message=_("Registration failed"),
              detail={"json": {"unknown": [_("A database error occurred.")]}})
    except Exception as e:
        db.session.rollback()
        abort(500, message=_("An unexpected error occurred"),
              detail={"json": {"unknown": [str(e)]}})

    return {
        "msg": _("Password set successfully. You can now log in."),
        "user": {
            "username": new_user.username,
            "email": new_user.email,
            "role": new_user.role,
        },
    }


@auth_bp.get("/orcid/login")
@auth_bp.doc(hide=True)
def orcid_login():
    """OAuth2 ORCID : redirect to ORCID auth page.
    The callback need to be exactly  the redirect_uri from ORCID.
    more information https://orcid.org/developer-tools
    """
    if Config.AUTH_MODE not in ("orcid", "both") or not orcid_enabled():
        abort(404)
    redirect_uri = url_for("auth.orcid_callback", _external=True)
    return oauth.orcid.authorize_redirect(redirect_uri)


@auth_bp.get("/orcid/callback")
@auth_bp.doc(hide=True)
def orcid_callback():
    """ORCID callback  : verifies identity, generate the JWT.
    Invite-only model 
    The role ALWAYS comes from the local invitation: ORCID give no permissions.
    """
    if Config.AUTH_MODE not in ("orcid", "both") or not orcid_enabled():
        abort(404)

    try:
        token = oauth.orcid.authorize_access_token()
    except Exception as e:
        print("ORCID callback error:", e)
        return redirect(url_for("auth.loginPage",
                                sso_error=_("ORCID sign-in failed.")))

    userinfo = token.get("userinfo") or {}
    if not userinfo:
        try:
            userinfo = oauth.orcid.userinfo(token=token)
        except Exception:
            userinfo = {}
    orcid_id = userinfo.get("sub")
    if not orcid_id:
        return redirect(url_for("auth.loginPage",
                                sso_error=_("ORCID did not return an identifier.")))

    user = User.query.filter_by(orcid_id=orcid_id).first()
    if user is None:
        invite = Invitation.find_valid_orcid(orcid_id)
        if invite is None:
            # No matching invitation -> no account (invite-only model preserved).
            return redirect(url_for(
                "auth.loginPage",
                sso_error=_("No valid ORCID invitation for this account. "
                            "Ask an administrator to invite you.")))

        username = invite.email.split("@")[0]
        if User.query.filter_by(username=username).first():
            return redirect(url_for("auth.loginPage",
                                    sso_error=_("Username is already taken.")))
        try:
            user = User(username=username, email=invite.email,
                        role=invite.role, auth_provider="orcid",
                        orcid_id=orcid_id)
            db.session.add(user)
            invite.mark_used()
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return redirect(url_for("auth.loginPage",
                                    sso_error=_("Registration failed.")))

    # because of the strict policy, redirect don't work
    _issue_jwt_cookie(user)

    return render_template("auth/orcid_success.html",
                           next_url=url_for("public.home"))


@auth_bp.get("/who_am_i")
@jwt_required()
# @jwt_required(locations=["headers"])
def protected():
    """For test"""
    return jsonify(
        id=current_user.id,
        username=current_user.username,
    )


@auth_bp.get("/logout_wc")
def logout_wc():
    response = jsonify({"msg": "logout successful"})
    unset_jwt_cookies(response)
    return response
