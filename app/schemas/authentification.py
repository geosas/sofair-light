import re

from pydantic import (BaseModel, Field, field_validator, model_validator,
                      EmailStr)
from typing import Literal, Optional

from flask_babel import gettext as _

from app.services.password_policy import password_errors, PASSWORD_MIN_LENGTH


ASSIGNABLE_ROLES = Literal["metrologue",
                           "thematicien", "data engineer", "test"]

# ORCID iD: 16 digits grouped in sets of 4 separated by dashes, where the last
# character can be an X (checksum). Example: 0000-0002-1825-0097
# https://support.orcid.org/hc/en-us/articles/360053289173-Why-does-my-ORCID-iD-have-an-X
ORCID_ID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class InviteSchema(BaseModel):
    """Admin-created invitation: target email + role + auth method.

    For `auth_provider='orcid'` the admin MUST supply the invitee's `orcid_id`:
    only that ORCID login can activate the

    """
    email: EmailStr = Field(..., examples=["jane@example.com"])
    role: ASSIGNABLE_ROLES = Field(
        default="metrologue",
        examples=["metrologue", "thematicien", "data engineer"])
    auth_provider: Literal["local", "orcid"] = Field(
        default="local", examples=["local", "orcid"])
    orcid_id: Optional[str] = Field(
        default=None, examples=["0000-0002-1825-0097"])

    @model_validator(mode="after")
    def _check_orcid(self):
        if self.auth_provider == "orcid":
            if not self.orcid_id:
                raise ValueError(
                    _("An ORCID iD is required for an ORCID invitation."))
            if not ORCID_ID_RE.match(self.orcid_id):
                raise ValueError(
                    _("Invalid ORCID iD (expected 0000-0000-0000-0000)."))
        else:
            # Ignore any ORCID iD passed on a local invitation.
            self.orcid_id = None
        return self


class SetPasswordSchema(BaseModel):
    """User setting their own password from an invitation link."""
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH,
                          examples=["Password123!"])

    @field_validator("password")
    def validate_password(cls, v: str) -> str:
        """Validate password (min lenght, upper case, special characteres)"""
        errors = password_errors(v)
        if errors:
            raise ValueError(errors[0])
        return v


class LoginSchema(BaseModel):
    # json_schema_extra adds `example` (SINGULAR): that's what Swagger UI reads
    # in OpenAPI 3.0 for the "Example Value" tab (the plural `examples` is not rendered there).
    password: str = Field(
        ...,
        min_length=8,
        examples=["Password123!"],
        # json_schema_extra={"example": "Password123!"},
    )

    email: EmailStr = Field(
        ...,
        examples=["john@example.com"],
        # json_schema_extra={"example": "john@example.com"},
    )


class TokenOut(BaseModel):
    """Successful login response."""
    access_token: str


class UserOut(BaseModel):
    username: str
    email: str
    role: str


class RegisterOut(BaseModel):
    """Successful registration response"""
    msg: str
    user: UserOut


class InviteOut(BaseModel):
    """Invitation created
    """
    msg: str
    email: str
    role: str
    auth_provider: str
    invite_url: Optional[str] = None
    orcid_id: Optional[str] = None
    expires_at: str
