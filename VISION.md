# Context Lens: long-term vision

## The future we want

AI coding agents are becoming a normal development surface, but developers still have almost no
visibility into the state that shapes an agent's decisions. A session can look healthy while its
instructions are fading, its evidence is being buried, and its tool history is becoming more
expensive than useful.

Context Lens will be the open, vendor-neutral observability and recovery layer for that hidden
state. It should help any developer answer three questions, regardless of which agent they use:

1. **What is consuming the session's context?**
2. **Is the agent's working quality at risk?**
3. **What is the safest action to take next?**

The goal is not to maximize session length. The goal is to preserve intent, evidence, and forward
progress across long and complex work.

## Product promise

> Context Lens helps developers detect context degradation early, understand its cause, and recover
> without losing the important parts of the work.

Every product decision should strengthen at least one part of this promise: **detect, explain, or
recover**.

## Who it serves

- Individual developers using AI agents for multi-file and multi-hour tasks.
- Maintainers who need reliable agent behavior across large repositories.
- Teams adopting several agent tools and wanting a consistent context-health model.
- Tool builders who need an open event schema and reusable diagnostics instead of inventing another
  token gauge.
- Researchers studying long-context agent behavior in real development workflows.

The first audience is the individual developer. Team and enterprise capabilities should grow from
a tool that remains useful, local, and understandable for one person.

## Product principles

### Local and private by default

Source code, prompts, transcripts, and tool results can be sensitive. Core analysis must work
locally. Any future sync or hosted feature must be optional, explicit, and designed around
redaction and data minimization.

### Evidence before confidence

Context health is not the same as answer correctness. Signals must show their inputs, assumptions,
and limitations. Estimated values remain labeled as estimates; experimental signals remain labeled
as experimental.

### Advice must be actionable

A red gauge without a safe next step is anxiety, not observability. Every warning should explain
the likely cause and offer a concrete recovery action such as checkpointing facts, trimming stale
output, re-stating constraints, compacting, or verifying against files.

### Portable core, native integrations

Claude Code, Codex, and OpenCode expose different events and telemetry. Context Lens should share a
host-neutral analysis core while using native hooks and interfaces where they create a better user
experience. Cross-platform support must not mean lowest-common-denominator support.

### Lightweight adoption

Installation should take minutes, analysis should feel instant, and the default path should avoid a
server, account, or external database. Added complexity must earn its place.

### Open calibration

Thresholds, weights, schemas, fixtures, and benchmark methodology should be inspectable and
challengeable. The project should invite evidence that improves or disproves its heuristics.

## The product system

Context Lens should mature into five composable layers:

```text
Claude Code   Codex   OpenCode   Other hosts
     \          |        |          /
              Host adapters
                    |
       Normalized session event stream
                    |
       Context health analysis engine
                    |
      Policy and recovery recommendation
                    |
 CLI · statusline · dashboard · IDE · reports
```

### 1. Host adapters

Adapters translate native transcripts, hooks, tool events, usage data, compaction events, and model
metadata into a versioned Context Lens event schema. Each adapter owns capability detection and
reports which signals it can measure accurately.

### 2. Session model

A normalized, append-friendly session model describes turns, instructions, tool calls, artifacts,
summaries, token usage, and checkpoints. It gives every integration the same vocabulary without
requiring identical telemetry.

### 3. Analysis engine

The engine calculates explainable signals for load, redundancy, instruction distance, exploration,
retrieval quality, and compaction loss. It separates raw observations from derived scores so new
research can change the model without rewriting adapters.

### 4. Recovery engine

The recovery layer turns diagnosis into a host-appropriate plan. Early actions may be suggestions;
later integrations can offer previewable, reversible automation such as:

- Create a durable checkpoint of decisions, constraints, and unresolved questions.
- Re-anchor the agent with the active objective and acceptance criteria.
- Exclude or summarize superseded tool output.
- Compact at an evidence-informed moment.
- Verify summary claims against repository files after compaction.

### 5. User surfaces

The terminal remains the universal interface. Statuslines, dashboards, IDE views, machine-readable
JSON, and CI reports should consume the same analysis instead of developing separate scoring logic.

## Roadmap

Dates should follow validated learning rather than public promises. The phases describe capability
gates, not deadlines.

### Phase 1 — Make the Claude Code foundation undeniable

- Keep the current plugin fast, dependency-free, and well tested.
- Repair installation, screenshots, demo assets, CI, and documentation for a cold GitHub visitor.
- Add deterministic fixtures for shallow, degraded, and post-compaction sessions.
- Publish the signal definitions and known limitations.
- Establish issue templates, contribution guidance, releases, and a repeatable demo.

