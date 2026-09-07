"""Archive bulk-export routes (authenticated).

Two downloads of the raw/qualified archive:
- GET /private/export/observations.parquet -> all observations as Parquet.
- GET /private/export/relations.duckdb      -> the relation tables as a DuckDB file.

Parquet and DuckDB files can't be streamed on the fly, so each file is
materialised into a per-request temp dir, streamed from disk (constant memory),
and the temp dir is removed once the response is fully sent (call_on_close).
"""
import os
import shutil
import tempfile

from flask import send_file

from app.services.security import jwt_required_or_redirect
from app.sta_tools import archive_export

from app.routes.private import private_bp


def _stream_temp_file(build, filename, mimetype):
    """Run ``build(path)`` into a fresh temp dir, then stream the file and clean
    up the dir when the response closes. Any build error removes the dir first."""
    workdir = tempfile.mkdtemp(prefix="stalt_export_")
    path = os.path.join(workdir, filename)
    try:
        build(path)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    resp = send_file(path, mimetype=mimetype, as_attachment=True,
                     download_name=filename)
    resp.call_on_close(lambda: shutil.rmtree(workdir, ignore_errors=True))
    return resp


@private_bp.get("/export/observations.parquet")
@jwt_required_or_redirect()
def export_observations():
    return _stream_temp_file(
        archive_export.export_observations_parquet,
        "observations.parquet",
        "application/vnd.apache.parquet")


@private_bp.get("/export/relations.duckdb")
@jwt_required_or_redirect()
def export_relations():
    return _stream_temp_file(
        archive_export.export_relations_duckdb,
        "relations.duckdb",
        "application/octet-stream")
