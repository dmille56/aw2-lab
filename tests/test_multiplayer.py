"""Player count, team configuration, and authorization survive durable reloads."""

from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    CreateMatchRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
    configuration_from_controller,
    default_players,
)
from aw2_lab.api_validation import ContractValidationError, validate_configuration
from aw2_lab.authorization import AuthorizationError, AuthorizationService, Permission
from aw2_lab.match_contract import PlayerSlot


@pytest.mark.parametrize(
    "map_id,count,teams",
    [
        ("bean_island", 2, ("a", "b")),
        ("pyramid_cape", 3, ("a", "b", "b")),
        ("four_corners", 4, ("a", "a", "b", "b")),
    ],
)
def test_multiplayer_credentials_and_teams_survive_restart(tmp_path, map_id, count, teams):
    secret = SecretStr("o" * 43)
    auth = AuthorizationService(tmp_path / "auth.json", secret)
    players = tuple(
        p.model_copy(update={"team_id": team})
        for p, team in zip(default_players(count), teams, strict=True)
    )
    configuration = VERIFIED_CONFIGURATION.model_copy(update={"map_id": map_id, "players": players})
    match = auth.create_match(
        auth.authenticate(secret),
        CreateMatchRequest(request_id=uuid4(), configuration=configuration),
    )
    credentials = []
    for i, slot in enumerate(match.configuration.player_slots):
        invitation = SecretStr(str(i) * 43)
        credential = SecretStr(chr(97 + i) * 43)
        auth.issue_invitation(
            auth.authenticate(secret),
            match.match_id,
            slot,
            IssueInvitationRequest(request_id=uuid4(), invitation_token=invitation),
        )
        auth.claim_slot(
            match.match_id,
            slot,
            credential,
            JoinSlotRequest(
                request_id=uuid4(), invitation_token=invitation, display_name=f"Player {i + 1}"
            ),
        )
        credentials.append(credential)
    restarted = AuthorizationService(auth.path, secret)
    assert configuration_from_controller(restarted.summaries()[0].configuration) == configuration
    for slot, credential in zip(match.configuration.player_slots, credentials, strict=True):
        principal = restarted.authenticate(credential)
        assert principal.player_slot == slot
        restarted.authorize(principal, Permission.PLAY, match.match_id)
    if count < 4:
        with pytest.raises(AuthorizationError):
            restarted.issue_invitation(
                restarted.authenticate(secret),
                match.match_id,
                PlayerSlot.SLOT_4,
                IssueInvitationRequest(request_id=uuid4(), invitation_token=SecretStr("z" * 43)),
            )


@pytest.mark.parametrize(
    "players",
    [default_players(2), tuple(p.model_copy(update={"team_id": "a"}) for p in default_players(4))],
)
def test_incompatible_map_count_or_single_team_is_rejected(players):
    with pytest.raises(ContractValidationError):
        validate_configuration(
            VERIFIED_CONFIGURATION.model_copy(update={"map_id": "four_corners", "players": players})
        )


def test_rules_with_unrecognized_objects_fail_closed():
    from aw2_lab.cold_boot import ColdBootError, _locate_rule_selectors

    with pytest.raises(ColdBootError, match="signatures"):
        _locate_rule_selectors(bytes(0x1000))


def test_legacy_durable_configuration_defaults_to_two_slots():
    from aw2_lab.match_contract import FixedMatchConfiguration

    legacy = {"map_id": "bean_island", "player_1_co": "andy", "player_2_co": "max"}
    configuration = FixedMatchConfiguration.model_validate(legacy)
    assert configuration.player_slots == (PlayerSlot.SLOT_1, PlayerSlot.SLOT_2)
    assert configuration.team_ids == (0, 1)
