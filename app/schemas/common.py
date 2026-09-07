"""SHARED Pydantic schemas for APIFlask doc/validation.

Convention: one module per domain in app/schemas/
    - authentification.py : /auth (Login/Invite/SetPassword + Token/Register/Invite outputs)
    - common.py           : reusable (this file)
    - sensors.py          : /sensors
    - metadata.py         : /  (catalog, service metadata)
    - ...
Schemas specific to ONE route may stay defined in the route file.
"""
from pydantic import BaseModel


class FieldError(BaseModel):
    field: str
    message: str


class ErrorOut(BaseModel):
    """Unified error shape of the app (produced by the error_processor).

    Reference in the error doc if needed, e.g.:
        @bp.doc(responses={422: 'Validation', 409: 'Conflict'})
    """
    msg: str
    errors: list[FieldError] = []


class MessageOut(BaseModel):
    """Simple response { "msg": "..." } (e.g. logout, acknowledgements)."""
    msg: str
