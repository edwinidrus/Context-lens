# Security and privacy

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13601/badge)](https://www.bestpractices.dev/projects/13601)

Context Lens holds the OpenSSF Best Practices **baseline-1** badge
([project 13601](https://www.bestpractices.dev/en/projects/13601)), covering basic OSS hygiene:
public version control, an OSS license, a working build/test pipeline, and a documented
vulnerability-reporting process (this file).

## Supported versions

Security fixes are applied to the latest release on `main`. Older local marketplace copies are not
updated automatically; rebuild or upgrade the marketplace and restart the host after updating.

## Reporting a vulnerability

Security contact: [@edwinidrus](https://github.com/edwinidrus).

Please use Context Lens's
[private vulnerability reporting form](https://github.com/edwinidrus/Context-lens/security/advisories/new)
for issues that could expose local transcripts, prompts, source paths, credentials, or arbitrary
command execution. Do not open a public issue containing private session data. If private reporting
is unavailable, contact the maintainer through the project email in `.codex-plugin/plugin.json` with
only a minimal description and arrange a safe channel before sharing reproduction data.

## Trust boundary

- Context Lens runs locally with the permissions of the current user.
- Claude Code analysis reads the host-provided transcript path. The opt-in Codex experiment reads a
  bounded rollout tail and persists numeric token metadata only.
- Generated reports and privacy-minimized summaries are stored under `~/.context-lens/` by default.
- The project does not send transcripts, reports, or usage telemetry to a remote service.
- Plugin hook commands must be reviewed and trusted in the host before they run.

Treat generated HTML reports and local cache files as sensitive metadata. Do not publish real
transcripts or cache directories when reporting a bug; use a minimal anonymized JSONL fixture.
