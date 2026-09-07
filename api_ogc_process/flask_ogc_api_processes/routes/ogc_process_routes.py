"""
Blueprint factory for OGC API - Processes (Part 1: Core).

``create_ogc_blueprint`` builds a self-contained Flask blueprint that can be
registered in *any* Flask application. Everything it needs is injected:

- ``processes`` : the process registry (list or dict of process classes),
- ``config``    : engine settings (base URL, thread count, ...), with defaults,
- ``job_store`` : pluggable job persistence (default: autonomous SQLite).

There is **no module-level state** and **no import side effect**: importing this
module does not create an app, an executor, a database, or read any global config.
"""
import logging
import multiprocessing as mp
import re
import threading
import uuid

from flask import Blueprint, request, jsonify, render_template, Response
from pydantic import ValidationError

from ..config import resolve_config, build_service_info
from ..job_store import SQLiteJobStore
from ..utils.input_resolver import resolve_inputs, InputResolutionError
from ..utils.output_handler import (
    filter_outputs,
    format_response,
    validate_response_parameter,
    validate_outputs_parameter,
)
from .openapi_routes import generate_openapi_spec

logger = logging.getLogger(__name__)

# Server-generated job IDs are UUID4; validate the URL segment before it is used
# to touch the job store / result files (SECURITY_AUDIT.md #10, defence in depth).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _is_valid_job_id(job_id: str) -> bool:
    return bool(_UUID_RE.match(job_id or ""))


def _build_registry(processes) -> dict:
    """Normalize an injected registry (list or dict of classes) to ``{id: class}``."""
    classes = processes.values() if isinstance(processes, dict) else processes
    registry = {}
    for cls in classes:
        registry[cls.get_metadata()["id"]] = cls
    return registry


# Async jobs run as separate OS processes so DELETE can kill them (real PID).
# We use the ``forkserver`` start method: children are forked from a clean,
# single-threaded server process, which avoids the deadlocks that plain ``fork``
# can cause when spawning from a multi-threaded web server (a child inheriting a
# lock held by another thread). It requires the worker + its args to be picklable
# - which is why ``_run_and_persist`` is module-level and ``SQLiteJobStore`` is
# picklable. Falls back to the platform default where forkserver is unavailable.
try:
    _MP_CTX = mp.get_context("forkserver")
except ValueError:  # pragma: no cover - non-forkserver platforms (e.g. Windows)
    _MP_CTX = mp.get_context()


def _run_and_persist(process_class, data, job_id, job_store):
    """Validate + run a process and persist its status/results.

    Defined at **module level** (no closure, no un-picklable capture) so it can be
    the ``target`` of a ``multiprocessing.Process`` - which is what makes async jobs
    run in their own killable OS process. Returns ``(result, code)`` (the return
    value is ignored when this runs inside a child process).
    """
    job_store.update_job(job_id, progress=0, status="running")
    try:
        validated_data = process_class.Schema.model_validate(data)
        result, code = process_class.run(validated_data)
        # Honour a dismissal that landed while the process was running: do not
        # overwrite a "dismissed" job back to "successful".
        current = job_store.get_job(job_id)
        if current is not None and current["status"] == "dismissed":
            return result, code
        job_store.save_results(job_id, result)
        job_store.update_job(job_id, progress=100, status="successful")
        return result, code
    except ValidationError as e:
        errors = [{"field": err["loc"][0], "message": err["msg"]} for err in e.errors()]
        job_store.update_job(job_id, progress=100, status="failed", message="Validation failed")
        return {"msg": "Validation failed", "errors": errors}, 422
    except Exception:  # noqa: BLE001 - report as OGC failure
        # Do NOT leak the exception text to the client (SECURITY_AUDIT.md #7):
        # log the details server-side, return a generic message.
        logger.exception("Process '%s' (job %s) raised an unexpected error",
                         getattr(process_class, "__name__", process_class), job_id)
        job_store.update_job(job_id, progress=100, status="failed",
                             message="Internal processing error")
        return {"error": "Internal processing error"}, 500


