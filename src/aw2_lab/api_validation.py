"""Transport-independent configuration validation and safe v1 error translation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from aw2_lab.api_contract import VERIFIED_CONFIGURATION, CreateMatchRequest, MatchConfiguration
from aw2_lab.match_contract import ErrorBody, ErrorCode, ErrorResponse, FixedMatchConfiguration

# Recognized IDs do not imply playable combinations. Only the profile below is verified.
KNOWN_CO_IDS = frozenset(
    [
        "andy",
        "max",
        "sami",
        "nell",
        "hachi",
        "olaf",
        "grit",
        "colin",
        "kanbei",
        "sonja",
        "sensei",
        "eagle",
        "drake",
        "jess",
        "flak",
        "lash",
        "adder",
        "hawke",
        "sturm",
    ]
)
KNOWN_MAP_IDS = frozenset({"bean_island"})


def resolve_configuration(request: CreateMatchRequest) -> MatchConfiguration:
    """Resolve on first creation; the caller persists this result for subsequent retries."""
    return validate_configuration(request.configuration or VERIFIED_CONFIGURATION)


class ContractValidationError(ValueError):
    """Safe shared-service failure, independent of HTTP and MCP framing."""

    def __init__(self, code: ErrorCode, message: str, *, field: str) -> None:
        super().__init__(message)
        self.body = ErrorBody(code=code, message=message, details={"field": field})


def validate_configuration(configuration: MatchConfiguration) -> MatchConfiguration:
    """Reject unknown catalogs before checking the whole supported combination."""
    if configuration.map_id not in KNOWN_MAP_IDS:
        raise ContractValidationError(
            ErrorCode.INVALID_REQUEST, "Unknown map identifier", field="configuration.map_id"
        )
    if any(player.co_id not in KNOWN_CO_IDS for player in configuration.players):
        raise ContractValidationError(
            ErrorCode.INVALID_REQUEST, "Unknown CO identifier", field="configuration.players.co_id"
        )
    if configuration != VERIFIED_CONFIGURATION:
        raise ContractValidationError(
            ErrorCode.UNSUPPORTED_FEATURE,
            "Configuration does not match a verified profile",
            field="configuration",
        )
    return configuration


def configuration_to_controller(configuration: MatchConfiguration) -> FixedMatchConfiguration:
    """Prevent an unsupported transport configuration from being silently defaulted."""
    validate_configuration(configuration)
    return FixedMatchConfiguration()


ERROR_HTTP_STATUS: Mapping[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.UNSUPPORTED_FEATURE: 422,
    ErrorCode.MATCH_NOT_FOUND: 404,
    ErrorCode.ACTIVE_MATCH_EXISTS: 409,
    ErrorCode.MATCH_CLOSED: 409,
    ErrorCode.MATCH_FINISHED: 409,
    ErrorCode.SLOT_UNAVAILABLE: 409,
    ErrorCode.INVALID_CREDENTIAL: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.INVALID_INVITATION: 403,
    ErrorCode.NOT_YOUR_TURN: 409,
    ErrorCode.STALE_REVISION: 409,
    ErrorCode.REQUEST_ID_CONFLICT: 409,
    ErrorCode.COMMAND_NOT_FOUND: 404,
    ErrorCode.COMMAND_CAPACITY: 429,
    ErrorCode.SERVER_SHUTTING_DOWN: 503,
    ErrorCode.OBSERVATION_UNAVAILABLE: 409,
    ErrorCode.ACTION_REJECTED: 409,
    ErrorCode.TIMEOUT: 409,
    ErrorCode.ROLLBACK_FAILED: 409,
    ErrorCode.RECOVERY_REQUIRED: 409,
    ErrorCode.CHECKPOINT_INCOMPATIBLE: 409,
    ErrorCode.CHECKPOINT_CORRUPT: 400,
    ErrorCode.CHECKPOINT_NOT_FOUND: 404,
    ErrorCode.JOURNAL_CORRUPT: 503,
    ErrorCode.STORAGE_UNAVAILABLE: 503,
    ErrorCode.RUNTIME_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


@dataclass(frozen=True)
class HttpError:
    status_code: int
    response: ErrorResponse
    headers: Mapping[str, str]


def map_error(
    body: ErrorBody,
    *,
    request_id: UUID | None = None,
    request_failure_status: Literal[400, 413, 415, 422] | None = None,
) -> HttpError:
    """Map trusted safe service errors; never pass arbitrary exception messages here."""
    if request_failure_status is not None and body.code is not ErrorCode.INVALID_REQUEST:
        raise ValueError("Request failure status applies only to invalid_request")
    status = request_failure_status or ERROR_HTTP_STATUS[body.code]
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = "1"
    return HttpError(status, ErrorResponse(error=body, request_id=request_id), headers)


# Only schema-owned location names are ever exposed. Extra keys and union tags can be secrets.
_SAFE_FIELDS = frozenset(
    [
        "contract_version",
        "request_id",
        "configuration",
        "map_id",
        "players",
        "slot",
        "co_id",
        "color",
        "team_id",
        "control",
        "rules",
        "fog",
        "starting_weather",
        "starting_funds",
        "day_limit",
        "co_powers",
        "display_name",
        "invitation_token",
        "expires_in_seconds",
        "expected_revision",
        "action",
        "kind",
        "unit_id",
        "path",
        "x",
        "y",
        "target",
        "property",
        "unit_type",
        "buttons",
        "frames",
        "address",
        "length",
        "data",
    ]
)


def validation_error(error: ValidationError, *, request_id: UUID | None = None) -> HttpError:
    """Remove input, validator context, arbitrary keys, and messages from Pydantic errors."""
    details: dict[str, str | int | bool | None] = {"issue_count": error.error_count()}
    for index, issue in enumerate(error.errors(include_input=False, include_context=False)[:16]):
        path = ".".join(
            str(part) if isinstance(part, int) or part in _SAFE_FIELDS else "field"
            for part in issue["loc"][:10]
        )
        details[f"field_{index + 1}"] = path or "request"
    return map_error(
        ErrorBody(
            code=ErrorCode.INVALID_REQUEST, message="Request validation failed", details=details
        ),
        request_id=request_id,
    )


def internal_error(*, request_id: UUID | None = None) -> HttpError:
    return map_error(
        ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="Internal server error"),
        request_id=request_id,
    )
