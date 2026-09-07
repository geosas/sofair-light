"""
Custom OGC-flavoured OpenAPI 3.0 specification generator.

This powers the ``/api`` endpoint (OGC ``oas30`` conformance class). It is a pure
function of the injected process registry and config - no module-level state, no
blueprint. The ``/api`` route itself lives in the blueprint factory.
"""


def generate_openapi_spec(process_functions, config):
    """
    Generate an OpenAPI 3.0 specification dynamically from registered processes.

    Args:
        process_functions: Dictionary mapping process IDs to process classes
        config: Resolved engine config (needs APP_TITLE and URL_PROJET)

    Returns:
        dict: OpenAPI 3.0 specification
    """
    # Get list of available process IDs
    process_ids = list(process_functions.keys())

    # Generate schemas for each process
    process_schemas = {}
    for process_id, process_class in process_functions.items():
        input_schema = process_class.Schema.model_json_schema()
        output_schema = process_class.OutputSchema.model_json_schema()

        # Create example from schema defaults/examples
        example_input = {}
        for field_name, field_info in input_schema.get('properties', {}).items():
            if 'examples' in field_info and field_info['examples']:
                example_input[field_name] = field_info['examples'][0] if isinstance(field_info['examples'], list) else field_info['examples']
            elif 'default' in field_info:
                example_input[field_name] = field_info['default']

        process_schemas[process_id] = {
            'input': input_schema,
            'output': output_schema,
            'example': example_input
        }

    openapi_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": config.APP_TITLE,
            "description": "API compliant with the OGC API - Processes standard, enabling the execution of processing tasks",
            "version": "1.0.0",
            "contact": {
                "name": "GéoSAS",
                "email": "geosas_adm@framalistes.org",
                "url": "https://geosas.fr"
            },
            "license": {
                "name": "GPL-3.0-only",
                "url": "https://www.gnu.org/licenses/gpl-3.0.html"
            }
        },
        "servers": [
            {
                "url": config.URL_PROJET,
                "description": "Production server"
            }
        ],
        "paths": {
            "/": {
                "get": {
                    "summary": "Landing page",
                    "description": "Returns the API landing page with service metadata",
                    "operationId": "getLandingPage",
                    "tags": ["Core"],
                    "parameters": [
                        {
                            "name": "f",
                            "in": "query",
                            "description": "Response format",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["application/json"]
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Service metadata",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/LandingPage"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/conformance": {
                "get": {
                    "summary": "Conformance classes",
                    "description": "Lists the OGC API conformance classes implemented by this service",
                    "operationId": "getConformance",
                    "tags": ["Core"],
                    "responses": {
                        "200": {
                            "description": "Conformance declaration",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ConformanceDeclaration"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/processes": {
                "get": {
                    "summary": "List processes",
                    "description": "Returns the list of available processes",
                    "operationId": "getProcesses",
                    "tags": ["Processes"],
                    "parameters": [
                        {
                            "name": "f",
                            "in": "query",
                            "description": "Response format",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["application/json"]
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "List of processes",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ProcessList"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            **{
                f"/processes/{pid}": {
                    "get": {
                        "summary": f"Get {pid} process description",
                        "description": process_functions[pid].get_metadata().get('description', f"Returns detailed information about the {pid} process"),
                        "operationId": f"getProcess_{pid}",
                        "tags": [pid],
                        "parameters": [
                            {
                                "name": "f",
                                "in": "query",
                                "description": "Response format",
                                "required": False,
                                "schema": {
                                    "type": "string",
                                    "enum": ["application/json"]
                                }
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "Process description",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/ProcessDescription"
                                        }
                                    }
                                }
                            }
                        }
                    }
                } for pid in process_ids
            },
            **{
                f"/processes/{pid}/execution": {
                    "post": {
                        "summary": f"Execute {pid}",
                        "description": process_functions[pid].get_metadata().get('description', f"Execute the {pid} process"),
                        "operationId": f"execute_{pid}",
                        "tags": [pid],
                        "parameters": [
                            {
                                "name": "Prefer",
                                "in": "header",
                                "description": "Execution preference (respond-async for asynchronous execution)",
                                "required": False,
                                "schema": {
                                    "type": "string",
                                    "enum": ["respond-async"]
                                }
                            }
                        ],
                        "requestBody": {
                            "description": f"Execution request for {pid} process",
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": f"#/components/schemas/{pid}Execute"
                                    },
                                    "example": {
                                        "inputs": process_schemas[pid]['example'],
                                        "response": "document"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Synchronous execution result",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": f"#/components/schemas/{pid}Output"
                                        }
                                    },
                                    "multipart/related": {
                                        "schema": {
                                            "type": "string",
                                            "format": "binary"
                                        },
                                        "description": "Multiple outputs with response=raw"
                                    }
                                }
                            },
                            "201": {
                                "description": "Asynchronous execution accepted (job created)",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/StatusInfo"
                                        }
                                    }
                                }
                            },
                            "400": {
                                "description": "Invalid parameter",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Error"
                                        }
                                    }
                                }
                            },
                            "422": {
                                "description": "Validation error",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/ValidationError"
                                        }
                                    }
                                }
                            }
                        }
                    }
                } for pid in process_ids
            },
            "/jobs": {
                "get": {
                    "summary": "List jobs",
                    "description": "Returns a list of jobs with optional filtering and pagination",
                    "operationId": "getJobs",
                    "tags": ["Jobs"],
                    "parameters": [
                        {
                            "name": "type",
                            "in": "query",
                            "description": "Filter by job type",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["process"]
                            }
                        },
                        {
                            "name": "processID",
                            "in": "query",
                            "description": "Filter by process identifier",
                            "required": False,
                            "schema": {
                                "type": "string"
                            }
                        },
                        {
                            "name": "status",
                            "in": "query",
                            "description": "Filter by job status",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["accepted", "running", "successful", "failed", "dismissed"]
                            }
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "description": "Maximum number of jobs to return (1-100, default: 10)",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "default": 10
                            }
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "description": "Number of jobs to skip for pagination",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "minimum": 0,
                                "default": 0
                            }
                        },
                        {
                            "name": "f",
                            "in": "query",
                            "description": "Response format",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["application/json"]
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "List of jobs with pagination info",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/JobList"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/jobs/{jobId}": {
                "get": {
                    "summary": "Get job status",
                    "description": "Returns the status of a specific job",
                    "operationId": "getJobStatus",
                    "tags": ["Jobs"],
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "description": "Job identifier (UUID)",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "format": "uuid"
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Job status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/JobStatus"
                                    }
                                }
                            }
                        },
                        "404": {
                            "description": "Job not found",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Error"
                                    }
                                }
                            }
                        }
                    }
                },
                "delete": {
                    "summary": "Dismiss/cancel a job",
                    "description": "Dismisses a job. Sets the job status to 'dismissed'.",
                    "operationId": "dismissJob",
                    "tags": ["Jobs"],
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "description": "Job identifier (UUID)",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "format": "uuid"
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Job dismissed successfully",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/JobStatus"
                                    }
                                }
                            }
                        },
                        "404": {
                            "description": "Job not found",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Error"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/jobs/{jobId}/results": {
                "get": {
                    "summary": "Get job results",
                    "description": "Returns the results of a completed job",
                    "operationId": "getJobResults",
                    "tags": ["Jobs"],
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "description": "Job identifier (UUID)",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "format": "uuid"
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Job result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/JobStatus"
                                    }
                                }
                            }
                        },
                        "404": {
                            "description": "Job not found",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Error"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api": {
                "get": {
                    "summary": "API definition",
                    "description": "Returns the OpenAPI 3.0 specification for this API in JSON format or as interactive Swagger UI documentation",
                    "operationId": "getApiDefinition",
                    "tags": ["Core"],
                    "parameters": [
                        {
                            "name": "f",
                            "in": "query",
                            "description": "Response format: 'json' for OpenAPI JSON spec, 'html' for Swagger UI",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["json", "html"],
                                "default": "json"
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OpenAPI specification (JSON) or Swagger UI (HTML)",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object"
                                    }
                                },
                                "text/html": {
                                    "schema": {
                                        "type": "string"
                                    }
                                }
                            }
                        },
                        "400": {
                            "description": "Invalid format parameter",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Error"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "LandingPage": {
                    "type": "object",
                    "properties": {
                        "@context": {"type": "string"},
                        "@type": {"type": "string"},
                        "@id": {"type": "string"},
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "termsOfService": {"type": "string"},
                        "license": {"type": "string"},
                        "provider": {"type": "object"},
                        "links": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Link"}
                        }
                    }
                },
                "ConformanceDeclaration": {
                    "type": "object",
                    "properties": {
                        "conformsTo": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                },
                "ProcessList": {
                    "type": "object",
                    "properties": {
                        "processes": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/ProcessSummary"}
                        }
                    }
                },
                "ProcessSummary": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "version": {"type": "number"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "links": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Link"}
                        },
                        "jobControlOptions": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "outputTransmission": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                },
                "ProcessDescription": {
                    "allOf": [
                        {"$ref": "#/components/schemas/ProcessSummary"},
                        {
                            "type": "object",
                            "properties": {
                                "inputs": {"type": "object"},
                                "outputs": {"type": "object"}
                            }
                        }
                    ]
                },
                "JobList": {
                    "type": "object",
                    "properties": {
                        "jobs": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/JobStatus"}
                        },
                        "links": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Link"},
                            "description": "Navigation links (self, next, prev)"
                        },
                        "numberMatched": {
                            "type": "integer",
                            "description": "Total number of jobs matching the query"
                        },
                        "numberReturned": {
                            "type": "integer",
                            "description": "Number of jobs returned in this response"
                        }
                    }
                },
                "JobStatus": {
                    "type": "object",
                    "required": ["jobID", "processID", "type", "status", "progress", "created", "updated"],
                    "properties": {
                        "jobID": {
                            "type": "string",
                            "format": "uuid",
                            "description": "Unique job identifier"
                        },
                        "processID": {
                            "type": "string",
                            "description": "Process identifier"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["process"],
                            "description": "Job type"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["accepted", "running", "successful", "failed", "dismissed"],
                            "description": "Job status"
                        },
                        "message": {
                            "type": "string",
                            "description": "Optional message"
                        },
                        "progress": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                            "description": "Progress percentage"
                        },
                        "created": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Job creation timestamp"
                        },
                        "started": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Job start timestamp"
                        },
                        "finished": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Job finish timestamp"
                        },
                        "updated": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Last update timestamp"
                        },
                        "links": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Link"},
                            "description": "Related links"
                        }
                    }
                },
                "StatusInfo": {
                    "description": "Job status info returned for async execution",
                    "allOf": [{"$ref": "#/components/schemas/JobStatus"}]
                },
                "Execute": {
                    "type": "object",
                    "description": "Execute request body following OGC API Processes standard",
                    "required": ["inputs"],
                    "properties": {
                        "inputs": {
                            "type": "object",
                            "description": "Input parameters for the process"
                        },
                        "outputs": {
                            "type": "object",
                            "description": "Output parameters specification (optional)"
                        },
                        "response": {
                            "type": "string",
                            "enum": ["raw", "document"],
                            "default": "document",
                            "description": "Response format: document (default, JSON) or raw (multipart for multiple outputs)"
                        }
                    }
                },
                "Link": {
                    "type": "object",
                    "properties": {
                        "href": {"type": "string"},
                        "rel": {"type": "string"},
                        "type": {"type": "string"},
                        "title": {"type": "string"},
                        "hreflang": {"type": "string"}
                    }
                },
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"}
                    }
                },
                "ValidationError": {
                    "type": "object",
                    "properties": {
                        "msg": {"type": "string"},
                        "errors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string"},
                                    "message": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                **{
                    f"{pid}Input": process_schemas[pid]['input']
                    for pid in process_ids
                },
                **{
                    f"{pid}Output": process_schemas[pid]['output']
                    for pid in process_ids
                },
                **{
                    f"{pid}Execute": {
                        "type": "object",
                        "description": f"Execute request for {pid} process",
                        "required": ["inputs"],
                        "properties": {
                            "inputs": {
                                "$ref": f"#/components/schemas/{pid}Input"
                            },
                            "outputs": {
                                "type": "object",
                                "description": "Output parameters specification (optional)"
                            },
                            "response": {
                                "type": "string",
                                "enum": ["raw", "document"],
                                "default": "document",
                                "description": "Response format: document (default, JSON) or raw (multipart for multiple outputs)"
                            }
                        }
                    }
                    for pid in process_ids
                }
            }
        },
        "tags": [
            {
                "name": "Core",
                "description": "Core API endpoints (landing page, conformance, OpenAPI)"
            },
            {
                "name": "Processes",
                "description": "Process listing endpoint"
            },
            *[
                {
                    "name": pid,
                    "description": process_functions[pid].get_metadata().get('description', f"Endpoints for {pid} process")
                }
                for pid in process_ids
            ],
            {
                "name": "Jobs",
                "description": "Job management and status endpoints"
            }
        ]
    }

    return openapi_spec
