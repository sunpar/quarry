import pytest

from quarry.cli import banner, free_port, main, new_token


def test_banner_contains_tunnel_and_url() -> None:
    text = banner(port=4321, token="abc", host_hint="devbox")
    assert "ssh -L 4321:127.0.0.1:4321 devbox" in text
    assert "http://127.0.0.1:4321/#token=abc" in text


def test_free_port_is_usable() -> None:
    port = free_port()
    assert 1024 < port < 65536


def test_token_is_long_and_url_safe() -> None:
    token = new_token()
    assert len(token) >= 40 and all(c.isalnum() or c in "-_" for c in token)


def test_main_without_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "serve" in capsys.readouterr().err
