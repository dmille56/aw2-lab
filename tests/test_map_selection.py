"""Map choices remain intact across public validation and durable match metadata."""

from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    CapabilitiesResponse,
    ConfigurationProfile,
    CreateMatchRequest,
    FeatureAvailability,
    configuration_from_controller,
)
from aw2_lab.api_validation import configuration_to_controller, validate_configuration
from aw2_lab.authorization import AuthorizationError, AuthorizationService
from aw2_lab.map_catalog import MAP_IDS
from aw2_lab.match_contract import ErrorCode


@pytest.mark.parametrize("map_id", MAP_IDS)
def test_selected_map_survives_durable_creation_and_retries(map_id, tmp_path):
    secret = SecretStr("o" * 43)
    auth = AuthorizationService(tmp_path / "auth.json", secret)
    configuration = VERIFIED_CONFIGURATION.model_copy(update={"map_id": map_id})
    request = CreateMatchRequest(request_id=uuid4(), configuration=configuration)
    created = auth.create_match(auth.authenticate(secret), request)
    assert created.configuration.map_id == map_id
    assert configuration_from_controller(created.configuration) == configuration
    assert configuration_to_controller(configuration) == created.configuration
    restarted = AuthorizationService(auth.path, secret)
    assert restarted.create_match(restarted.authenticate(secret), request) == created

    # A different map is a different retry payload, even with the same request ID.
    other_id = next(value for value in MAP_IDS if value != map_id)
    with pytest.raises(AuthorizationError) as caught:
        restarted.create_match(
            restarted.authenticate(secret),
            request.model_copy(
                update={"configuration": configuration.model_copy(update={"map_id": other_id})}
            ),
        )
    assert caught.value.body.code is ErrorCode.REQUEST_ID_CONFLICT


def test_profile_identifier_must_match_its_map():
    with pytest.raises(ValidationError):
        ConfigurationProfile(
            profile_id="bean_island_v1",
            configuration=VERIFIED_CONFIGURATION.model_copy(update={"map_id": "crater_isle"}),
        )


def test_advertised_profiles_and_options_describe_the_same_supported_maps():
    unavailable = FeatureAvailability(
        name="events",
        implemented=False,
        available=False,
        verification="unverified",
        unavailable_reason="Not needed for map selection",
    )
    capabilities = CapabilitiesResponse(http_sse=unavailable, mcp_subscriptions=unavailable)
    profiles = capabilities.configuration_profiles
    assert (
        tuple(p.configuration.map_id for p in profiles)
        == capabilities.configuration_options.map_ids
    )
    assert len(profiles) == len(MAP_IDS) == 17
    assert profiles[0].profile_id == capabilities.default_profile_id
    for profile in profiles:
        assert validate_configuration(profile.configuration) == profile.configuration
