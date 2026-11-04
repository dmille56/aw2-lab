"""Structured MCP application failures, separate from JSON-RPC protocol errors."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from aw2_lab.match_contract import ContractModel, ErrorBody


class AdapterError(ContractModel):
    code: Literal["outcome_unknown", "protocol_error", "capacity_exceeded", "unknown_tool"]
    message: str


class MCPFailure(ContractModel):
    error: ErrorBody | AdapterError
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    request_id: UUID | None = None
