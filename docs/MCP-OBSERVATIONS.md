# MCP state, command, and screenshot observations

The MCP server now offers versioned state and command resources plus equivalent
state/observation tools for clients that only call tools. The resources are
`aw2://v1/matches/{match_id}/state` and
`aw2://v1/matches/{match_id}/commands/{command_id}`. Both return the existing
`StateResponse` / `CommandResult` JSON models, including settled lifecycle state,
readiness, unavailable decoder fields, terminal errors, and unknown values.

Every read resolves the bearer from the authenticated request context and goes
through the shared SDK and HTTP authorization facade. Player reads are restricted
to their own match. Reads do not enter the mutation queue, advance frames, or
change revisions. After reconnect, clients should read current state and command
status; MCP resource reads do not promise replay.

`get_screenshot(match_id, revision)` requires an explicit revision and only reads
the committed cached boundary image. The SDK verifies PNG content type/signature,
a 1 MiB bound, match ID, requested revision, and frame metadata from the same HTTP
response. MCP returns image content plus structured
`{contract_version, match_id, revision, frame, mime_type}` metadata. A missing
image or revision mismatch preserves the shared `observation_unavailable` error;
malformed or mismatched response metadata produces a sanitized protocol error.
No executing-frame screenshot is available through this tool.

ROM-independent checks use the mounted transport and a controlled executor. They
compare resource/tool state, read terminal command status, assert screenshots carry
the same revision/frame as the committed state, check cross-match denial, verify
an unavailable old boundary error, and confirm repeated reads leave the frame and
revision unchanged. The SDK tests reject forged response identity/revision. This
does not claim real display capture or live host image rendering; those remain in
the live Milestone 4 verification task.
