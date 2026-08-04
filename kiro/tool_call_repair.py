"""Recovery for Kiro streams interrupted while emitting large tool inputs."""

import copy
import json
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
from loguru import logger

from kiro.config import TOOL_CALL_TEXT_RECOVERY


ToolCallRepairer = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
REPAIRER_EXTENSION_KEY = "kiro_tool_call_repairer"


def _find_tool_schema(payload: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    """Find a named tool's JSON input schema in a Kiro request payload."""
    current = payload.get("conversationState", {}).get("currentMessage", {}).get("userInputMessage", {})
    tools = current.get("userInputMessageContext", {}).get("tools", [])
    for entry in tools:
        specification = entry.get("toolSpecification", {})
        if specification.get("name") == tool_name:
            schema = specification.get("inputSchema", {}).get("json", {})
            return schema if isinstance(schema, dict) else {}
    return {}


def _build_repair_payload(
    original_payload: Dict[str, Any],
    tool_name: str,
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a text-only request that reproduces one tool's complete input."""
    payload = copy.deepcopy(original_payload)
    conversation_state = payload["conversationState"]
    conversation_state["conversationId"] = str(uuid.uuid4())
    user_message = conversation_state["currentMessage"]["userInputMessage"]
    context = user_message.get("userInputMessageContext")
    if isinstance(context, dict):
        context.pop("tools", None)
        if not context:
            user_message.pop("userInputMessageContext", None)

    schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    user_message["content"] = (
        f"{user_message.get('content', '')}\n\n"
        "[Gateway recovery instruction]\n"
        f"Your previous call to tool {tool_name!r} was interrupted while its input was being transported. "
        "Reconstruct the exact complete input now. Return only one valid JSON object containing the tool "
        "arguments. Do not use Markdown, commentary, or a tool call. Preserve long string values verbatim.\n"
        f"Tool input schema: {schema_json}"
    )

    fields = payload.setdefault("additionalModelRequestFields", {})
    fields["thinking"] = {"type": "disabled"}
    fields["output_config"] = {"effort": "low"}
    return payload


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Extract and validate one JSON object from a model text response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        last_fence = stripped.rfind("```")
        if first_newline >= 0 and last_fence > first_newline:
            stripped = stripped[first_newline + 1:last_fence].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("repair response did not contain a JSON object")
    value = json.loads(stripped[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("repair response JSON was not an object")
    return value


def attach_tool_call_repairer(
    response: httpx.Response,
    auth_manager: Any,
    url: str,
    original_payload: Dict[str, Any],
) -> None:
    """Attach a lazy large-tool-input repair callback to an upstream response."""
    if not TOOL_CALL_TEXT_RECOVERY:
        return

    async def repair(tool_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        function = tool_call.get("function", {})
        tool_name = function.get("name", "") or tool_call.get("name", "")
        if not tool_name:
            return None

        schema = _find_tool_schema(original_payload, tool_name)
        repair_payload = _build_repair_payload(original_payload, tool_name, schema)
        logger.warning("Recovering interrupted tool input for '{}' through text-only inference", tool_name)

        # Use an isolated client so repair responses cannot recursively attach
        # another repair callback or reuse the interrupted connection.
        from kiro.http_client import KiroHttpClient
        from kiro.streaming_core import collect_stream_to_result

        repair_client = KiroHttpClient(auth_manager, shared_client=None)
        repair_response: Optional[httpx.Response] = None
        try:
            repair_response = await repair_client.request_with_retry(
                "POST", url, repair_payload, stream=True
            )
            if repair_response.status_code != 200:
                body = await repair_response.aread()
                raise ValueError(
                    f"repair inference returned HTTP {repair_response.status_code}: "
                    f"{body.decode('utf-8', errors='replace')[:200]}"
                )
            result = await collect_stream_to_result(repair_response)
            arguments = _extract_json_object(result.content)
            required = schema.get("required", []) if isinstance(schema, dict) else []
            missing = [name for name in required if name not in arguments]
            if missing:
                raise ValueError(f"repair response omitted required fields: {missing}")

            repaired = copy.deepcopy(tool_call)
            repaired.setdefault("function", {})["arguments"] = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            repaired.pop("_truncation_detected", None)
            repaired.pop("_truncation_info", None)
            logger.info(
                "Recovered tool input for '{}': {} bytes",
                tool_name,
                len(repaired["function"]["arguments"].encode("utf-8")),
            )
            return repaired
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error("Tool input text recovery failed for '{}': {}", tool_name, exc)
            return None
        finally:
            if repair_response is not None:
                try:
                    await repair_response.aclose()
                except httpx.HTTPError:
                    pass
            await repair_client.close()

    response.extensions[REPAIRER_EXTENSION_KEY] = repair
