# kaji

`kaji` is an embeddable SDK for building agents into your own platform. It ships
in two languages plus a reference service, arranged as workspace packages under
`kaji/packages/`, with the canonical contract spine and release machinery shared
at this level.

<!-- canonical-status-links:start -->
> Canonical documentation: https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md
> Release status and evidence: https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md
<!-- canonical-status-links:end -->

OpenAI is the sole beta-supported primary provider. Anthropic, Gemini, Kimi, and
OpenRouter are opt-in experimental adapters. Use the deterministic mock provider
for local and test flows. See [**Kaji MVP**](https://github.com/enkyuan/alloy/blob/main/docs/MVP.md)
for the full developer path and scope.

## Packages

| Package      | Path                          | Published as        | What it is                                            |
| ------------ | ----------------------------- | ------------------- | ----------------------------------------------------- |
| Python SDK   | [`packages/py`](packages/py)         | `kaji` (PyPI)   | Python embedded agent SDK, imported as `kaji`. Full docs in its own README. |
| TypeScript SDK | [`packages/ts`](packages/ts) | `kaji` (npm)    | TypeScript embedded agent SDK                         |
| Reference service | [`packages/serve`](packages/serve)       | `kaji-serve` (unpublished) | Experimental FastAPI + Soniox STT reference service   |

> The npm package publishes as `kaji`; the PyPI package publishes as `kaji`.
> The Python package is imported as `kaji`; the TypeScript package as `kaji`.

Canonical contracts, release scripts, benchmarks, and fixtures live once at the
Kaji root (`contracts/`, `scripts/`, `benchmarks/`, `fixtures/`) and are consumed
by both SDKs. The Python SDK and reference service form a `uv` workspace rooted at
the repository root.

## Where to run what

| Task                      | From                          | Command                                      |
| ------------------------- | ----------------------------- | -------------------------------------------- |
| Python SDK tests          | repo root                     | `uv run --package kaji pytest`           |
| Reference-service tests   | repo root                     | `uv run --package kaji-serve pytest`         |
| TypeScript SDK tests      | repo root                     | `bun --filter @irogane/kaji test`                 |
| Release forensics / gates | `kaji/`                       | `kaji/scripts/*.py` (e.g. `beta_release_check.py`) |

Contributor setup and the full local-check matrix live in
[`CONTRIBUTING.md`](https://github.com/enkyuan/alloy/blob/main/CONTRIBUTING.md).
