"""Tests for the FreePBX facade."""

from __future__ import annotations

import os

import pytest

from pyfreepbx import FreePBX
from pyfreepbx.exceptions import ConfigError
from pyfreepbx.services.extensions import ExtensionService
from pyfreepbx.services.health import HealthService
from pyfreepbx.services.queues import QueueService
from pyfreepbx.services.system import SystemService


class TestFreePBXFacade:
    def test_construction_graphql_only(self) -> None:
        pbx = FreePBX(host="pbx.test", api_token="tok")
        assert pbx.ami_available is False
        assert isinstance(pbx.extensions, ExtensionService)
        assert isinstance(pbx.queues, QueueService)
        assert isinstance(pbx.system, SystemService)
        assert isinstance(pbx.health, HealthService)
        pbx.close()

    def test_construction_with_ami(self) -> None:
        pbx = FreePBX(
            host="pbx.test",
            api_token="tok",
            ami_username="admin",
            ami_secret="secret",
        )
        assert pbx.ami_available is True
        pbx.close()

    def test_context_manager(self) -> None:
        with FreePBX(host="pbx.test", api_token="tok") as pbx:
            assert isinstance(pbx, FreePBX)

    def test_repr(self) -> None:
        pbx = FreePBX(host="pbx.test", api_token="tok")
        assert "pbx.test" in repr(pbx)
        assert "ami=disabled" in repr(pbx)
        pbx.close()

    def test_from_env_missing_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FREEPBX_HOST", raising=False)
        monkeypatch.delenv("FREEPBX_API_TOKEN", raising=False)
        with pytest.raises(ConfigError):
            FreePBX.from_env()

    def test_from_env_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FREEPBX_HOST", "env.test")
        monkeypatch.setenv("FREEPBX_API_TOKEN", "env-tok")
        pbx = FreePBX.from_env()
        assert repr(pbx) == "<FreePBX host='env.test' ami=disabled>"
        pbx.close()

    def test_connect_ami_without_config(self) -> None:
        pbx = FreePBX(host="pbx.test", api_token="tok")
        with pytest.raises(ConfigError, match="AMI is not configured"):
            pbx.connect_ami()
        pbx.close()
