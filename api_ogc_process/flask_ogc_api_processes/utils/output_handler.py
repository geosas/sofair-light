"""
Output handler for OGC API Processes.

Handles the `outputs` and `response` parameters as specified in:
- OGC API Processes 1.0, execute.yaml schema
- Requirement /req/core/process-execute-default-outputs
- Requirement /req/core/process-execute-sync-document
- Requirement /req/core/process-execute-sync-raw-value-one
- Requirement /req/core/process-execute-sync-raw-value-multi (multipart/related)
"""
from typing import Any
import json
import uuid


def filter_outputs(results: dict, requested_outputs: dict | None, process_outputs: dict) -> dict:
    """
    Filter process results based on requested outputs.

    According to OGC standard (req/core/process-execute-default-outputs):
    If outputs parameter is omitted, return all defined outputs.

    Args:
        results: The raw results from the process execution
        requested_outputs: The outputs parameter from execute request, or None
        process_outputs: The output definitions from the process description

    Returns:
        Filtered results containing only requested outputs
    """
    if requested_outputs is None:
        # No outputs specified = return all outputs (default behavior)
        return results

    if not requested_outputs:
        # Empty outputs dict = return all outputs
        return results

    # Filter to only include requested outputs
    filtered = {}
    for output_id in requested_outputs.keys():
        if output_id in results:
            filtered[output_id] = results[output_id]
        # Note: If a requested output is not in results, we silently skip it
        # The process might not have produced that output

    return filtered


def get_content_type_for_value(value: Any) -> str:
    """
    Determine the appropriate Content-Type for a value.

    Args:
        value: The output value

    Returns:
        MIME type string
    """
    if isinstance(value, (dict, list)):
        return "application/json"
    elif isinstance(value, str):
        return "text/plain"
    elif isinstance(value, (int, float)):
        return "application/json"
    elif isinstance(value, bytes):
        return "application/octet-stream"
    else:
        return "application/json"


def serialize_value(value: Any, content_type: str) -> str:
    """
    Serialize a value to string based on content type.

    Args:
        value: The value to serialize
        content_type: The target content type

    Returns:
        Serialized string representation
    """
    if content_type == "application/json":
        return json.dumps(value)
    elif content_type == "text/plain":
        return str(value)
    else:
        return json.dumps(value)


def create_multipart_response(results: dict, requested_outputs: dict | None = None) -> tuple[bytes, str]:
    """
    Create a multipart/related response for multiple outputs.

    Conforms to RFC 2387 (The MIME Multipart/Related Content-type)
    and OGC requirement /req/core/process-execute-sync-raw-value-multi.

    Args:
        results: Dictionary of output_id -> value
        requested_outputs: Optional outputs specification with format info

    Returns:
        Tuple of (body_bytes, content_type_with_boundary)
    """
    # Generate a unique boundary
    boundary = f"ogc_boundary_{uuid.uuid4().hex[:16]}"

    parts = []

    for output_id, value in results.items():
        # Get the content type for this output
        # Check if format was specified in request
        format_spec = None
        if requested_outputs and output_id in requested_outputs:
            output_spec = requested_outputs[output_id]
            if isinstance(output_spec, dict):
                format_spec = output_spec.get("format")

        if format_spec and "mediaType" in format_spec:
            content_type = format_spec["mediaType"]
        else:
            content_type = get_content_type_for_value(value)

        # Serialize the value
        serialized = serialize_value(value, content_type)

        # Build the part according to RFC 2387
        # Content-ID header is required by OGC standard
        part_headers = [
            f"Content-Type: {content_type}",
            f"Content-ID: <{output_id}>"
        ]

        part = "\r\n".join(part_headers) + "\r\n\r\n" + serialized
        parts.append(part)

    # Assemble the multipart body
    body = ""
    for part in parts:
        body += f"--{boundary}\r\n"
        body += part + "\r\n"
    body += f"--{boundary}--\r\n"

    # Content-Type header with boundary and type parameter
    # type parameter indicates the MIME type of the "root" (first) part
    first_output_id = list(results.keys())[0]
    first_value = results[first_output_id]
    root_type = get_content_type_for_value(first_value)

    content_type = f'multipart/related; boundary="{boundary}"; type="{root_type}"'

    return body.encode('utf-8'), content_type


