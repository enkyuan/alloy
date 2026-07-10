import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "kaji" / "contracts" / "beta-core-v1.json"


def test_beta_contract_defaults_are_public_and_stable() -> None:
    contract = json.loads(CONTRACT.read_text())

    assert contract["runtime"]["sameSessionTurns"] == "serialized"
    assert contract["runtime"]["maxToolIterations"] == 5
    assert contract["runtime"]["contextWindowTurns"] == 32
    assert contract["tools"]["maxConcurrency"] == 4
    assert contract["tools"]["timeoutMs"] == 30_000
    assert contract["events"]["subscriberQueueCapacity"] == 1024
    assert contract["events"]["inMemoryStoreMaxEventsPerSession"] == 10_000
