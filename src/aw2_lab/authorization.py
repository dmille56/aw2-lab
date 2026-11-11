"""Durable setup and authorization ledger, independent of emulator checkpoints.

One server owns this ledger. Mutations use copy-on-write plus fsync/atomic replace;
no successful metadata response precedes persistence. Raw tokens are never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from aw2_lab.api_contract import (
    CreateMatchRequest,
    InvitationReference,
    IssueInvitationRequest,
    JoinSlotRequest,
    OperatorPrincipal,
    PlayerPrincipal,
    Principal,
    SlotAuthorization,
    configuration_from_controller,
)
from aw2_lab.api_validation import (
    configuration_to_controller,
    resolve_configuration,
    validate_configuration,
)
from aw2_lab.match_contract import (
    CheckpointReference,
    ErrorBody,
    ErrorCode,
    MatchLifecycle,
    MatchSummary,
    PlayerSlot,
    PlayerSlotState,
    SlotStatus,
)
from aw2_lab.storage import resolve_storage_root


class AuthorizationError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.body = ErrorBody(code=code, message=message)


class Permission(StrEnum):
    ADMIN = "admin"
    READ = "read"
    PLAY = "play"
    CHECKPOINT_CREATE = "checkpoint_create"
    ARCHIVE = "archive"
    DEBUG = "debug"


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Slot(_PrivateModel):
    generation: int = Field(default=0, ge=0, strict=True)
    status: SlotStatus = SlotStatus.OPEN
    credential_hash: Digest | None = None
    display_name: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> _Slot:
        if (self.status is SlotStatus.JOINED) != (self.credential_hash is not None):
            raise ValueError("Slot status and verifier disagree")
        if self.status is not SlotStatus.JOINED and self.display_name is not None:
            raise ValueError("Unclaimed slots cannot have display names")
        return self


class _Invitation(_PrivateModel):
    reference: InvitationReference
    token_hash: Digest
    generation: int = Field(ge=0, strict=True)
    consumed: bool = False
    invalidated: bool = False


class _Match(_PrivateModel):
    summary: MatchSummary
    slots: dict[PlayerSlot, _Slot]
    invitations: dict[UUID, _Invitation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self) -> _Match:
        validate_configuration(configuration_from_controller(self.summary.configuration))
        if set(self.slots) != set(self.summary.configuration.player_slots):
            raise ValueError("Authorization slots are incomplete")
        for public in self.summary.slots:
            private = self.slots[public.slot]
            if (public.status, public.display_name) != (private.status, private.display_name):
                raise ValueError("Public and private slot metadata disagree")
        for key, invitation in self.invitations.items():
            if (
                invitation.reference.invitation_id != key
                or invitation.reference.match_id != self.summary.match_id
            ):
                raise ValueError("Invitation identity disagrees")
            if invitation.generation > self.slots[invitation.reference.player_slot].generation:
                raise ValueError("Invitation authorization generation is invalid")
        return self


class _Retry(_PrivateModel):
    operation: Literal["create", "invite", "join", "revoke", "checkpoint_import"]
    fingerprint: Digest
    match_id: UUID
    slot: PlayerSlot | None = None
    generation: int | None = None
    credential_hash: Digest | None = None
    invitation_id: UUID | None = None
    authorization: SlotAuthorization | None = None
    checkpoint: CheckpointReference | None = None

    @model_validator(mode="after")
    def consistent(self) -> _Retry:
        if self.operation in {"create", "checkpoint_import"}:
            if any(
                value is not None
                for value in (
                    self.slot,
                    self.generation,
                    self.credential_hash,
                    self.invitation_id,
                    self.authorization,
                )
            ):
                raise ValueError("Creation retry cannot contain slot metadata")
        elif self.slot is None or self.generation is None or self.generation < 0:
            raise ValueError("Slot retry identity is incomplete")
        if self.operation == "checkpoint_import":
            if self.checkpoint is None or self.checkpoint.match_id != self.match_id:
                raise ValueError("Import retry checkpoint is missing or inconsistent")
        elif self.checkpoint is not None:
            raise ValueError("Only import retries can contain checkpoint metadata")
        if self.operation == "invite" and self.invitation_id is None:
            raise ValueError("Invitation retry reference is missing")
        if self.operation == "join" and self.credential_hash is None:
            raise ValueError("Claim retry verifier is missing")
        if self.operation == "revoke" and (
            self.authorization is None
            or self.authorization.match_id != self.match_id
            or self.authorization.player_slot != self.slot
            or self.authorization.authorization_generation != self.generation
            or self.authorization.status is not SlotStatus.REVOKED
        ):
            raise ValueError("Revocation retry reference is inconsistent")
        return self


class _Ledger(_PrivateModel):
    schema_version: Literal[1] = 1
    matches: dict[UUID, _Match] = Field(default_factory=dict)
    requests: dict[UUID, _Retry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self) -> _Ledger:
        if any(key != record.summary.match_id for key, record in self.matches.items()):
            raise ValueError("Ledger match identity disagrees")
        if (
            sum(
                record.summary.lifecycle is not MatchLifecycle.CLOSED
                for record in self.matches.values()
            )
            > 1
        ):
            raise ValueError("Ledger has multiple active matches")
        for retry in self.requests.values():
            match = self.matches.get(retry.match_id)
            if match is None:
                raise ValueError("Retry refers to an unknown match")
            if (
                retry.slot is not None
                and retry.generation is not None
                and retry.generation > match.slots[retry.slot].generation
            ):
                raise ValueError("Retry generation is invalid")
            if retry.invitation_id is not None and retry.invitation_id not in match.invitations:
                raise ValueError("Retry invitation is missing")
        return self


def _digest(token: SecretStr) -> str:
    value = token.get_secret_value()
    if not 32 <= len(value) <= 128:
        raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_operator_secret(path: Path) -> SecretStr:
    """Load a bounded owner-only regular file, rejecting symlinks and Nix sources."""
    try:
        resolved = path.expanduser().resolve()
        resolve_storage_root(resolved.parent)
        if resolved.is_relative_to("/nix/store"):
            raise ValueError("Immutable secret source")
        descriptor = os.open(path.expanduser(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Not a regular file")
            if os.name == "posix" and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
                raise ValueError("Secret file permissions are not private")
            raw = source.read(131)
        value = raw.removesuffix(b"\n").decode("ascii")
        if not 32 <= len(value) <= 128 or any(character.isspace() for character in value):
            raise ValueError("Invalid token")
        return SecretStr(value)
    except OSError, ValueError, UnicodeError:
        raise AuthorizationError(
            ErrorCode.STORAGE_UNAVAILABLE, "Cannot load private operator credential file"
        ) from None


T = TypeVar("T")


class AuthorizationService:
    def __init__(
        self,
        path: Path,
        operator_token: SecretStr,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        debug_enabled: bool = False,
    ) -> None:
        self.path = path
        self._operator_hash = _digest(operator_token)
        self._operator_generation = secrets.randbits(52)
        self._clock = clock
        self.debug_enabled = debug_enabled
        self._lock = threading.RLock()
        self._failed = False
        self._changed: dict[tuple[UUID, PlayerSlot], set[Callable[[], None]]] = {}
        self._state = self._load()
        if any(
            self._operator_hash == retry.credential_hash for retry in self._state.requests.values()
        ) or any(
            self._operator_hash == invite.token_hash
            for match in self._state.matches.values()
            for invite in match.invitations.values()
        ):
            raise AuthorizationError(
                ErrorCode.STORAGE_UNAVAILABLE,
                "Operator credential conflicts with an existing secret",
            )

    def _load(self) -> _Ledger:
        try:
            if not self.path.exists():
                return _Ledger()
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Not a regular ledger")
            if os.name == "posix" and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
                raise ValueError("Ledger permissions are not private")
            if metadata.st_size > 16 * 1024 * 1024:
                raise ValueError("Ledger exceeds size limit")
            return _Ledger.model_validate_json(self.path.read_bytes())
        except OSError, ValueError, ValidationError:
            raise AuthorizationError(
                ErrorCode.STORAGE_UNAVAILABLE, "Authorization ledger is unavailable or corrupt"
            ) from None

    def _healthy(self) -> None:
        if self._failed:
            raise AuthorizationError(
                ErrorCode.STORAGE_UNAVAILABLE, "Authorization ledger requires restart"
            )

    def _transaction(self, operation: Callable[[_Ledger], T]) -> T:
        with self._lock:
            self._healthy()
            candidate = self._state.model_copy(deep=True)
            result = operation(candidate)
            # Revalidate cross-record invariants before committing the candidate.
            candidate = _Ledger.model_validate(candidate.model_dump())
            encoded = candidate.model_dump_json().encode()
            if len(encoded) > 16 * 1024 * 1024:
                raise AuthorizationError(
                    ErrorCode.STORAGE_UNAVAILABLE, "Authorization ledger capacity reached"
                )
            temporary: str | None = None
            try:
                missing = []
                ancestor = self.path.parent
                while not ancestor.exists():
                    missing.append(ancestor)
                    ancestor = ancestor.parent
                for directory in reversed(missing):
                    directory.mkdir(mode=0o700)
                    _sync_directory(directory.parent)
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".authorization-", dir=self.path.parent
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
                temporary = None
                _sync_directory(self.path.parent)
            except OSError:
                # An uncertain rename/fsync must never leave stale permissions usable.
                self._failed = True
                raise AuthorizationError(
                    ErrorCode.STORAGE_UNAVAILABLE, "Cannot persist authorization metadata"
                ) from None
            finally:
                if temporary is not None:
                    os.unlink(temporary)
            self._state = candidate
            return result

    def authenticate(self, credential: SecretStr) -> Principal:
        digest = _digest(credential)
        with self._lock:
            self._healthy()
            if hmac.compare_digest(digest, self._operator_hash):
                return OperatorPrincipal(authorization_generation=self._operator_generation)
            for match in self._state.matches.values():
                for slot, value in match.slots.items():
                    if value.credential_hash and hmac.compare_digest(digest, value.credential_hash):
                        return PlayerPrincipal(
                            match_id=match.summary.match_id,
                            player_slot=slot,
                            authorization_generation=value.generation,
                        )
        raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")

    def authorize(
        self, principal: Principal, permission: Permission, match_id: UUID | None = None
    ) -> None:
        with self._lock:
            self._healthy()
            if isinstance(principal, OperatorPrincipal):
                if principal.authorization_generation != self._operator_generation:
                    raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
                if permission is Permission.PLAY:
                    raise AuthorizationError(
                        ErrorCode.PERMISSION_DENIED, "Gameplay requires a player credential"
                    )
                if permission is Permission.DEBUG and not self.debug_enabled:
                    raise AuthorizationError(
                        ErrorCode.UNSUPPORTED_FEATURE, "Debug access is disabled"
                    )
                return
            match = self._match(self._state, principal.match_id)
            if principal.player_slot not in match.slots:
                raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
            slot = match.slots[principal.player_slot]
            if (
                slot.status is not SlotStatus.JOINED
                or slot.generation != principal.authorization_generation
            ):
                raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
            if match_id != principal.match_id or permission not in {
                Permission.READ,
                Permission.PLAY,
                Permission.CHECKPOINT_CREATE,
            }:
                raise AuthorizationError(ErrorCode.PERMISSION_DENIED, "Permission denied")
            if (
                permission is not Permission.READ
                and match.summary.lifecycle is MatchLifecycle.CLOSED
            ):
                raise AuthorizationError(ErrorCode.MATCH_CLOSED, "The match is closed")

    def watch(self, principal: Principal, callback: Callable[[], None]) -> Callable[[], None]:
        """Register revocation wakeup for future subscriptions/waits; delivery still rechecks."""
        with self._lock:
            self.authorize(principal, Permission.READ, getattr(principal, "match_id", None))
            if not isinstance(principal, PlayerPrincipal):
                return lambda: None
            key = (principal.match_id, principal.player_slot)
            callbacks = self._changed.setdefault(key, set())
            callbacks.add(callback)

            def remove() -> None:
                with self._lock:
                    callbacks.discard(callback)

            return remove

    @staticmethod
    def _match(state: _Ledger, match_id: UUID) -> _Match:
        match = state.matches.get(match_id)
        if match is None:
            raise AuthorizationError(ErrorCode.MATCH_NOT_FOUND, "Match was not found")
        return match

    @staticmethod
    def _fingerprint(
        operation: str, match_id: UUID | None, slot: PlayerSlot | None, payload: object
    ) -> str:
        encoded = json.dumps(
            [operation, str(match_id), slot, payload], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _retry(state: _Ledger, request_id: UUID, fingerprint: str) -> _Retry | None:
        retry = state.requests.get(request_id)
        if retry and retry.fingerprint != fingerprint:
            raise AuthorizationError(
                ErrorCode.REQUEST_ID_CONFLICT, "Request ID was already used with different data"
            )
        return retry

    def create_match(self, principal: Principal, request: CreateMatchRequest) -> MatchSummary:
        self.authorize(principal, Permission.ADMIN)
        # Preserve omission in the fingerprint; resolve the default only on first creation.
        fingerprint = self._fingerprint("create", None, None, request.model_dump(mode="json"))
        with self._lock:
            retry = self._retry(self._state, request.request_id, fingerprint)
            if retry:
                return self._match(self._state, retry.match_id).summary
        configuration = configuration_to_controller(resolve_configuration(request))

        def create(state: _Ledger) -> MatchSummary:
            retry = self._retry(state, request.request_id, fingerprint)
            if retry:
                return self._match(state, retry.match_id).summary
            if any(
                match.summary.lifecycle is not MatchLifecycle.CLOSED
                for match in state.matches.values()
            ):
                raise AuthorizationError(ErrorCode.ACTIVE_MATCH_EXISTS, "A match is already active")
            summary = MatchSummary(
                match_id=uuid4(),
                revision=0,
                lifecycle=MatchLifecycle.SETUP,
                configuration=configuration,
                slots=tuple(
                    PlayerSlotState(slot=slot, status=SlotStatus.OPEN)
                    for slot in configuration.player_slots
                ),
                created_at=self._clock(),
            )
            state.matches[summary.match_id] = _Match(
                summary=summary, slots={slot: _Slot() for slot in configuration.player_slots}
            )
            state.requests[request.request_id] = _Retry(
                operation="create", fingerprint=fingerprint, match_id=summary.match_id
            )
            return summary

        return self._transaction(create)

    def issue_invitation(
        self,
        principal: Principal,
        match_id: UUID,
        slot: PlayerSlot,
        request: IssueInvitationRequest,
    ) -> InvitationReference:
        self.authorize(principal, Permission.ADMIN, match_id)
        token_hash = _digest(request.invitation_token)
        fingerprint = self._fingerprint(
            "invite",
            match_id,
            slot,
            {"token_hash": token_hash, "seconds": request.expires_in_seconds},
        )

        def issue(state: _Ledger) -> InvitationReference:
            match = self._match(state, match_id)
            if slot not in match.slots:
                raise AuthorizationError(
                    ErrorCode.SLOT_UNAVAILABLE, "Player slot is not configured"
                )
            retry = self._retry(state, request.request_id, fingerprint)
            if retry:
                assert retry.invitation_id is not None
                return match.invitations[retry.invitation_id].reference
            self._setup(match)
            if match.slots[slot].status is SlotStatus.JOINED:
                raise AuthorizationError(ErrorCode.SLOT_UNAVAILABLE, "The player slot is taken")
            self._distinct(state, token_hash)
            for invitation in match.invitations.values():
                if invitation.reference.player_slot is slot:
                    invitation.invalidated = True
            reference = InvitationReference(
                invitation_id=uuid4(),
                match_id=match_id,
                player_slot=slot,
                expires_at=self._clock() + timedelta(seconds=request.expires_in_seconds),
            )
            match.invitations[reference.invitation_id] = _Invitation(
                reference=reference, token_hash=token_hash, generation=match.slots[slot].generation
            )
            state.requests[request.request_id] = _Retry(
                operation="invite",
                fingerprint=fingerprint,
                match_id=match_id,
                slot=slot,
                generation=match.slots[slot].generation,
                invitation_id=reference.invitation_id,
            )
            return reference

        return self._transaction(issue)

    def claim_slot(
        self, match_id: UUID, slot: PlayerSlot, credential: SecretStr, request: JoinSlotRequest
    ) -> PlayerPrincipal:
        credential_hash = _digest(credential)
        invitation_hash = _digest(request.invitation_token)
        fingerprint = self._fingerprint(
            "join",
            match_id,
            slot,
            {
                "display_name": request.display_name,
                "invitation_hash": invitation_hash,
                "credential_hash": credential_hash,
            },
        )

        def claim(state: _Ledger) -> PlayerPrincipal:
            match = self._match(state, match_id)
            if slot not in match.slots:
                raise AuthorizationError(
                    ErrorCode.SLOT_UNAVAILABLE, "Player slot is not configured"
                )
            current = match.slots[slot]
            prior = state.requests.get(request.request_id)
            if (
                prior is not None
                and prior.operation == "join"
                and (
                    prior.match_id != match_id
                    or prior.slot is not slot
                    or current.status is not SlotStatus.JOINED
                    or current.generation != prior.generation
                    or current.credential_hash is None
                    or not hmac.compare_digest(current.credential_hash, credential_hash)
                )
            ):
                raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
            retry = self._retry(state, request.request_id, fingerprint)
            if retry:
                if (
                    current.status is not SlotStatus.JOINED
                    or current.generation != retry.generation
                    or current.credential_hash != credential_hash
                ):
                    raise AuthorizationError(ErrorCode.INVALID_CREDENTIAL, "Invalid credential")
                return PlayerPrincipal(
                    match_id=match_id, player_slot=slot, authorization_generation=current.generation
                )
            self._setup(match)
            invitation = next(
                (
                    value
                    for value in match.invitations.values()
                    if hmac.compare_digest(value.token_hash, invitation_hash)
                    and value.reference.player_slot is slot
                    and value.generation == current.generation
                    and not value.invalidated
                    and not value.consumed
                    and value.reference.expires_at > self._clock()
                ),
                None,
            )
            if invitation is None:
                raise AuthorizationError(
                    ErrorCode.INVALID_INVITATION, "Invalid or expired invitation"
                )
            if current.status is SlotStatus.JOINED:
                raise AuthorizationError(ErrorCode.SLOT_UNAVAILABLE, "The player slot is taken")
            self._distinct(state, credential_hash)
            current.status = SlotStatus.JOINED
            current.credential_hash = credential_hash
            current.display_name = request.display_name
            invitation.consumed = True
            self._sync_slots(match)
            state.requests[request.request_id] = _Retry(
                operation="join",
                fingerprint=fingerprint,
                match_id=match_id,
                slot=slot,
                generation=current.generation,
                credential_hash=credential_hash,
            )
            return PlayerPrincipal(
                match_id=match_id, player_slot=slot, authorization_generation=current.generation
            )

        return self._transaction(claim)

    def revoke_slot(
        self, principal: Principal, match_id: UUID, slot: PlayerSlot, request_id: UUID
    ) -> SlotAuthorization:
        self.authorize(principal, Permission.ADMIN, match_id)
        fingerprint = self._fingerprint("revoke", match_id, slot, {})

        def revoke(state: _Ledger) -> SlotAuthorization:
            match = self._match(state, match_id)
            if slot not in match.slots:
                raise AuthorizationError(
                    ErrorCode.SLOT_UNAVAILABLE, "Player slot is not configured"
                )
            retry = self._retry(state, request_id, fingerprint)
            if retry:
                assert retry.authorization is not None
                return retry.authorization
            value = match.slots[slot]
            value.generation += 1
            value.status = SlotStatus.REVOKED
            value.credential_hash = None
            value.display_name = None
            for invitation in match.invitations.values():
                if invitation.reference.player_slot is slot:
                    invitation.invalidated = True
            self._sync_slots(match)
            result = SlotAuthorization(
                match_id=match_id,
                player_slot=slot,
                status=value.status,
                authorization_generation=value.generation,
            )
            state.requests[request_id] = _Retry(
                operation="revoke",
                fingerprint=fingerprint,
                match_id=match_id,
                slot=slot,
                generation=value.generation,
                authorization=result,
            )
            return result

        with self._lock:
            before = self._match(self._state, match_id).slots[slot].generation
            result = self._transaction(revoke)
            if self._match(self._state, match_id).slots[slot].generation != before:
                for callback in tuple(self._changed.pop((match_id, slot), ())):
                    try:
                        callback()
                    except Exception:  # noqa: BLE001, S110 -- delivery cannot undo durable revocation
                        pass
            return result

    @staticmethod
    def _setup(match: _Match) -> None:
        if match.summary.lifecycle is not MatchLifecycle.SETUP:
            raise AuthorizationError(
                ErrorCode.SLOT_UNAVAILABLE, "Player claims are allowed only during setup"
            )

    def _distinct(self, state: _Ledger, digest: str) -> None:
        if (
            hmac.compare_digest(digest, self._operator_hash)
            or any(
                digest == value.credential_hash
                for match in state.matches.values()
                for value in match.slots.values()
            )
            or any(digest == retry.credential_hash for retry in state.requests.values())
            or any(
                digest == invite.token_hash
                for match in state.matches.values()
                for invite in match.invitations.values()
            )
        ):
            raise AuthorizationError(
                ErrorCode.INVALID_CREDENTIAL, "Use an independently generated secret"
            )

    @staticmethod
    def _sync_slots(match: _Match) -> None:
        match.summary = match.summary.model_copy(
            update={
                "slots": tuple(
                    PlayerSlotState(
                        slot=slot,
                        status=match.slots[slot].status,
                        display_name=match.slots[slot].display_name,
                    )
                    for slot in match.slots
                )
            }
        )

    def summaries(self) -> tuple[MatchSummary, ...]:
        with self._lock:
            self._healthy()
            return tuple(match.summary for match in self._state.matches.values())

    def require_command_request_id(self, request_id: UUID) -> None:
        """Keep command IDs disjoint from durable metadata operation IDs."""
        with self._lock:
            self._healthy()
            if request_id in self._state.requests:
                raise AuthorizationError(
                    ErrorCode.REQUEST_ID_CONFLICT, "Request ID belongs to a metadata operation"
                )

    def import_checkpoint(
        self,
        principal: Principal,
        match_id: UUID,
        request_id: UUID,
        digest: str,
        save: Callable[[], CheckpointReference],
    ) -> CheckpointReference:
        """Persist an import receipt after immutable storage, without changing CURRENT."""
        self.authorize(principal, Permission.ARCHIVE, match_id)
        fingerprint = self._fingerprint("checkpoint_import", match_id, None, digest)

        def import_archive(state: _Ledger) -> CheckpointReference:
            retry = self._retry(state, request_id, fingerprint)
            if retry is not None:
                assert retry.checkpoint is not None
                return retry.checkpoint
            match = self._match(state, match_id)
            if match.summary.lifecycle is MatchLifecycle.CLOSED:
                raise AuthorizationError(ErrorCode.MATCH_CLOSED, "The match is closed")
            reference = save()
            if reference.match_id != match_id:
                raise ValueError("Import callback returned a checkpoint for another match")
            state.requests[request_id] = _Retry(
                operation="checkpoint_import",
                fingerprint=fingerprint,
                match_id=match_id,
                checkpoint=reference,
            )
            return reference

        return self._transaction(import_archive)

    def overlay(self, summary: MatchSummary, *, recovering: bool = False) -> MatchSummary:
        """Checkpoint verifiers and slot statuses never replace current authorization."""
        with self._lock:
            self._healthy()
            match = self._state.matches.get(summary.match_id)
            if match is None:
                raise AuthorizationError(
                    ErrorCode.RECOVERY_REQUIRED, "Current authorization metadata is missing"
                )
            if (
                match.summary.configuration != summary.configuration
                or match.summary.created_at != summary.created_at
            ):
                raise AuthorizationError(
                    ErrorCode.RECOVERY_REQUIRED, "Authorization and checkpoint metadata disagree"
                )
            if recovering and match.summary.lifecycle in {
                MatchLifecycle.SETUP,
                MatchLifecycle.CLOSED,
            }:
                raise AuthorizationError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Authorization metadata cannot adopt this checkpoint",
                )
            if (
                recovering
                and match.summary.lifecycle is MatchLifecycle.FINISHED
                and summary.lifecycle is not MatchLifecycle.FINISHED
            ):
                raise AuthorizationError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "A finished match cannot recover a playable checkpoint",
                )
            return summary.model_copy(update={"slots": match.summary.slots})

    def record_boundary(self, summary: MatchSummary) -> None:
        def record(state: _Ledger) -> None:
            match = self._match(state, summary.match_id)
            match.summary = summary.model_copy(update={"slots": match.summary.slots})
            if summary.lifecycle is MatchLifecycle.CLOSED:
                for invitation in match.invitations.values():
                    invitation.invalidated = True

        self._transaction(record)

    def credential_hashes(self, match_id: UUID) -> dict[PlayerSlot, str]:
        with self._lock:
            self._healthy()
            return {
                slot: value.credential_hash
                for slot, value in self._match(self._state, match_id).slots.items()
                if value.credential_hash is not None
            }


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