def format_response(results: dict, response_type: str, requested_outputs: dict | None = None) -> tuple[Any, str, bool]:
    """
    Format the response based on the response parameter.

    Args:
        results: The (filtered) results from process execution
        response_type: Either "raw" or "document"
        requested_outputs: Optional outputs specification (for format info in multipart)

    Returns:
        Tuple of (formatted_result, content_type, is_multipart)
        - is_multipart: True if the response is multipart/related (body is bytes)

    According to OGC standard:
    - response=raw with 1 output: Return output directly
    - response=raw with multiple outputs: Return multipart/related (RFC 2387)
    - response=document: Return results wrapped in a JSON document (results.yaml format)
    """
    if response_type == "document":
        # Return as OGC results document (results.yaml format)
        # The document is a map of output identifiers to values
        return results, "application/json", False

    # response=raw (default)
    if len(results) == 1:
        # Single output: return the value directly
        # OGC req/core/process-execute-sync-raw-value-one
        output_id = list(results.keys())[0]
        value = results[output_id]
        content_type = get_content_type_for_value(value)

        # For raw single output, we still return as JSON dict for consistency
        # (the Flask route will jsonify it)
        return results, content_type, False
    else:
        # Multiple outputs with response=raw
        # OGC req/core/process-execute-sync-raw-value-multi
        # Return multipart/related response
        body, content_type = create_multipart_response(results, requested_outputs)
        return body, content_type, True


def get_output_format(output_id: str, requested_outputs: dict | None) -> dict | None:
    """
    Get the requested format for a specific output.

    Args:
        output_id: The output identifier
        requested_outputs: The outputs parameter from execute request

    Returns:
        Format dict with mediaType, or None if not specified
    """
    if requested_outputs is None:
        return None

    output_spec = requested_outputs.get(output_id)
    if output_spec is None:
        return None

    return output_spec.get("format")


def get_transmission_mode(output_id: str, requested_outputs: dict | None) -> str:
    """
    Get the transmission mode for a specific output.

    Args:
        output_id: The output identifier
        requested_outputs: The outputs parameter from execute request

    Returns:
        "value" or "reference" (default: "value")
    """
    if requested_outputs is None:
        return "value"

    output_spec = requested_outputs.get(output_id)
    if output_spec is None:
        return "value"

    return output_spec.get("transmissionMode", "value")


def validate_response_parameter(response: str | None) -> str:
    """
    Validate and normalize the response parameter.

    Args:
        response: The response parameter value

    Returns:
        Normalized value ("raw" or "document")

    Raises:
        ValueError: If response value is invalid
    """
    if response is None:
        # Default to "document" for better client compatibility
        # (multipart/related from response=raw is harder to parse)
        # OGC standard says default is "raw", but "document" is more practical
        return "document"

    response = response.lower()
    if response not in ("raw", "document"):
        raise ValueError(f"Invalid response value: '{response}'. Must be 'raw' or 'document'.")

    return response


def validate_outputs_parameter(outputs: dict | None, process_outputs: dict) -> dict | None:
    """
    Validate the outputs parameter against process output definitions.

    Args:
        outputs: The outputs parameter from execute request
        process_outputs: The output definitions from the process description

    Returns:
        Validated outputs dict, or None if not specified

    Raises:
        ValueError: If an unknown output is requested
    """
    if outputs is None:
        return None

    # Check that all requested outputs are defined in the process
    unknown_outputs = set(outputs.keys()) - set(process_outputs.keys())
    if unknown_outputs:
        raise ValueError(
            f"Unknown output(s) requested: {', '.join(unknown_outputs)}. "
            f"Available outputs: {', '.join(process_outputs.keys())}"
        )

    # Validate transmissionMode values
    for output_id, output_spec in outputs.items():
        if isinstance(output_spec, dict):
            transmission_mode = output_spec.get("transmissionMode")
            if transmission_mode and transmission_mode not in ("value", "reference"):
                raise ValueError(
                    f"Invalid transmissionMode for output '{output_id}': '{transmission_mode}'. "
                    "Must be 'value' or 'reference'."
                )

    return outputs
