"""Settings guard tests: placeholder SECRET_KEY must not boot outside debug."""

from __future__ import annotations

import pytest

from cartograph.settings import Settings


def test_placeholder_secret_rejected_in_prod() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(secret_key="change-me", debug=False, _env_file=None)


def test_short_secret_rejected_in_prod() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(secret_key="short", debug=False, _env_file=None)


def test_placeholder_secret_allowed_in_debug() -> None:
    assert Settings(secret_key="change-me", debug=True, _env_file=None).debug


def test_real_secret_accepted() -> None:
    s = Settings(secret_key="a" * 32, debug=False, _env_file=None)
    assert s.secret_key == "a" * 32
