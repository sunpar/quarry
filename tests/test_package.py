import quarry


def test_version_is_string() -> None:
    assert isinstance(quarry.__version__, str)
