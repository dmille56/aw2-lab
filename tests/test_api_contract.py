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
    ConfigurationOptions,
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
    RuleConfiguration,
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
    ActivateSuperPowerAction,
    Capabilities,
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


@pytest.mark.parametrize("capture_limit", [None, *range(12, 28)])
def test_capture_limits_are_valid_but_only_off_is_executable(capture_limit: int | None) -> None:
    configuration = MatchConfiguration.model_validate(
        dict(profile(), rules=dict(profile()["rules"], capture_limit=capture_limit))
    )
    assert configuration.rules.capture_limit == capture_limit
    assert MatchConfiguration.model_validate_json(configuration.model_dump_json()) == configuration
    if capture_limit is None:
        assert configuration_to_controller(configuration) == FixedMatchConfiguration()
    else:
        with pytest.raises(ContractValidationError) as caught:
            configuration_to_controller(configuration)
        assert caught.value.body.code is ErrorCode.UNSUPPORTED_FEATURE


@pytest.mark.parametrize("capture_limit", [-1, 0, 1, 11, 28, 100, True, False, 12.0, "12", "off"])
def test_malformed_capture_limit_is_invalid(capture_limit: object) -> None:
    with pytest.raises(ValidationError) as caught:
        RuleConfiguration.model_validate(dict(profile()["rules"], capture_limit=capture_limit))
    error = validation_error(caught.value)
    assert error.response.error.code is ErrorCode.INVALID_REQUEST
    assert error.response.error.details["field_1"] == "capture_limit"


def test_capture_limit_is_required_and_legacy_storage_implies_off() -> None:
    rules = profile()["rules"]
    del rules["capture_limit"]
    with pytest.raises(ValidationError):
        RuleConfiguration.model_validate(rules)
    stored = FixedMatchConfiguration().model_dump_json()
    assert "capture_limit" not in stored
    legacy = FixedMatchConfiguration.model_validate_json(stored)
    converted = configuration_from_controller(legacy)
    assert converted.model_dump(mode="json")["rules"]["capture_limit"] is None
    assert configuration_to_controller(converted).model_dump_json() == stored


@pytest.mark.parametrize("day_limit", [None, 5, 20, 30, 99])
def test_day_limit_values_are_valid_but_only_thirty_is_executable(day_limit: int | None) -> None:
    configuration = MatchConfiguration.model_validate(
        dict(profile(), rules=dict(profile()["rules"], day_limit=day_limit))
    )
    assert configuration.rules.day_limit == day_limit
    assert MatchConfiguration.model_validate_json(configuration.model_dump_json()) == configuration
    if day_limit == 30:
        assert configuration_to_controller(configuration) == FixedMatchConfiguration()
    else:
        with pytest.raises(ContractValidationError) as caught:
            configuration_to_controller(configuration)
        assert caught.value.body.code is ErrorCode.UNSUPPORTED_FEATURE


@pytest.mark.parametrize("day_limit", [-1, 0, 1, 2, 3, 4, 100, True, False, 30.0, "30", "off"])
def test_malformed_day_limit_is_invalid(day_limit: object) -> None:
    with pytest.raises(ValidationError):
        RuleConfiguration.model_validate(dict(profile()["rules"], day_limit=day_limit))


@pytest.mark.parametrize("day_limit", [5, 20, 30, 99])
def test_stored_day_limits_translate_without_changing_their_values(day_limit: int) -> None:
    stored = FixedMatchConfiguration(rules=MatchRules(day_limit=day_limit)).model_dump_json()
    legacy = FixedMatchConfiguration.model_validate_json(stored)
    configuration = configuration_from_controller(legacy)
    assert configuration.rules.day_limit == day_limit
    assert legacy.model_dump_json() == stored
    if day_limit == 30:
        assert configuration_to_controller(configuration).model_dump_json() == stored
    else:
        with pytest.raises(ContractValidationError):
            configuration_to_controller(configuration)


