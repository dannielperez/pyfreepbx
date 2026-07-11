"""Consistency tests for firewall network replacement."""

from unittest.mock import MagicMock, call

from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.services.firewall import FirewallReplacementState, FirewallService


def _service() -> FirewallService:
    return FirewallService(MagicMock())


def test_replace_creates_before_deleting_old_network():
    service = _service()
    service.create_network = MagicMock()
    service.delete_network = MagicMock(return_value=True)
    calls = MagicMock()
    calls.attach_mock(service.create_network, "create")
    calls.attach_mock(service.delete_network, "delete")

    result = service.replace_network("1.2.3.4/32", "5.6.7.8/32", name="Site", zone="trusted")

    assert result.state is FirewallReplacementState.SUCCESS
    assert [item[0] for item in calls.mock_calls] == ["create", "delete"]


def test_create_failure_with_absent_replacement_leaves_old_network_untouched():
    service = _service()
    service.create_network = MagicMock(side_effect=RuntimeError("create failed"))
    service.get_network = MagicMock(side_effect=NotFoundError("absent"))
    service.delete_network = MagicMock()

    result = service.replace_network("1.2.3.4/32", "5.6.7.8/32", name="Site", zone="trusted")

    assert result.state is FirewallReplacementState.CREATE_FAILED
    service.delete_network.assert_not_called()


def test_delete_failure_compensates_only_after_old_network_is_confirmed_present():
    service = _service()
    service.create_network = MagicMock()
    service.delete_network = MagicMock(side_effect=[RuntimeError("delete old failed"), True])
    service.get_network = MagicMock(return_value=object())

    result = service.replace_network("1.2.3.4/32", "5.6.7.8/32", name="Site", zone="trusted")

    assert result.state is FirewallReplacementState.ROLLED_BACK
    assert service.delete_network.call_args_list == [
        call("1.2.3.4/32"),
        call("5.6.7.8/32"),
    ]


def test_ambiguous_delete_readback_reports_partial_without_compensation():
    service = _service()
    service.create_network = MagicMock()
    service.delete_network = MagicMock(side_effect=RuntimeError("delete timed out"))
    service.get_network = MagicMock(side_effect=RuntimeError("readback timed out"))

    result = service.replace_network("1.2.3.4/32", "5.6.7.8/32", name="Site", zone="trusted")

    assert result.state is FirewallReplacementState.PARTIAL
    assert result.verification_error == "readback timed out"
    service.delete_network.assert_called_once_with("1.2.3.4/32")
