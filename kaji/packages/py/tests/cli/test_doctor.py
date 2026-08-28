from kaji.cli.doctor import run_checks


def test_doctor_fails_without_provider_key() -> None:
    out = run_checks(env={}, python_version="3.11.0", kaji_version="0.1.0")
    assert out["failed"] is True


def test_doctor_passes_with_minimum_setup() -> None:
    out = run_checks(
        env={"OPENAI_API_KEY": "sk"}, python_version="3.11.0", kaji_version="0.1.0"
    )
    assert out["failed"] is False
