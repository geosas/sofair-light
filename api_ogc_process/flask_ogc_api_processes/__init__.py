"""
flask_ogc_api_processes - a reusable OGC API - Processes (Part 1: Core) engine.

Public API::

    from flask_ogc_api_processes import create_ogc_blueprint          # embed in any Flask app
    from flask_ogc_api_processes import create_app                     # standalone app
    from flask_ogc_api_processes import DefaultConfig, JobStore, SQLiteJobStore

Importing this package has **no side effects**: no app is created, no database is
opened, no config is read. Everything happens when you call the factory.
"""
from .config import DefaultConfig, resolve_config, build_service_info
from .job_store import JobStore, SQLiteJobStore
from .routes.ogc_process_routes import create_ogc_blueprint
from .standalone import create_app

__all__ = [
    "create_ogc_blueprint",
    "create_app",
    "DefaultConfig",
    "resolve_config",
    "build_service_info",
    "JobStore",
    "SQLiteJobStore",
]
