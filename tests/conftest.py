"""Tests are offline by default. MockTransport and ASGI clients remain available."""
import socket
import pytest
@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    def denied(*args,**kwargs):
        raise AssertionError('Network is disabled in unit tests; use httpx.MockTransport')
    monkeypatch.setattr(socket.socket,'connect',denied)
