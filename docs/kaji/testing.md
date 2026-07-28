# Testing Kaji

Use deterministic seams for local tests, then test the exact package artifact.
Local success is offline rehearsal, not protected release evidence.

## Local CI

Validate workflow syntax and executable workflow contracts:

```bash
bun run check:workflows
```

This requires `actionlint` (`brew install actionlint` on macOS).

Run the same Kaji gate command used by `gate / kaji`:

```bash
bun run ci:kaji
```

Run both checks together before pushing:

```bash
bun run ci:local
```

The combined command checks the uv lockfile and performs frozen Python and Bun
dependency syncs before running the gate.

These commands verify repository-owned workflow logic on the current macOS
host. They do not emulate the GitHub Actions runner environment, protected
environments, OIDC, artifact transfer, attestations, registry publication, or
keyed provider proof.

## Deterministic tests

- Use Python `get_provider("mock")` or TypeScript `MockProvider` for no-key
  turns and tool loops.
- Inject `Clock`, `IdFactory`, and the timer scheduler when asserting IDs,
  deadlines, ordering, or coalescing. Do not sleep in unit tests.
- Run canonical event, tool, integration, provider-normalization, CLI, and
  parity fixtures from `kaji/contracts/` in both SDKs.
- Test invalid durable tool results and provider-output bounds before testing
  recovery. External-effect tools with an unknown outcome are not auto-retried.

## Exact artifacts

Python tests build the wheel and sdist, install each in a clean virtual
environment, invoke the installed `kaji init --provider mock --yes`, run the
generated project cold and warm, and assert text, turn ID, and positive final
sequence. TypeScript tests pack the npm tarball, validate the scaffold's exact
SDK version and peer ranges, substitute that local tarball, then use separate
clean npm and Bun projects.

Packed TypeScript consumers compile with TypeScript 5.7.3 and 6.0.3 with
`skipLibCheck: false`. Protected runtime onboarding is limited to two
GitHub-hosted Linux/x64 cells: Node 22 on `ubuntu-22.04` and Node 24 on
`ubuntu-24.04`, each using npm and Bun. This evidence makes no broader runtime
or platform claim, including for other Node versions, macOS/arm64, Windows, or
fully offline dependency installation.

Release child processes use the bounded release-operator runner. Its tested
POSIX process-group cleanup requires macOS or Linux. That operator constraint
is separate from protected onboarding and does not establish another SDK
runtime platform.

## Protected evidence

OpenAI requires a real normalized tool loop in Python and TypeScript on the
exact commit. A missing `OPENAI_API_KEY` is a blocking failure, not a skip.
Anthropic and the other experimental/WIP providers are not beta publication
proof.

TypeScript onboarding evidence is derived from the exact current-run tarball
and raw producer/Node-compatibility archives. It requires npm and Bun install,
scaffold, no-key, deterministic Echo lifecycle, cold, and warm phases in two
GitHub-hosted Linux/x64 cells: Node 22 on `ubuntu-22.04` and Node 24 on
`ubuntu-24.04`. See the
[TypeScript onboarding evidence contract](typescript-onboarding-evidence.md).
This automated evidence does not claim human usability measurements,
macOS/arm64 or Windows onboarding, or fully offline dependency installation.

The paired benchmark and 30-minute soak remain separate required
GitHub-hosted macOS/arm64 evidence. Keyed provider proof and the final npm
publisher each retain their distinct protected-environment reviewer boundary.
PyPI publication is deferred.
