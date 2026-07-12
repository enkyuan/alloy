# Testing Kaji

Use deterministic seams for local tests, then test the exact package artifact.
Local success is offline rehearsal, not protected release evidence.

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

Packed TypeScript consumers compile with TypeScript 5.7.3 and the current 6.x
compiler with `skipLibCheck: false`. Runtime support is a separate Node 22 and
Node 24 matrix; compiler support does not imply other Node versions.

Release child processes use the bounded release-operator runner. Its tested
POSIX process-group cleanup requires macOS or Linux. That operator constraint
does not narrow the SDK runtime platforms declared by package metadata.

## Protected evidence

OpenAI and Anthropic each require a real normalized tool loop in Python and
TypeScript on the exact commit. A missing key is a blocking failure, not a
skip. The exact-commit five-user TTHW protocol lives in
`kaji/contracts/release/tthw-evidence-v1.schema.json`; until five real runs are
retained and validated, human TTHW remains **unmeasured**.
