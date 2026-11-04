"""Shared MCP tool argument, capacity, and structured failure boundary."""

import json
from collections import Counter
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError
from starlette.requests import Request

from aw2_lab.api_validation import map_error
from aw2_lab.authorization import AuthorizationError
from aw2_lab.match_contract import ContractModel, ErrorCode
from aw2_lab.match_controller import MatchControllerError
from aw2_lab.mcp_auth import caller_from_request
from aw2_lab.mcp_contract import MCPFailure
from aw2_lab.mcp_tools import MCP_BODY_BYTES
from aw2_lab.sdk import APIError, ProtocolError, TransportError


def failure(
    code: str,
    message: str,
    *,
    http_status: int | None = None,
    request_id: str | None = None,
    body: dict[str, Any] | None = None,
) -> types.CallToolResult:
    payload: dict[str, Any] = {
        "contract_version": 1,
        "error": body or {"code": code, "message": message},
    }
    if http_status is not None:
        payload["http_status"] = http_status
    if request_id is not None:
        payload["request_id"] = request_id
    payload = MCPFailure.model_validate(payload).model_dump(mode="json", exclude_none=True)
    return types.CallToolResult(
        isError=True,
        structuredContent=payload,
        content=[types.TextContent(type="text", text=json.dumps(payload))],
    )


class AW2MCP(FastMCP):
    """Keep successful shared schemas and preserve application errors as tool results."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._calls: Counter[str] = Counter()
        super().__init__(*args, **kwargs)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        identity = None
        try:
            try:
                request = self.get_context().request_context.request
            except ValueError:
                request = None
            if not isinstance(request, Request):
                raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Authentication required")
            caller = caller_from_request(request)
            identity = caller.principal.model_dump_json()
            if self._calls[identity] >= 4 or self._calls.total() >= 64:
                return failure("capacity_exceeded", "MCP tool capacity exceeded")
            self._calls[identity] += 1
            try:
                ContractModel.model_validate(
                    {"contract_version": arguments.get("contract_version", 1)}
                )
                tool = self._tool_manager.get_tool(name)
                if tool is None:
                    return failure("unknown_tool", "Unknown tool")
                properties = tool.parameters.get("properties", {})
                if arguments.keys() - properties.keys():
                    return failure("invalid_request", "Unknown tool arguments", http_status=400)
                if (
                    name == "create_match"
                    and "configuration" in arguments
                    and arguments["configuration"] is None
                ):
                    return failure(
                        "invalid_request",
                        "Provided configuration must be complete",
                        http_status=400,
                    )
                limit = MCP_BODY_BYTES if name == "import_checkpoint" else 65536
                if len(json.dumps(arguments).encode()) > limit:
                    return failure(
                        "invalid_request", "Tool arguments exceed limit", http_status=413
                    )
                result = await super().call_tool(name, arguments)
                caller.check()
                return result
            finally:
                self._calls[identity] -= 1
                if not self._calls[identity]:
                    del self._calls[identity]
        except Exception as error:  # noqa: BLE001 -- sanitize SDK and tool failures at the MCP boundary
            cause = error.__cause__ if isinstance(error, ToolError) else error
            if isinstance(cause, APIError):
                return failure(
                    cause.response.error.code.value,
                    "API request failed",
                    http_status=cause.status,
                    request_id=str(cause.response.request_id)
                    if cause.response.request_id
                    else None,
                    body=cause.response.error.model_dump(mode="json"),
                )
            if isinstance(cause, (AuthorizationError, MatchControllerError)):
                mapped = map_error(cause.body)
                return failure(
                    cause.body.code.value,
                    cause.body.message,
                    http_status=mapped.status_code,
                    body=cause.body.model_dump(mode="json"),
                )
            if isinstance(cause, TransportError):
                return failure(
                    "outcome_unknown",
                    "HTTP outcome is unknown; retry the identical request ID and payload",
                    request_id=str(cause.request_id) if cause.request_id else None,
                )
            if isinstance(cause, ProtocolError):
                return failure("protocol_error", "Invalid API response")
            if isinstance(cause, TimeoutError):
                return failure("timeout", "MCP wait deadline expired")
            if isinstance(cause, (ValidationError, ValueError, TypeError)):
                return failure("invalid_request", "Invalid tool arguments", http_status=400)
            return failure("internal_error", "MCP tool failed")
