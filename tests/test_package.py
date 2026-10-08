import quarry


def test_version_is_string():
    assert isinstance(quarry.__version__, str)
