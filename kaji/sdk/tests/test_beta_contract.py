import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "kaji" / "contracts" / "beta-core-v1.json"
PACKAGE_CONTRACTS = REPO_ROOT / "kaji" / "sdk" / "src" / "contracts"


def test_beta_contract_defaults_are_public_and_stable() -> None:
    contract = json.loads(CONTRACT.read_text())

    assert contract["runtime"]["sameSessionTurns"] == "serialized"
    assert contract["runtime"]["maxToolIterations"] == 5
    assert contract["runtime"]["contextWindowTurns"] == 32
    assert contract["tools"]["maxConcurrency"] == 4
    assert contract["tools"]["timeoutMs"] == 30_000
    assert contract["events"]["subscriberQueueCapacity"] == 1024
    assert contract["events"]["inMemoryStoreMaxEventsPerSession"] == 10_000


def test_python_package_contract_copy_matches_canonical_files() -> None:
    canonical = REPO_ROOT / "kaji" / "contracts"
    for source in canonical.rglob("*"):
        if source.is_file() and source.suffix in {".json", ".md"}:
            packaged = PACKAGE_CONTRACTS / source.relative_to(canonical)
            assert packaged.read_bytes() == source.read_bytes()
