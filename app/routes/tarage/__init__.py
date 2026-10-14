"""Gauging tools (/tarage): salt-dilution discharge, gauging list + rating curve."""
from flask import Blueprint

tarage_bp = Blueprint('tarage', __name__)

# create blueprint and after import
from app.routes.tarage import (  # noqa: E402,F401
    dilution,
    gauging_list,
)
