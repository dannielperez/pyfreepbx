import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "media_nat_guard", Path(__file__).parents[1] / "tools/pbx_media/media_nat_guard.py"
)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
ROW = {
    "extension": "4301",
    "panel": "10.40.41.241",
    "pbx": "10.254.250.11",
    "panel_peer": "site-key",
    "pbx_peer": "pbx-key",
    "comment": "approved-media",
}


def inputs():
    rules = g.rule_args(ROW)
    saved = {
        "PostUp": [["iptables", "-t", "nat", "-I", "POSTROUTING", "1", *r] for r in rules],
        "PostDown": [["iptables", "-t", "nat", "-D", "POSTROUTING", *r] for r in rules],
    }
    runtime = [["-A", "POSTROUTING", *r] for r in rules]
    runtime.append(["-A", "POSTROUTING", "-o", "wg0", "-j", "MASQUERADE"])
    return [
        saved,
        runtime,
        {"site-key": ["10.40.41.0/24"], "pbx-key": ["10.254.250.11/32"]},
        {"site-key": 950, "pbx-key": 960},
        {"10.40.41.241": "wg0", "10.254.250.11": "wg0"},
        1000,
    ]


def test_healthy_and_missing_rule_plan_preserves_unrelated_rules():
    args = inputs()
    assert g.inspect(ROW, *args) == ("clear", [])
    args[1].pop(0)
    assert g.inspect(ROW, *args) == ("missing_rule", [g.rule_args(ROW)[0]])
    assert args[1][-1][-1] == "MASQUERADE"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("saved", "saved_policy_drift"),
        ("peer", "route_or_peer_conflict"),
        ("route", "route_or_peer_conflict"),
        ("stale", "stale_tunnel"),
        ("duplicate", "duplicate_rule"),
        ("order", "rule_order_review"),
    ],
)
def test_uncertain_or_changed_policy_never_authorizes_write(change, reason):
    args = inputs()
    if change == "saved":
        args[0]["PostDown"] = []
    if change == "peer":
        args[2]["competing"] = ["10.40.41.241/32"]
    if change == "route":
        args[4]["10.40.41.241"] = "eth0"
    if change == "stale":
        args[3]["site-key"] = 1
    if change == "duplicate":
        args[1].insert(0, args[1][0])
    if change == "order":
        args[1].insert(0, args[1].pop())
    assert g.inspect(ROW, *args) == (reason, [])


def test_exact_saved_commands_required():
    args = inputs()
    config = (
        "PostUp = "
        + "; ".join(" ".join(r) for r in args[0]["PostUp"])
        + "\nPostDown = "
        + "; ".join(" ".join(r) for r in args[0]["PostDown"])
    )
    assert g.saved_rules(config) == args[0]
    assert g.saved_rules(config.replace("ACCEPT", "MASQUERADE")) != args[0]


def test_runtime_udp_normalization():
    rule = g.rule_args(ROW)[0]
    assert g.normalize([*rule[:8], "-m", "udp", *rule[8:]]) == rule


def test_unapproved_duplicate_and_public_addresses_rejected():
    for rows in [[ROW, ROW], [{**ROW, "panel": "8.8.8.8"}], [{**ROW, "extension": "x;bad"}]]:
        with pytest.raises(ValueError):
            g.approved_rows({"version": 1, "approved": rows})


def test_reconcile_repairs_only_saved_missing_rules_and_is_idempotent(monkeypatch):
    from types import SimpleNamespace

    args = inputs()
    config = (
        "PostUp = "
        + "; ".join(" ".join(r) for r in args[0]["PostUp"])
        + "\nPostDown = "
        + "; ".join(" ".join(r) for r in args[0]["PostDown"])
    )
    runtime = args[1][2:]
    commands = []
    monkeypatch.setattr(g.time, "time", lambda: 1000)
    monkeypatch.setattr(g, "collect", lambda: (args[2], args[3], list(runtime)))
    monkeypatch.setattr(g, "Path", lambda p: SimpleNamespace(read_text=lambda: config))

    def run(cmd):
        commands.append(cmd)
        if cmd[0] == "ip":
            return '[{"dev":"wg0"}]'
        if cmd[:7] == ["iptables", "-w", "5", "-t", "nat", "-I", "POSTROUTING"]:
            runtime.insert(0, ["-A", "POSTROUTING", *cmd[8:]])
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(g, "run", run)
    manifest = {"version": 1, "source_id": "pbx", "approved": [ROW]}
    first = g.reconcile(manifest, config, True, lambda: True)
    assert first["paths"][0]["repair"] == "restored"
    assert first["paths"][0]["state"] == "clear"
    assert sum(c[0] == "iptables" for c in commands) == 2
    g.reconcile(manifest, config, True, lambda: True)
    assert sum(c[0] == "iptables" for c in commands) == 2
    assert runtime[-1][-1] == "MASQUERADE"


def test_read_error_never_produces_a_healthy_path(monkeypatch):
    def fail():
        raise OSError("unavailable")

    monkeypatch.setattr(g, "collect", fail)
    row = g.reconcile({"version": 1, "source_id": "pbx", "approved": [ROW]}, "")["paths"][0]
    assert row["state"] == "unknown"
    assert row["reason"] == "probe_or_repair_error"
