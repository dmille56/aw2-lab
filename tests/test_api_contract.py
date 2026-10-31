"""ROM-independent checks for the proposed shared v1 transport boundary."""

import base64
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from test_match_observation import decode
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture

from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    CapabilitiesResponse,
    CloseMatchRequest,
    CreateMatchRequest,
    DebugButtonsRequest,
    DebugMemoryReadRequest,
    DebugMemoryWriteRequest,
    FeatureAvailability,
    GameplayCommandRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
    JoinSlotResponse,
    MatchConfiguration,
    PlayerPrincipal,
    Principal,
    SlotAuthorization,
    StateResponse,
    configuration_from_controller,
    summary_from_controller,
)
from aw2_lab.api_validation import (
    ERROR_HTTP_STATUS,
    ContractValidationError,
    configuration_to_controller,
    internal_error,
    map_error,
    resolve_configuration,
    validate_configuration,
    validation_error,
)
from aw2_lab.match_contract import (
    ErrorBody,
    ErrorCode,
    FixedMatchConfiguration,
    MatchLifecycle,
    MatchRules,
    MatchSummary,
    PlayerSlot,
    PlayerSlotState,
    SlotStatus,
)
from aw2_lab.match_observation import MatchObservationTracker


def profile() -> dict:
    return VERIFIED_CONFIGURATION.model_dump(mode="json")


def summary() -> MatchSummary:
    return MatchSummary(
        match_id=uuid4(),
        revision=0,
        lifecycle=MatchLifecycle.SETUP,
        configuration=FixedMatchConfiguration(),
        slots=tuple(PlayerSlotState(slot=slot, status=SlotStatus.OPEN) for slot in PlayerSlot),
        created_at=datetime.now(UTC),
    )


def test_profile_round_trip_and_explicit_legacy_adapter() -> None:
    configuration = MatchConfiguration.model_validate_json(VERIFIED_CONFIGURATION.model_dump_json())
    assert validate_configuration(configuration) == VERIFIED_CONFIGURATION
    assert (
        configuration_from_controller(configuration_to_controller(configuration)) == configuration
    )
    old = FixedMatchConfiguration(rules=MatchRules(day_limit=20))
    converted = configuration_from_controller(old)
    assert converted.rules.day_limit == 20
    with pytest.raises(ContractValidationError, match="verified profile"):
        configuration_to_controller(converted)


@pytest.mark.parametrize("change", ["fog", "co", "funds", "weather", "team", "cpu", "count"])
def test_known_unverified_combinations_are_unsupported(change: str) -> None:
    data = profile()
    if change == "fog":
        data["rules"]["fog"] = True
    elif change == "co":
        data["players"][0]["co_id"] = "sami"
    elif change == "funds":
        data["rules"]["starting_funds"] = 2000
    elif change == "weather":
        data["rules"]["starting_weather"] = "rain"
    elif change == "team":
        data["players"][1]["team_id"] = "a"
    elif change == "cpu":
        data["players"][0]["control"] = "computer"
    else:
        data["players"].append(dict(data["players"][0], slot="slot_3", color="green"))
    with pytest.raises(ContractValidationError) as caught:
        validate_configuration(MatchConfiguration.model_validate(data))
    assert caught.value.body.code is ErrorCode.UNSUPPORTED_FEATURE


@pytest.mark.parametrize("field", ["map_id", "co_id"])
def test_unknown_identifiers_are_invalid(field: str) -> None:
    data = profile()
    if field == "map_id":
        data[field] = "unknown_map"
    else:
        data["players"][0][field] = "unknown_co"
    with pytest.raises(ContractValidationError) as caught:
        validate_configuration(MatchConfiguration.model_validate(data))
    assert caught.value.body.code is ErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("change", ["slot", "color", "missing", "bool_integer", "string_bool"])
def test_malformed_configuration_is_rejected(change: str) -> None:
    data = profile()
    if change in {"slot", "color"}:
        data["players"][1][change] = data["players"][0][change]
    elif change == "missing":
        del data["rules"]["fog"]
    elif change == "bool_integer":
        data["rules"]["day_limit"] = True
    else:
        data["rules"]["fog"] = "false"
    with pytest.raises(ValidationError):
        MatchConfiguration.model_validate(data)


