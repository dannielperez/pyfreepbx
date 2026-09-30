#!/usr/bin/env python3
"""Reconcile only approved, persistently saved, source-preserving VPN media rules.

Runs on the VPN hub. Does not discover/approve endpoints, change routes, clear
conntrack, restart services, or infer human audibility. Python 3, standard library.
"""

import argparse
import fcntl
import ipaddress
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

MAX_BYTES = 1024 * 1024


def run(args):
    return subprocess.check_output(args, timeout=8, text=True, stderr=subprocess.PIPE)


def trusted_json(path):
    with open(path) as stream:
        st = os.fstat(stream.fileno())
        if st.st_uid != 0 or st.st_mode & 0o022 or st.st_size > MAX_BYTES:
            raise ValueError("manifest must be root-owned and not group/world writable")
        return json.load(stream)


def approved_rows(manifest):
    rows = manifest["approved"]
    if manifest.get("version") != 1 or not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("invalid manifest")
    seen = set()
    addresses = set()
    for row in rows:
        if not isinstance(row["extension"], str) or not row["extension"].isdigit():
            raise ValueError("invalid extension")
        if row["extension"] in seen or row["panel"] in addresses:
            raise ValueError("duplicate approval")
        seen.add(row["extension"])
        addresses.add(row["panel"])
        for name in ("panel", "pbx"):
            ip = ipaddress.IPv4Address(row[name])
            if not ip.is_private or ip.is_unspecified or ip.is_loopback or ip.is_multicast:
                raise ValueError("only explicit private endpoints are supported")
        if row["panel"] == row["pbx"] or row["panel_peer"] == row["pbx_peer"]:
            raise ValueError("distinct endpoint peers required")
        if not row["comment"] or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in row["comment"]
        ):
            raise ValueError("invalid rule label")
    return rows


def rule_args(row):
    return [
        [
            "-s",
            s + "/32",
            "-d",
            d + "/32",
            "-o",
            "wg0",
            "-p",
            "udp",
            "--dport",
            "10000:20000",
            "-m",
            "comment",
            "--comment",
            row["comment"],
            "-j",
            "ACCEPT",
        ]
        for s, d in [(row["pbx"], row["panel"]), (row["panel"], row["pbx"])]
    ]


def normalize(tokens):
    # iptables -S adds this implicit module to a UDP rule.
    result = list(tokens)
    for i in range(len(result) - 1, 0, -1):
        if result[i - 1 : i + 1] == ["-m", "udp"]:
            del result[i - 1 : i + 1]
    return result


def saved_rules(config):
    result = {"PostUp": [], "PostDown": []}
    for line in config.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in result:
            lexer = shlex.shlex(value, posix=True, punctuation_chars=";")
            lexer.whitespace_split = True
            command = []
            for token in [*list(lexer), ";"]:
                if token == ";":
                    result[key.strip()].append(normalize(command))
                    command = []
                else:
                    command.append(token)
    return result


def owns(address, key, peers):
    matches = [
        (ipaddress.ip_network(net).prefixlen, peer)
        for peer, networks in peers.items()
        for net in networks
        if ipaddress.ip_address(address) in ipaddress.ip_network(net)
    ]
    if not matches:
        return False
    longest = max(size for size, _ in matches)
    return {peer for size, peer in matches if size == longest} == {key}


def inspect(row, saved, runtime, peers, handshakes, routes, now):
    rules = rule_args(row)
    for rule in rules:
        if ["iptables", "-t", "nat", "-I", "POSTROUTING", "1", *rule] not in saved["PostUp"] or [
            "iptables",
            "-t",
            "nat",
            "-D",
            "POSTROUTING",
            *rule,
        ] not in saved["PostDown"]:
            return "saved_policy_drift", []
    for address, key in [(row["panel"], row["panel_peer"]), (row["pbx"], row["pbx_peer"])]:
        if not owns(address, key, peers) or routes.get(address) != "wg0":
            return "route_or_peer_conflict", []
        age = now - handshakes.get(key, 0)
        if not 0 <= age <= 180:
            return "stale_tunnel", []
    # Only first-position approved exemptions may precede the expected generic
    # masquerade. Do not try to repair arbitrary jumps or earlier NAT policy.
    missing = []
    for rule in rules:
        desired = ["-A", "POSTROUTING", *rule]
        positions = [i for i, existing in enumerate(runtime) if normalize(existing) == desired]
        if len(positions) > 1:
            return "duplicate_rule", []
        if positions:
            for prior in runtime[: positions[0]]:
                if "-j" in prior and prior[prior.index("-j") + 1] != "ACCEPT":
                    return "rule_order_review", []
        else:
            missing.append(rule)
    return ("missing_rule" if missing else "clear"), missing