def _prefers_json(default: bool) -> bool:
    """Content negotiation: does the client want JSON (vs the HTML representation)?

    Follows the OGC/HTTP convention (standard §7.3.2): the ``f`` query parameter
    **overrides** the ``Accept`` header. ``f=json``/``f=application/json`` -> JSON,
    ``f=html``/``f=text/html`` -> HTML. Without ``f``, the ``Accept`` header decides;
    ``default`` breaks ties (``*/*``) and the no-Accept case.
    """
    f = (request.args.get("f") or "").lower()
    if f in ("json", "application/json"):
        return True
    if f in ("html", "text/html"):
        return False
    accept = request.accept_mimetypes
    if not accept:
        return default
    json_q, html_q = accept["application/json"], accept["text/html"]
    if json_q == html_q:
        return default
    return json_q > html_q


def create_ogc_blueprint(processes, *, config=None, job_store=None, url_prefix="/"):
    """Create an OGC API - Processes blueprint.

    Args:
        processes: Injected process registry (list or dict of process classes).
        config: Engine config object/dict (defaults applied via ``resolve_config``).
        job_store: A :class:`~flask_ogc_api_processes.job_store.JobStore`. Defaults to an
            autonomous :class:`~flask_ogc_api_processes.job_store.SQLiteJobStore`.
        url_prefix: Advisory default prefix (the host decides at registration).

    Returns:
        A Flask ``Blueprint`` exposing the OGC API - Processes endpoints.
    """
    config = resolve_config(config)
    if job_store is None:
        job_store = SQLiteJobStore()

    # Crash recovery: a previous run may have died leaving jobs in a non-terminal
    # state. Their OS processes are gone (the in-memory registry did not survive),
    # so they can never complete - mark them failed instead of leaving them stuck
    # in "running"/"accepted" forever.
    for _stale_status in ("running", "accepted"):
        _stale_jobs, _ = job_store.list_jobs(status=_stale_status, limit=1_000_000)
        for _job in _stale_jobs:
            job_store.update_job(_job["jobID"], status="failed", progress=100,
                                 message="Interrupted by a server restart")

    process_functions = _build_registry(processes)
    processes_listing = {"processes": [cls.get_metadata() for cls in process_functions.values()]}
    # Async jobs run in their own OS process (killable). ``THREAD_NUMBER`` caps how
    # many run at once; ``_running`` maps job_id -> Process so DELETE can kill one.
    _slots = threading.BoundedSemaphore(getattr(config, "THREAD_NUMBER", 2))
    _running = {}
    _running_lock = threading.Lock()

    # Bound the number of async jobs in flight (running + queued supervisor threads)
    # so a flood of ``respond-async`` requests cannot spawn unbounded threads
    # (SECURITY_AUDIT.md #5). Above the cap, new async requests get 429.
    _max_inflight = (getattr(config, "THREAD_NUMBER", 2)
                     + getattr(config, "MAX_ASYNC_QUEUE", 100))
    _inflight = [0]
    _inflight_lock = threading.Lock()

    # Templates live at the package root (../templates). Static is intentionally
    # left to the host app to avoid a duplicate "/static" route on registration.
    bp = Blueprint(
        "flask_ogc_api_processes",
        __name__,
        template_folder="../templates",
        url_prefix=url_prefix if url_prefix != "/" else None,
    )
    # Expose engine internals for introspection / tests.
    bp.ogc_job_store = job_store
    bp.ogc_config = config
    bp.ogc_processes = process_functions
    bp.ogc_running = _running  # job_id -> live async Process (killed by DELETE)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _job_links(job: dict) -> list:
        base = config.URL_PROJET
        links = [{
            "href": f"{base}/jobs/{job['jobID']}",
            "rel": "self",
            "type": "application/json",
            "title": "This job",
        }]
        if job["status"] == "successful":
            links.append({
                "href": f"{base}/jobs/{job['jobID']}/results",
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/results",
                "type": "application/json",
                "title": "Job results",
            })
        return links

    def _job_dict(job: dict, include_links=True) -> dict:
        if include_links:
            job = {**job, "links": _job_links(job)}
        return job

    def _error(type_suffix, title, status, detail, **extra):
        body = {
            "type": f"http://www.opengis.net/def/exceptions/ogcapi-processes-1/1.0/{type_suffix}",
            "title": title,
            "status": status,
            "detail": detail,
        }
        body.update(extra)
        return jsonify(body), status

    def get_process_output_definitions(process_id: str) -> dict:
        process = process_functions.get(process_id)
        if not process:
            return {}
        output_schema = process.OutputSchema.model_json_schema()
        outputs = {}
        for key, item in output_schema.get("properties", {}).items():
            outputs[key] = {
                "title": item.get("title", key),
                "description": item.get("description", ""),
                "schema": {"type": item.get("type", "string")},
            }
        return outputs

    def execute_process(process_id, data, job_id):
        """Synchronous helper: run + persist in the current request thread."""
        return _run_and_persist(process_functions[process_id], data, job_id, job_store)

    def _supervise_async_job(process_id, data, job_id):
        """Run one async job in its own killable process, capped by the semaphore.

        Runs in a lightweight daemon thread: waits for a free slot, spawns the child
        process, records it in ``_running`` (so DELETE can terminate it), waits for
        it, then frees the slot. If the job was dismissed while queued, it never
        starts.
        """
        _slots.acquire()
        try:
            job = job_store.get_job(job_id)
            if job is None or job["status"] == "dismissed":
                return
            proc = _MP_CTX.Process(
                target=_run_and_persist,
                args=(process_functions[process_id], data, job_id, job_store),
                daemon=True,
            )
            proc.start()
            with _running_lock:
                _running[job_id] = proc
            proc.join()
        finally:
            with _running_lock:
                _running.pop(job_id, None)
            _slots.release()
            with _inflight_lock:
                _inflight[0] -= 1

    # ------------------------------------------------------------------ #
    # Routes                                                             #
    # ------------------------------------------------------------------ #
    @bp.get("/")
    def landing():
        service_info = getattr(config, "SERVICE_INFO", None) or build_service_info(
            config.URL_PROJET, config.APP_TITLE
        )
        if _prefers_json(default=False):
            return jsonify(service_info)
        return render_template("public/index.html", api=service_info)

    @bp.get("/processes")
    def get_processes():
        if _prefers_json(default=False):
            return jsonify(processes_listing)
        return render_template("public/processes.html", processes=processes_listing["processes"])

    @bp.get("/processes/<process_id>")
    def get_processes_id(process_id):
        if process_id not in process_functions:
            return jsonify({"error": "Process not found"}), 404
        process = process_functions.get(process_id)
        process_description = dict(process.get_metadata())

        input_description = process.Schema.model_json_schema()
        output_description = process.OutputSchema.model_json_schema()
        process_description["inputs"] = {}
        process_description["outputs"] = {}

        for key, item in input_description["properties"].items():
            min_occurs = 1 if key in input_description.get("required", []) else 0
            process_description["inputs"][key] = {
                "title": item["title"],
                "description": item["description"],
                "schema": {"minOccurs": min_occurs, "maxOccurs": 1, "type": item["type"]},
            }
        for key, item in output_description["properties"].items():
            min_occurs = 1 if key in output_description.get("required", []) else 0
            process_description["outputs"][key] = {
                "title": item["title"],
                "description": item["description"],
                "schema": {"minOccurs": min_occurs, "maxOccurs": 1, "type": item["type"]},
            }

        process_description["links"] = [
            {
                "href": f"{config.URL_PROJET}/processes/{process_id}",
                "rel": "self",
                "type": "application/json",
                "title": "Process description",
            },
            {
                "href": f"{config.URL_PROJET}/processes/{process_id}/execution",
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/execute",
                "type": "application/json",
                "title": "Execute process",
            },
        ]

        if _prefers_json(default=False):
            return jsonify(process_description)
        return render_template("public/process_id.html", process=process_description)

    @bp.post("/processes/<process_id>/execution")
    def execute_process_route(process_id):
        """Execute a process (OGC API Processes compliant endpoint)."""
        if process_id not in process_functions:
            return jsonify({"error": "Process not found"}), 404

        job_id = str(uuid.uuid4())
        job_store.create_job(job_id, process_id, type="process",
                             status="accepted", message="", progress=0)

        request_body = request.get_json()

        # OGC format {"inputs": {...}, "outputs": {...}, "response": "..."}
        # plus direct format for backward compatibility.
        if isinstance(request_body, dict) and "inputs" in request_body:
            data = request_body["inputs"]
            requested_outputs = request_body.get("outputs")
            response_type = request_body.get("response")
        else:
            data = request_body
            requested_outputs = None
            response_type = None

        process_outputs = get_process_output_definitions(process_id)

        # Validate response parameter (OGC execute.yaml)
        try:
            response_type = validate_response_parameter(response_type)
        except ValueError as e:
            job_store.update_job(job_id, status="failed", message=str(e), progress=100)
            return _error("invalid-parameter-value", "Invalid parameter value", 400, str(e))

        # Validate outputs parameter
        try:
            requested_outputs = validate_outputs_parameter(requested_outputs, process_outputs)
        except ValueError as e:
            job_store.update_job(job_id, status="failed", message=str(e), progress=100)
            return _error("invalid-parameter-value", "Invalid parameter value", 400, str(e))

        # Resolve inputs by reference (OGC req/core/process-execute-inputs-B)
        try:
            data = resolve_inputs(
                data,
                allowed_hosts=getattr(config, "REF_ALLOWED_HOSTS", None),
                max_bytes=getattr(config, "MAX_REF_BYTES", 10 * 1024 * 1024),
                max_references=getattr(config, "MAX_REFERENCES_PER_REQUEST", 20),
            )
        except InputResolutionError as e:
            job_store.update_job(job_id, status="failed", message=str(e), progress=100)
            return _error("input-resolution-failed", "Input resolution failed", 400,
                          str(e), input=e.input_name, href=e.href)

        # Async execution?
        prefer = request.headers.get("Prefer")
        if prefer is not None:
            if prefer == "respond-async":
                # Reject (429) instead of spawning an unbounded number of threads
                # when too many async jobs are already in flight (SECURITY_AUDIT.md #5).
                with _inflight_lock:
                    if _inflight[0] >= _max_inflight:
                        job_store.update_job(job_id, status="failed", progress=100,
                                             message="Server busy: too many async jobs queued")
                        return _error("too-many-requests", "Too many requests", 429,
                                      "Too many async jobs in flight; retry later")
                    _inflight[0] += 1
                threading.Thread(
                    target=_supervise_async_job,
                    args=(process_id, data, job_id),
                    daemon=True,
                ).start()
                job = job_store.get_job(job_id)
                response = jsonify(_job_dict(job))
                response.status_code = 201
                response.headers["Location"] = f"/jobs/{job_id}"
                response.headers["Link"] = f'</jobs/{job_id}>; rel="monitor"'
                return response
            return jsonify({"error": "Prefer only accepts: respond-async"}), 400

        # Synchronous execution
        try:
            result, code = execute_process(process_id, data, job_id)
            if code >= 400:
                return jsonify(result), code

            filtered_result = filter_outputs(result, requested_outputs, process_outputs)
            formatted_result, content_type, is_multipart = format_response(
                filtered_result, response_type, requested_outputs
            )
            if is_multipart:
                return Response(formatted_result, status=code, content_type=content_type)
            return jsonify(formatted_result), code
        except Exception:  # noqa: BLE001
            logger.exception("Synchronous execution of process '%s' (job %s) failed",
                             process_id, job_id)
            job_store.update_job(job_id, status="failed", progress=100,
                                 message="Internal processing error")
            return jsonify({"error": "error server in the process execution"}), 500

    @bp.get("/jobs")
    def get_jobs():
        """List jobs (OGC API Processes compliant), with filtering + pagination."""
        job_type = request.args.get("type")
        process_id = request.args.get("processID")
        status = request.args.get("status")
        limit = request.args.get("limit", 10, type=int)
        offset = request.args.get("offset", 0, type=int)

        # ``type=int`` yields None on a non-numeric value; normalize + clamp so a
        # negative/garbage offset can't reach the store (SECURITY_AUDIT.md #11).
        limit = max(1, min(limit if limit is not None else 10, 100))
        offset = max(0, offset if offset is not None else 0)

        jobs_list, total_count = job_store.list_jobs(
            type=job_type, process_id=process_id, status=status, limit=limit, offset=offset
        )

        base_url = f"{config.URL_PROJET}/jobs"
        query_params = []
        if job_type:
            query_params.append(f"type={job_type}")
        if process_id:
            query_params.append(f"processID={process_id}")
        if status:
            query_params.append(f"status={status}")

        links = [{
            "href": f"{base_url}?{'&'.join(query_params + [f'limit={limit}', f'offset={offset}'])}" if query_params else f"{base_url}?limit={limit}&offset={offset}",
            "rel": "self",
            "type": "application/json",
            "title": "This document",
        }]
        if offset + limit < total_count:
            next_params = query_params + [f"limit={limit}", f"offset={offset + limit}"]
            links.append({
                "href": f"{base_url}?{'&'.join(next_params)}",
                "rel": "next",
                "type": "application/json",
                "title": "Next page",
            })
        if offset > 0:
            prev_params = query_params + [f"limit={limit}", f"offset={max(0, offset - limit)}"]
            links.append({
                "href": f"{base_url}?{'&'.join(prev_params)}",
                "rel": "prev",
                "type": "application/json",
                "title": "Previous page",
            })

        response_data = {
            "jobs": jobs_list,
            "links": links,
            "numberMatched": total_count,
            "numberReturned": len(jobs_list),
        }

        if _prefers_json(default=False):
            return jsonify(response_data), 200
        return render_template("public/jobs.html", jobs=jobs_list)

    @bp.get("/jobs/<job_id>")
    def get_job_status(job_id):
        if not _is_valid_job_id(job_id):
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        job_info = job_store.get_job(job_id)
        if job_info is None:
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        return jsonify(_job_dict(job_info))

    @bp.get("/jobs/<job_id>/results")
    def get_job_results(job_id):
        if not _is_valid_job_id(job_id):
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        job_info = job_store.get_job(job_id)
        if job_info is None:
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")

        if job_info["status"] not in ("successful", "failed"):
            return _error("result-not-ready", "Result not ready", 404,
                          f"Job '{job_id}' is still {job_info['status']}")

        if job_info["status"] == "failed":
            return _error("job-failed", "Job failed", 500,
                          f"Job '{job_id}' failed: {job_info['message']}")

        results = job_store.load_results(job_id)
        if results is None:
            return _error("result-not-found", "Results not found", 404,
                          f"Results for job '{job_id}' not found")
        return jsonify(results)

    def _kill_if_running(job_id):
        """Terminate a job's async process if still alive. Safe against PID reuse:
        we hold the multiprocessing.Process OBJECT, never a raw PID, so terminate()
        no-ops once the child is reaped and a recycled PID can't be signalled by
        mistake. ``_running`` is in-memory, so after a restart there is nothing to
        kill (the job is simply already gone from it)."""
        with _running_lock:
            proc = _running.get(job_id)
        if proc is not None and proc.is_alive():
            proc.terminate()          # SIGTERM -> stop even an opaque long task
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()           # SIGKILL fallback
                proc.join(timeout=2)

    @bp.delete("/jobs/<job_id>")
    def delete_job(job_id):
        """OGC dismiss: stop the work and mark the job ``dismissed`` (row kept)."""
        if not _is_valid_job_id(job_id):
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        job_info = job_store.get_job(job_id)
        if job_info is None:
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        _kill_if_running(job_id)
        # Mark dismissed last so it sticks even if the child raced to a terminal state.
        job_store.update_job(job_id, status="dismissed", message="Job dismissed by user", progress=0)
        return jsonify(_job_dict(job_store.get_job(job_id))), 200

    @bp.delete("/jobs/<job_id>/purge")
    def purge_job(job_id):
        """Custom (non-OGC): hard-delete a job - remove its DB row and result file.

        Unlike the OGC dismiss (``DELETE /jobs/{id}``, which keeps a ``dismissed``
        record), this permanently erases the job from the store. If it is still
        running, its process is terminated first.
        """
        if not _is_valid_job_id(job_id):
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        if job_store.get_job(job_id) is None:
            return _error("no-such-job", "No such job", 404, f"Job with ID '{job_id}' not found")
        _kill_if_running(job_id)
        try:
            job_store.delete_job(job_id)
        except NotImplementedError:
            return _error("not-supported", "Not supported", 501,
                          "The configured job store does not support hard deletion")
        return jsonify({"purged": job_id}), 200

    @bp.get("/conformance")
    def get_conformance():
        return jsonify({
            "conformsTo": [
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/core",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/json",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/html",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/oas30",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/ogc-process-description",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/job-list",
                "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/dismiss",
            ]
        })

    @bp.get("/api")
    def get_api():
        """Serve the OpenAPI specification (JSON) or Swagger UI (HTML)."""
        if _prefers_json(default=True):  # API definition defaults to JSON
            return jsonify(generate_openapi_spec(process_functions, config))
        return render_template(
            "public/swagger.html",
            title=config.APP_TITLE,
            spec_url=f"{config.URL_PROJET}/api?f=json",
        )

    return bp