def test_creation_omission_is_distinct_from_null_and_complete_config() -> None:
    request_id = uuid4()
    assert CreateMatchRequest(request_id=request_id).configuration is None
    assert (
        resolve_configuration(CreateMatchRequest(request_id=request_id)) == VERIFIED_CONFIGURATION
    )
    assert CreateMatchRequest(
        request_id=request_id, configuration=VERIFIED_CONFIGURATION
    ).configuration
    with pytest.raises(ValidationError):
        CreateMatchRequest.model_validate({"request_id": request_id, "configuration": None})
    with pytest.raises(ValidationError):
        CreateMatchRequest.model_validate({"request_id": request_id, "configuration": {}})


@pytest.mark.parametrize("version", [True, 1.0, "1", 0, 2])
def test_contract_version_is_explicitly_v1(version: object) -> None:
    with pytest.raises(ValidationError):
        CreateMatchRequest.model_validate({"request_id": uuid4(), "contract_version": version})


@pytest.mark.parametrize("extra", ["credential", "match_id", "player_slot", "rom_path"])
def test_gameplay_identity_and_paths_cannot_be_supplied_in_body(extra: str) -> None:
    body = {"request_id": uuid4(), "expected_revision": 0, "action": {"kind": "end_turn"}}
    body[extra] = "untrusted"
    with pytest.raises(ValidationError):
        GameplayCommandRequest.model_validate(body)


@pytest.mark.parametrize("revision", [True, -1, 1.5, "1", 1 << 53])
def test_invalid_revisions(revision: object) -> None:
    with pytest.raises(ValidationError):
        GameplayCommandRequest.model_validate(
            {"request_id": uuid4(), "expected_revision": revision, "action": {"kind": "end_turn"}}
        )


def test_movement_path_bound_and_stationary_action() -> None:
    body = {
        "request_id": uuid4(),
        "expected_revision": 0,
        "action": {"kind": "move_wait", "unit_id": "1", "path": []},
    }
    assert GameplayCommandRequest.model_validate(body).action.path == ()
    body["action"]["path"] = [{"x": 0, "y": 0}] * 4097
    with pytest.raises(ValidationError):
        GameplayCommandRequest.model_validate(body)


def test_close_has_no_expected_revision() -> None:
    assert CloseMatchRequest(request_id=uuid4())
    with pytest.raises(ValidationError):
        CloseMatchRequest.model_validate({"request_id": uuid4(), "expected_revision": 0})


def test_invitation_and_join_secrets_are_not_serialized() -> None:
    secret = "s" * 43
    issue = IssueInvitationRequest(request_id=uuid4(), invitation_token=secret)
    join = JoinSlotRequest(request_id=uuid4(), invitation_token=secret, display_name="  Player  ")
    assert issue.expires_in_seconds == 900
    assert join.display_name == "Player"
    for model in (issue, join):
        assert secret not in repr(model)
        assert "invitation_token" not in model.model_dump()
        assert secret not in model.model_dump_json()
        assert model.invitation_token.get_secret_value() == secret
    for seconds in (59, 3601, True):
        with pytest.raises(ValidationError):
            IssueInvitationRequest(
                request_id=uuid4(), invitation_token=secret, expires_in_seconds=seconds
            )
    for name in ("  ", "x" * 81):
        with pytest.raises(ValidationError):
            JoinSlotRequest(request_id=uuid4(), invitation_token=secret, display_name=name)


def test_invalid_secrets_and_extra_keys_are_redacted() -> None:
    sentinel = "SECRET_DO_NOT_EXPOSE"
    for data in (
        {"invitation_token": sentinel},
        {"invitation_token": "s" * 43, sentinel: sentinel},
    ):
        request_id = uuid4()
        with pytest.raises(ValidationError) as caught:
            IssueInvitationRequest.model_validate({"request_id": request_id, **data})
        # Pydantic still prints arbitrary extra-field names in raw exceptions.
        # Adapters must use the safe conversion rather than log/return those errors.
        result = validation_error(caught.value, request_id=request_id)
        assert sentinel not in result.response.model_dump_json()
        assert result.response.request_id == request_id
        assert result.status_code == 422


def test_typed_principals_and_revoked_slot() -> None:
    player = PlayerPrincipal(
        match_id=uuid4(), player_slot=PlayerSlot.SLOT_1, authorization_generation=3
    )
    assert TypeAdapter(Principal).validate_json(player.model_dump_json()) == player
    revoked = SlotAuthorization(
        match_id=player.match_id,
        player_slot=player.player_slot,
        status=SlotStatus.REVOKED,
        authorization_generation=4,
    )
    assert revoked.model_dump(mode="json")["status"] == "revoked"
    with pytest.raises(ValidationError):
        SlotAuthorization.model_validate(dict(revoked.model_dump(), display_name="old player"))