def collect():
    peers = {}
    for line in run(["wg", "show", "wg0", "allowed-ips"]).splitlines():
        key, nets = line.split("\t", 1)
        peers[key] = [n for n in nets.split() if n != "(none)"]
    handshakes = dict(
        (key, int(at))
        for key, at in (
            line.split("\t")
            for line in run(["wg", "show", "wg0", "latest-handshakes"]).splitlines()
        )
    )
    runtime = [
        shlex.split(line)
        for line in run(["iptables", "-t", "nat", "-S", "POSTROUTING"]).splitlines()
        if line.startswith("-A ")
    ]
    return peers, handshakes, runtime


def reconcile(manifest, config, apply=False, approval_check=None):
    rows = approved_rows(manifest)
    saved = saved_rules(config)
    results = []
    deadline = time.monotonic() + 45
    for row in rows:
        result = {"extension": row["extension"], "state": "unknown", "repair": "none"}
        try:
            if time.monotonic() >= deadline:
                raise ValueError("run budget exhausted")
            peers, handshakes, runtime = collect()
            routes = {}
            for address in (row["panel"], row["pbx"]):
                route = json.loads(run(["ip", "-j", "route", "get", address]))
                routes[address] = route[0].get("dev") if len(route) == 1 else None
            reason, missing = inspect(row, saved, runtime, peers, handshakes, routes, time.time())
            if apply and missing:
                # Recheck persisted approval immediately before bounded writes.
                if Path("/etc/wireguard/wg0.conf").read_text() != config:
                    raise ValueError("saved configuration changed")
                if approval_check is not None and not approval_check():
                    raise ValueError("manifest changed")
                check_peers, check_handshakes, check_runtime = collect()
                if (
                    check_peers != peers
                    or check_runtime != runtime
                    or inspect(
                        row,
                        saved,
                        check_runtime,
                        check_peers,
                        check_handshakes,
                        routes,
                        time.time(),
                    )[0]
                    != "missing_rule"
                ):
                    raise ValueError("runtime changed")
                result["repair"] = "verification_failed"
                for rule in missing:
                    run(["iptables", "-w", "5", "-t", "nat", "-I", "POSTROUTING", "1", *rule])
                peers, handshakes, runtime = collect()
                reason, _remaining = inspect(
                    row, saved, runtime, peers, handshakes, routes, time.time()
                )
                result["repair"] = "restored" if reason == "clear" else "verification_failed"
            result.update(state="clear" if reason == "clear" else "fault", reason=reason)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            result.update(state="unknown", reason="probe_or_repair_error")
        results.append(result)
    return {
        "version": 1,
        "source_id": manifest["source_id"],
        "observed_at": time.time(),
        "paths": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--s3-uri")
    args = parser.parse_args()
    with open("/run/media-nat-guard.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = trusted_json(args.manifest)
        result = reconcile(
            manifest,
            Path("/etc/wireguard/wg0.conf").read_text(),
            args.apply,
            lambda: trusted_json(args.manifest) == manifest,
        )
        output = Path(args.output)
        temporary = output.with_suffix(".tmp")
        with open(temporary, "w") as stream:
            os.chmod(temporary, 0o600)
            json.dump(result, stream)
        os.replace(temporary, output)
        if args.s3_uri:
            subprocess.run(
                ["aws", "s3", "cp", str(output), args.s3_uri, "--only-show-errors"],
                timeout=15,
                check=True,
            )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