@pytest.mark.parametrize("day_limit", [1, 2, 3, 4])
def test_legacy_short_day_limits_are_not_silently_changed(day_limit: int) -> None:
    legacy = FixedMatchConfiguration(rules=MatchRules(day_limit=day_limit))
    with pytest.raises(ValidationError):
        configuration_from_controller(legacy)
    assert legacy.rules.day_limit == day_limit


@pytest.mark.parametrize("weather", ["clear", "rain", "snow", "random"])
def test_weather_modes_are_valid_but_only_clear_is_executable(weather: str) -> None:
    data = profile()
    data["rules"]["weather"] = weather
    configuration = MatchConfiguration.model_validate(data)
    assert configuration.rules.weather == weather
    assert MatchConfiguration.model_validate_json(configuration.model_dump_json()) == configuration
    if weather == "clear":
        assert configuration_to_controller(configuration) == FixedMatchConfiguration()
    else:
        with pytest.raises(ContractValidationError) as caught:
            configuration_to_controller(configuration)
        assert caught.value.body.code is ErrorCode.UNSUPPORTED_FEATURE


@pytest.mark.parametrize("weather", ["Random", "storm", "", None, True, 0])
def test_malformed_weather_is_invalid(weather: object) -> None:
    with pytest.raises(ValidationError):
        RuleConfiguration.model_validate(dict(profile()["rules"], weather=weather))


def test_public_weather_rename_preserves_stored_controller_rules() -> None:
    # Persisted checkpoints and authorization ledgers keep their original shape.
    stored = FixedMatchConfiguration().model_dump(mode="json")
    assert stored["rules"]["starting_weather"] == "clear"
    assert "weather" not in stored["rules"]
    legacy = FixedMatchConfiguration.model_validate_json(
        FixedMatchConfiguration.model_validate(stored).model_dump_json()
    )
    converted = configuration_from_controller(legacy)
    assert converted.rules.weather == "clear"
    assert "starting_weather" not in converted.model_dump()["rules"]
    assert configuration_to_controller(converted).model_dump(mode="json") == stored
    rules = profile()["rules"]
    old_rules = dict(rules, starting_weather=rules["weather"])
    del old_rules["weather"]
    for data in (dict(rules, starting_weather="clear"), old_rules):
        with pytest.raises(ValidationError):
            RuleConfiguration.model_validate(data)


@pytest.mark.parametrize("change", ["fog", "co", "funds", "weather", "team", "cpu", "count"])
def test_known_unverified_combinations_are_unsupported(change: str) -> None:
    data = profile()
    if change == "fog":
        data["rules"]["fog"] = True
    elif change == "co":
        data["players"][0]["co_id"] = "sami"
    elif change == "funds":
        data["rules"]["income_per_property"] = 2000
    elif change == "weather":
        data["rules"]["weather"] = "rain"
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


def test_stationary_attack_action_contract() -> None:
    request = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {"kind": "attack", "unit_id": "1", "target": {"x": 1, "y": 2}},
        }
    )
    assert request.action.kind == "attack"
    assert "attack" in Capabilities().supported_actions


def test_normal_power_action_contract() -> None:
    request = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {"kind": "activate_normal_power"},
        }
    )
    assert request.action.kind == "activate_normal_power"
    assert "activate_normal_power" in Capabilities().supported_actions


def test_super_power_action_contract_is_distinct_and_supported() -> None:
    request = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {"kind": "activate_super_power"},
        }
    )
    assert isinstance(request.action, ActivateSuperPowerAction)
    assert "activate_super_power" in Capabilities().supported_actions
    assert "super_power_activation" not in Capabilities().unsupported_features


