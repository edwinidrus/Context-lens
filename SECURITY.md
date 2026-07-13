# Security and privacy

## Supported versions

Security fixes are applied to the latest release on `main`. Older local marketplace copies are not
updated automatically; rebuild or upgrade the marketplace and restart the host after updating.

## Reporting a vulnerability

Please use GitHub's **Security → Report a vulnerability** flow for issues that could expose local
transcripts, prompts, source paths, credentials, or arbitrary command execution. Do not open a
public issue containing private session data. If private reporting is unavailable, contact the
maintainer through the project email in `.codex-plugin/plugin.json` with only a minimal description
and arrange a safe channel before sharing reproduction data.

## Trust boundary

- Context Lens runs locally with the permissions of the current user.
- Claude Code analysis reads the host-provided transcript path. The opt-in Codex experiment reads a
  bounded rollout tail and persists numeric token metadata only.
- Generated reports and privacy-minimized summaries are stored under `~/.context-lens/` by default.
- The project does not send transcripts, reports, or usage telemetry to a remote service.
- Plugin hook commands must be reviewed and trusted in the host before they run.

Treat generated HTML reports and local cache files as sensitive metadata. Do not publish real
transcripts or cache directories when reporting a bug; use a minimal anonymized JSONL fixture.
