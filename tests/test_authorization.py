"""Durability, scoped permissions, invitations, and revocation without a ROM."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from aw2_lab.api_contract import (
    VERIFIED_CONFIGURATION,
    CreateMatchRequest,
    IssueInvitationRequest,
    JoinSlotRequest,
)
from aw2_lab.authorization import (
    AuthorizationError,
    AuthorizationService,
    Permission,
    load_operator_secret,
)
from aw2_lab.match_contract import ErrorCode, MatchLifecycle, PlayerSlot, SlotStatus


def token(character):
    return SecretStr(character * 43)


@pytest.fixture
def auth(tmp_path):
    return AuthorizationService(tmp_path / "authorization.json", token("o"))


def operator(auth):
    return auth.authenticate(token("o"))


def create(auth):
    return auth.create_match(operator(auth), CreateMatchRequest(request_id=uuid4()))


def invite(auth, match_id, slot=PlayerSlot.SLOT_1, *, secret=None, request_id=None):
    request = IssueInvitationRequest(
        request_id=request_id or uuid4(), invitation_token=secret or token("i")
    )
    return auth.issue_invitation(operator(auth), match_id, slot, request), request


def claim(auth, match_id, slot=PlayerSlot.SLOT_1, *, invitation=None, credential=None):
    invitation = invitation or token("i")
    request = JoinSlotRequest(
        request_id=uuid4(), display_name=" Player ", invitation_token=invitation
    )
    credential = credential or token("p")
    return auth.claim_slot(match_id, slot, credential, request), request


def assert_code(code, function):
    with pytest.raises(AuthorizationError) as caught:
        function()
    assert caught.value.body.code is code


def test_create_is_durable_retry_safe_and_keeps_default_resolution(auth):
    request = CreateMatchRequest(request_id=uuid4())
    first = auth.create_match(operator(auth), request)
    assert auth.create_match(operator(auth), request) == first
    restarted = AuthorizationService(auth.path, token("o"))
    assert restarted.create_match(operator(restarted), request) == first
    assert_code(ErrorCode.ACTIVE_MATCH_EXISTS, lambda: create(restarted))
    changed = request.model_copy(update={"configuration": VERIFIED_CONFIGURATION})
    assert_code(
        ErrorCode.REQUEST_ID_CONFLICT, lambda: restarted.create_match(operator(restarted), changed)
    )


def test_claim_retry_after_expiry_and_restart_has_no_secret_echo(tmp_path):
    now = [datetime(2026, 10, 30, tzinfo=UTC)]
    auth = AuthorizationService(tmp_path / "authorization.json", token("o"), clock=lambda: now[0])
    match = create(auth)
    reference, request = invite(auth, match.match_id)
    player, join = claim(auth, match.match_id)
    assert reference.expires_at == now[0] + timedelta(minutes=15)
    now[0] += timedelta(hours=2)
    restarted = AuthorizationService(auth.path, token("o"), clock=lambda: now[0])
    assert (
        restarted.issue_invitation(operator(restarted), match.match_id, PlayerSlot.SLOT_1, request)
        == reference
    )
    assert restarted.claim_slot(match.match_id, PlayerSlot.SLOT_1, token("p"), join) == player
    assert restarted.authenticate(token("p")) == player
    for secret in (token("o"), token("i"), token("p")):
        assert secret.get_secret_value() not in auth.path.read_text()
    assert auth.path.stat().st_mode & 0o077 == 0
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: restarted.claim_slot(match.match_id, PlayerSlot.SLOT_1, token("z"), join),
    )
    assert_code(
        ErrorCode.REQUEST_ID_CONFLICT,
        lambda: restarted.claim_slot(
            match.match_id,
            PlayerSlot.SLOT_1,
            token("p"),
            join.model_copy(update={"display_name": "Changed"}),
        ),
    )


def test_expired_replaced_and_consumed_invitations(auth):
    match = create(auth)
    old, _ = invite(auth, match.match_id)
    _, _ = invite(auth, match.match_id, secret=token("j"))
    assert_code(ErrorCode.INVALID_INVITATION, lambda: claim(auth, match.match_id))
    player, _ = claim(auth, match.match_id, invitation=token("j"))
    assert player.player_slot is PlayerSlot.SLOT_1
    assert_code(
        ErrorCode.INVALID_INVITATION,
        lambda: claim(auth, match.match_id, invitation=token("j"), credential=token("z")),
    )
    other = create_expiry_match(auth, match)
    assert other == old.match_id


def create_expiry_match(auth, match):
    auth.record_boundary(match.model_copy(update={"lifecycle": MatchLifecycle.CLOSED}))
    new = create(auth)
    reference, _ = invite(auth, new.match_id, secret=token("k"))
    auth._clock = lambda: reference.expires_at
    assert_code(
        ErrorCode.INVALID_INVITATION, lambda: claim(auth, new.match_id, invitation=token("k"))
    )
    return match.match_id


def test_independent_secrets_and_wrong_slot_claim(auth):
    match = create(auth)
    invite(auth, match.match_id)
    assert_code(
        ErrorCode.INVALID_CREDENTIAL, lambda: claim(auth, match.match_id, credential=token("i"))
    )
    assert_code(
        ErrorCode.INVALID_CREDENTIAL, lambda: claim(auth, match.match_id, credential=token("o"))
    )
    assert_code(
        ErrorCode.INVALID_INVITATION, lambda: claim(auth, match.match_id, PlayerSlot.SLOT_2)
    )
    claim(auth, match.match_id)
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: invite(auth, match.match_id, PlayerSlot.SLOT_2, secret=token("p")),
    )


def test_revoke_is_durable_invalidates_cached_claim_and_does_not_revoke_replacement(auth):
    match = create(auth)
    invite(auth, match.match_id)
    player, join = claim(auth, match.match_id)
    notified = []
    unsubscribe = auth.watch(player, lambda: notified.append(True))
    request_id = uuid4()
    revoked = auth.revoke_slot(operator(auth), match.match_id, PlayerSlot.SLOT_1, request_id)
    assert revoked.authorization_generation == 1
    assert notified == [True]
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: auth.authorize(player, Permission.READ, match.match_id),
    )
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: auth.authenticate(token("p")))
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: auth.claim_slot(match.match_id, PlayerSlot.SLOT_1, token("p"), join),
    )
    invite(auth, match.match_id, secret=token("j"))
    replacement, _ = claim(auth, match.match_id, invitation=token("j"), credential=token("q"))
    assert (
        auth.revoke_slot(operator(auth), match.match_id, PlayerSlot.SLOT_1, request_id) == revoked
    )
    auth.authorize(replacement, Permission.READ, match.match_id)
    unsubscribe()
    restarted = AuthorizationService(auth.path, token("o"))
    assert restarted.authenticate(token("q")) == replacement
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: restarted.authenticate(token("p")))


def test_revoke_after_start_does_not_change_game_revision_or_allow_rejoin(auth):
    match = create(auth)
    invite(auth, match.match_id)
    player, _ = claim(auth, match.match_id)
    before = auth.overlay(match).model_copy(
        update={"revision": 7, "lifecycle": MatchLifecycle.PLAYABLE}
    )
    auth.record_boundary(before)
    auth.revoke_slot(operator(auth), match.match_id, PlayerSlot.SLOT_1, uuid4())
    after = auth.overlay(before)
    assert (after.revision, after.lifecycle) == (7, MatchLifecycle.PLAYABLE)
    assert after.slots[0].status is SlotStatus.REVOKED
    assert_code(ErrorCode.SLOT_UNAVAILABLE, lambda: invite(auth, match.match_id, secret=token("j")))
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: auth.authorize(player, Permission.READ, match.match_id),
    )


@pytest.mark.parametrize("permission", list(Permission))
def test_operator_and_player_permission_matrix(auth, permission):
    match = create(auth)
    invite(auth, match.match_id)
    player, _ = claim(auth, match.match_id)
    if permission in {Permission.READ, Permission.PLAY, Permission.CHECKPOINT_CREATE}:
        auth.authorize(player, permission, match.match_id)
    else:
        assert_code(
            ErrorCode.PERMISSION_DENIED, lambda: auth.authorize(player, permission, match.match_id)
        )
    if permission is Permission.PLAY:
        assert_code(
            ErrorCode.PERMISSION_DENIED,
            lambda: auth.authorize(operator(auth), permission, match.match_id),
        )
    elif permission is Permission.DEBUG:
        assert_code(
            ErrorCode.UNSUPPORTED_FEATURE,
            lambda: auth.authorize(operator(auth), permission, match.match_id),
        )
    else:
        auth.authorize(operator(auth), permission, match.match_id)
    assert_code(ErrorCode.PERMISSION_DENIED, lambda: auth.authorize(player, permission, uuid4()))


def test_closed_match_remains_readable_but_not_mutable(auth):
    match = create(auth)
    invite(auth, match.match_id)
    player, _ = claim(auth, match.match_id)
    invite(auth, match.match_id, PlayerSlot.SLOT_2, secret=token("j"))
    auth.record_boundary(
        auth.overlay(match).model_copy(update={"lifecycle": MatchLifecycle.CLOSED})
    )
    auth.authorize(player, Permission.READ, match.match_id)
    assert_code(
        ErrorCode.MATCH_CLOSED, lambda: auth.authorize(player, Permission.PLAY, match.match_id)
    )
    assert_code(
        ErrorCode.SLOT_UNAVAILABLE,
        lambda: claim(
            auth, match.match_id, PlayerSlot.SLOT_2, invitation=token("j"), credential=token("q")
        ),
    )
    auth.revoke_slot(operator(auth), match.match_id, PlayerSlot.SLOT_1, uuid4())
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: auth.authorize(player, Permission.READ, match.match_id),
    )


def test_metadata_request_ids_conflict_across_operations(auth):
    request = CreateMatchRequest(request_id=uuid4())
    match = auth.create_match(operator(auth), request)
    assert_code(
        ErrorCode.REQUEST_ID_CONFLICT,
        lambda: invite(auth, match.match_id, request_id=request.request_id),
    )


def test_rotation_invalidates_old_operator_token_and_principal(auth):
    old = operator(auth)
    restarted = AuthorizationService(auth.path, token("n"))
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: restarted.authenticate(token("o")))
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: restarted.authorize(old, Permission.ADMIN))
    restarted.authorize(restarted.authenticate(token("n")), Permission.ADMIN)


def test_missing_and_corrupt_ledger_fail_checkpoint_adoption(auth):
    match = create(auth)
    assert_code(
        ErrorCode.RECOVERY_REQUIRED,
        lambda: auth.overlay(match.model_copy(update={"match_id": uuid4()}), recovering=True),
    )
    auth.path.write_text('{"schema_version":999}')
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: AuthorizationService(auth.path, token("o")))


def test_inconsistent_ledger_fails_closed(auth):
    create(auth)
    state = json.loads(auth.path.read_text())
    state["matches"][next(iter(state["matches"]))]["slots"]["slot_1"]["status"] = "joined"
    auth.path.write_text(json.dumps(state))
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: AuthorizationService(auth.path, token("o")))


def test_failed_write_never_acknowledges_claim_or_keeps_stale_authorization(auth, monkeypatch):
    match = create(auth)
    invite(auth, match.match_id)
    original = auth.path.read_bytes()

    def fail(*args):
        raise OSError("injected disk failure")

    monkeypatch.setattr(os, "replace", fail)
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: claim(auth, match.match_id))
    assert auth.path.read_bytes() == original
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: auth.authenticate(token("o")))
    restarted = AuthorizationService(auth.path, token("o"))
    assert_code(ErrorCode.INVALID_CREDENTIAL, lambda: restarted.authenticate(token("p")))


def test_operator_file_is_private_bounded_and_never_echoed(tmp_path):
    path = tmp_path / "operator-secret"
    secret = token("o").get_secret_value()
    path.write_text(secret + "\n")
    path.chmod(0o600)
    assert load_operator_secret(path).get_secret_value() == secret
    path.chmod(0o644)
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: load_operator_secret(path))
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: load_operator_secret(link))
    for value in ("short", "x" * 129, "x" * 40 + "\n\n"):
        path.write_text(value)
        with pytest.raises(AuthorizationError) as caught:
            load_operator_secret(path)
        assert value not in str(caught.value)


def test_corrupt_retry_cannot_be_adopted(auth):
    match = create(auth)
    _, request = invite(auth, match.match_id)
    state = json.loads(auth.path.read_text())
    state["requests"][str(request.request_id)]["invitation_id"] = None
    auth.path.write_text(json.dumps(state))
    assert_code(ErrorCode.STORAGE_UNAVAILABLE, lambda: AuthorizationService(auth.path, token("o")))


def test_revoked_secret_cannot_be_assigned_to_a_new_claim(auth):
    match = create(auth)
    invite(auth, match.match_id)
    claim(auth, match.match_id)
    auth.revoke_slot(operator(auth), match.match_id, PlayerSlot.SLOT_1, uuid4())
    invite(auth, match.match_id, secret=token("j"))
    assert_code(
        ErrorCode.INVALID_CREDENTIAL,
        lambda: claim(auth, match.match_id, invitation=token("j"), credential=token("p")),
    )
