import pytest

from src.greet import greet


def test_greet_basic():
    assert greet("world") == "Hello, world!"


def test_greet_rejects_empty():
    with pytest.raises(ValueError):
        greet("")


def test_greet_rejects_whitespace():
    with pytest.raises(ValueError):
        greet("   ")
