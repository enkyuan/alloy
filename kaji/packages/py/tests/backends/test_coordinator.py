from kaji.backends.postgres.coordinator import postgres_lock_key


def test_postgres_lock_key_is_stable() -> None:
    assert postgres_lock_key("same") == 677529369334489940