def test_transport_load_and_unload_action_contracts_are_bounded() -> None:
    load = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {
                "kind": "load",
                "unit_id": "cargo-1",
                "transport_id": "transport-1",
                "path": [],
            },
        }
    )
    assert load.action.kind == "load"
    unload = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {
                "kind": "unload",
                "transport_id": "transport-1",
                "path": [],
                "drops": [
                    {"unit_id": "cargo-1", "destination": {"x": 1, "y": 0}},
                    {"unit_id": "cargo-2", "destination": {"x": 0, "y": 1}},
                ],
            },
        }
    )
    assert unload.action.kind == "unload"
    assert "unload" in Capabilities().supported_actions
    body = unload.model_dump(mode="json")
    body["action"]["drops"].append({"unit_id": "cargo-3", "destination": {"x": 2, "y": 0}})
    with pytest.raises(ValidationError):
        GameplayCommandRequest.model_validate(body)


def test_join_action_requires_a_nonempty_bounded_path() -> None:
    body = {
        "request_id": uuid4(),
        "expected_revision": 0,
        "action": {"kind": "join", "unit_id": "1", "path": [{"x": 1, "y": 0}]},
    }
    request = GameplayCommandRequest.model_validate(body)
    assert request.action.kind == "join"
    assert "join" in Capabilities().supported_actions
    body["action"]["path"] = []
    with pytest.raises(ValidationError):
        GameplayCommandRequest.model_validate(body)


def test_supply_action_is_bounded_and_advertised_as_apc_resupply() -> None:
    body = {
        "request_id": uuid4(),
        "expected_revision": 0,
        "action": {"kind": "supply", "unit_id": "apc-1", "path": []},
    }
    request = GameplayCommandRequest.model_validate(body)
    assert request.action.kind == "supply"
    assert "supply" in Capabilities().supported_actions
    assert "apc_resupply" in Capabilities().supported_features
    assert "resupply" not in Capabilities().unsupported_features


@pytest.mark.parametrize(
    ("kind", "expected_feature"),
    [("dive", "diving_and_surfacing"), ("rise", "diving_and_surfacing")],
)
def test_submarine_mode_actions_are_bounded_and_advertised(
    kind: str, expected_feature: str
) -> None:
    request = GameplayCommandRequest.model_validate(
        {
            "request_id": uuid4(),
            "expected_revision": 0,
            "action": {"kind": kind, "unit_id": "sub-1", "path": []},
        }
    )
    assert request.action.kind == kind
    assert kind in Capabilities().supported_actions
    assert expected_feature in Capabilities().supported_features
    assert expected_feature not in Capabilities().unsupported_features


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
    assert caps.supported_match_observation_schema_versions == (1,)
    assert caps.supported_game_state_schema_versions == (5,)
    assert not caps.mcp_resources.implemented
    assert not caps.mcp_resources.available
    assert not caps.mcp_subscriptions.available
    assert caps.mcp_compatibility.endpoint == "/mcp"
    assert caps.configuration_profiles[0].configuration == VERIFIED_CONFIGURATION
    for field in ("supported_player_counts", "supported_control_modes"):
        for values in ([], [caps.model_dump()[field][0]] * 2):
            with pytest.raises(ValidationError):
                CapabilitiesResponse.model_validate(dict(caps.model_dump(), **{field: values}))
    with pytest.raises(ValidationError):
        FeatureAvailability(
            name="events", implemented=False, available=True, verification="unverified"
        )


@pytest.mark.parametrize("field", ["players", "rules"])
def test_capabilities_cannot_advertise_unverified_configuration_options(field: str) -> None:
    options = ConfigurationOptions().model_dump(mode="json")
    if field == "players":
        options[field][0]["co_id"] = "sami"
    else:
        options[field]["fog"] = True
    with pytest.raises(ValidationError, match="Only verified"):
        ConfigurationOptions.model_validate(options)


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


def test_income_option_is_not_mislabeled_as_starting_cash() -> None:
    configuration = configuration_from_controller(FixedMatchConfiguration())
    rules = configuration.model_dump(mode="json")["rules"]
    assert rules["income_per_property"] == 1000
    assert "starting_funds" not in rules
    rules["starting_funds"] = rules.pop("income_per_property")
    with pytest.raises(ValidationError):
        MatchConfiguration.model_validate(dict(configuration.model_dump(mode="json"), rules=rules))