**Exit condition:** a new user can understand, install, verify, and demonstrate Context Lens in less
than ten minutes.

### Phase 2 — Separate the portable core

- Define versioned event, capability, signal, and report schemas.
- Refactor Claude-specific transcript parsing behind an adapter boundary.
- Provide a stable CLI that accepts normalized JSON and emits a machine-readable report.
- Add golden cross-platform contract tests before adding another host.
- Document how unavailable telemetry affects confidence and signal coverage.

**Exit condition:** the same fixture produces the same health report without importing Claude Code
concepts into the analysis engine.

### Phase 3 — Codex and OpenCode

- Research the stable telemetry and extension points of each host.
- Implement one adapter at a time, beginning with read-only reports.
- Add native commands and the best available live surface for each tool.
- Publish a capability matrix so “supported” has a precise meaning.
- Compare equivalent sessions across hosts to find adapter or calibration bias.

**Exit condition:** Claude Code, Codex, and OpenCode can all produce an honest Context Lens report,
with clearly disclosed differences in fidelity.

### Phase 4 — Recovery workflows

- Generate portable session checkpoints containing intent, constraints, evidence, decisions, and
  next actions.
- Add re-anchor and post-compaction verification workflows.
- Recommend interventions based on the dominant signal instead of a single threshold.
- Make every automated mutation previewable, reversible, and opt-in.
- Measure whether interventions reduce repeated work and forgotten constraints.

**Exit condition:** Context Lens can demonstrate that its recommendations improve task continuity,
not merely that its dashboard changes color.

### Phase 5 — Ecosystem and team learning

- Publish an adapter SDK and compatibility test suite.
- Support community-defined signals and output surfaces with explicit trust boundaries.
- Add anonymized, opt-in aggregate studies and reproducible benchmark datasets.
- Explore team-level policy, fleet health, and CI integration without centralizing private session
  content.
- Collaborate with agent-tool maintainers and long-context researchers.

**Exit condition:** external contributors can add a host or signal without changing the core, and
teams can learn from aggregate health patterns without exposing session contents.

## Success measures

Vanity metrics help distribution, but product evidence must lead.

### User outcomes

- Fewer sessions abandoned because the agent lost constraints or repeated work.
- Less time spent reconstructing state after compaction or a new session.
- Higher completion rate for long, multi-step coding tasks.
- Developers can correctly explain why Context Lens raised a warning and what to do next.

### Product quality

- Analyzer latency and memory stay negligible relative to the host tool.
- False alarms and missed degradation reports are tracked against reproducible fixtures.
- Reports disclose signal coverage and confidence per host.
- No transcript content leaves the machine in the default configuration.

### Community and professional reach

- GitHub stars, forks, contributors, adapter proposals, and repeat users.
- Useful issue reports containing anonymized fixtures rather than only reactions to screenshots.
- Technical articles and demos that teach context engineering, not only promote the repository.
- Citations or collaborations with agent-tool maintainers and researchers.

## Public narrative

Context Lens should be communicated through honest engineering milestones:

1. **Problem:** long-context failure is gradual and invisible.
2. **Evidence:** show a reproducible session where measurable signals change.
3. **Build:** explain the local analyzer, scoring model, tradeoffs, and tests.
4. **Outcome:** demonstrate the warning and the recovery workflow.
5. **Invitation:** ask users to test, challenge calibration, or build an adapter.

For GitHub, the repository should provide a ten-second explanation, a real visual, a tested install,
and a visible roadmap. For LinkedIn and other professional channels, each release should become a
small technical story with a concrete lesson, evidence, and a link to something others can run.

Credibility is the growth strategy: do not imply support for a platform until an integration is
usable, do not turn heuristics into scientific claims, and publish limitations alongside results.

## Deliberate non-goals

Context Lens is not intended to:

- Replace a coding agent or choose which model is “best.”
- Read source code or transcripts through a hosted service by default.
- Claim that token usage alone predicts answer quality.
- Silently rewrite prompts, compact sessions, or delete context.
- Become a general application-performance monitoring platform.
- Promise identical capabilities when host telemetry differs.

## Decision filter

When choosing what to build, ask:

1. Does it help a developer detect, explain, or recover from context degradation?
2. Can it work locally and preserve user control?
3. Is the result supported by observable evidence?
4. Does it strengthen the portable core or a genuinely native integration?
5. Can a contributor understand and test it?

If the answer is mostly no, it is probably outside the Context Lens mission.
