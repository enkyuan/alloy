from kaji.cli.upgrade import find_outdated


def test_find_outdated_returns_only_upgradable() -> None:
    installed = {"kaji": "0.1.0", "kaji-serve": "0.1.0"}

    def fake(name: str) -> str | None:
        return {"kaji": "0.2.0", "kaji-serve": "0.1.0"}.get(name)

    out = find_outdated(installed, fake)
    assert out == [{"name": "kaji", "current": "0.1.0", "latest": "0.2.0"}]


def test_find_outdated_skips_unknown_latest() -> None:
    installed = {"kaji": "0.1.0"}
    out = find_outdated(installed, lambda _: None)
    assert out == []