def test_summary_and_join_response_never_return_credentials() -> None:
    old = summary()
    old = old.model_copy(
        update={
            "slots": (
                PlayerSlotState(
                    slot=PlayerSlot.SLOT_1, status=SlotStatus.JOINED, display_name="Player"
                ),
                old.slots[1],
            )
        }
    )
    converted = summary_from_controller(old)
    joined = JoinSlotResponse(match=converted, player_slot=PlayerSlot.SLOT_1)
    assert "credential" not in joined.model_dump_json()
    assert converted.configuration == VERIFIED_CONFIGURATION
    with pytest.raises(ValidationError):
        JoinSlotResponse(match=converted, player_slot=PlayerSlot.SLOT_2)
    with pytest.raises(ValidationError):
        type(converted).model_validate(dict(converted.model_dump(), slots=[]))
    assert StateResponse(summary=converted, settled=True, observation=None)
    with pytest.raises(ValidationError):
        StateResponse(summary=converted, settled=False, observation=None)


def test_capabilities_do_not_claim_runtime_actions_by_default() -> None:
    unavailable = FeatureAvailability(
        name="events",
        implemented=False,
        available=False,
        verification="unverified",
        unavailable_reason="Not wired",
    )
    caps = CapabilitiesResponse(http_sse=unavailable, mcp_subscriptions=unavailable)
    assert caps.actions == ()
    assert caps.supported_game_contract_versions == (1,)
    assert caps.configuration_profiles[0].configuration == VERIFIED_CONFIGURATION
    with pytest.raises(ValidationError):
        FeatureAvailability(
            name="events", implemented=False, available=True, verification="unverified"
        )


def test_state_response_preserves_boundary_identity_and_revision(memory) -> None:
    current = summary_from_controller(summary())
    observation = MatchObservationTracker(current.match_id).commit_boundary(decode(memory))
    current = current.model_copy(
        update={"revision": observation.revision, "lifecycle": MatchLifecycle.PLAYABLE}
    )
    state = StateResponse(summary=current, settled=True, observation=observation)
    assert StateResponse.model_validate_json(state.model_dump_json()) == state
    for changed in (
        replace(observation, match_id=uuid4()),
        replace(observation, revision=observation.revision + 1),
    ):
        with pytest.raises(ValidationError):
            StateResponse(summary=current, settled=True, observation=changed)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_has_a_stable_status(code: ErrorCode) -> None:
    assert set(ERROR_HTTP_STATUS) == set(ErrorCode)
    result = map_error(ErrorBody(code=code, message="Safe service failure"))
    assert result.status_code == ERROR_HTTP_STATUS[code]
    assert result.headers["Cache-Control"] == "no-store"
    if code is ErrorCode.INVALID_CREDENTIAL:
        assert result.headers["WWW-Authenticate"] == "Bearer"
    if code is ErrorCode.COMMAND_CAPACITY:
        assert result.headers["Retry-After"] == "1"


@pytest.mark.parametrize("status", [400, 413, 415, 422])
def test_invalid_request_context_status(status: int) -> None:
    assert (
        map_error(
            ErrorBody(code=ErrorCode.INVALID_REQUEST, message="Invalid request"),
            request_failure_status=status,
        ).status_code
        == status
    )
    assert internal_error().response.error.message == "Internal server error"


def test_debug_bounds_before_queueing() -> None:
    common = {"request_id": uuid4(), "expected_revision": 0}
    assert DebugButtonsRequest(**common, frames=1, buttons=("a", "b"))
    for buttons in (("neutral", "a"), ("a", "a"), ()):
        with pytest.raises(ValidationError):
            DebugButtonsRequest(**common, frames=1, buttons=buttons)
    with pytest.raises(ValidationError):
        DebugButtonsRequest(**common, frames=601, buttons=("a",))
    assert DebugMemoryWriteRequest(**common, address=0, data=base64.b64encode(b"x" * 256).decode())
    for data in ("!!!!", "eA==\n", base64.b64encode(b"x" * 257).decode()):
        with pytest.raises(ValidationError):
            DebugMemoryWriteRequest(**common, address=0, data=data)
    with pytest.raises(ValidationError):
        DebugMemoryReadRequest(expected_revision=0, address=0xFFFFFFFF, length=2)
