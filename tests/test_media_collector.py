import json
import struct
import sys
import unittest
from pathlib import Path

# The standalone collector is intentionally Python 2 compatible on legacy PBXs.
sys.path.insert(0, str(Path(__file__).parents[1] / "tools/pbx_media"))
from media_evidence import CaptureStats, Evidence, bridge_pairs, queue_evidence, route_evidence

PBX = "10.254.250.11"


def sip(cid, ext, other, method="INVITE", response=False, port=11082, outgoing=True, cseq=1):
    first = "SIP/2.0 200 OK" if response else method + " sip:" + other + "@host SIP/2.0"
    return (
        f"{first}\r\nCall-ID: {cid}\r\nFrom: <sip:{other if outgoing else ext}@host>\r\n"
        f"To: <sip:{ext if outgoing else other}@host>\r\nCSeq: {cseq} {method}\r\n\r\n"
        f"c=IN IP4 10.1.1.1\r\nm=audio {port} RTP/AVP 0 13 101\r\n"
        "a=rtpmap:0 PCMU/8000\r\na=rtpmap:13 CN/8000\r\n"
        "a=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
    ).encode()


def channel(name, bridge, state="Up"):
    return "!".join(
        [name, "c", "s", "1", state, "Dial", "data", "caller", "", "", "3", "12", bridge, "id"]
    )


class TestMedia(unittest.TestCase):
    def setup_call(self):
        e = Evidence([PBX], ["30101", "30199"])
        e.complete = True
        for cid, ext, port in [("site", "30101", 11082), ("guard", "30199", 14738)]:
            e.packet(1, PBX, 5060, "10.1.1.1", 5060, sip(cid, ext, "999", port=port))
            e.packet(
                2, "10.1.1.1", 5060, PBX, 5060, sip(cid, ext, "999", response=True, port=11900)
            )
            e.packet(3, PBX, 5060, "10.1.1.1", 5060, sip(cid, ext, "999", method="ACK", port=port))
        return e

    def rtp(self, e, at, port, direction, seq, pt=0):
        p = struct.pack("!BBHII", 128, pt, seq, seq * 160, port) + b"x" * 12
        args = ("10.1.1.1", 11900, PBX, port) if direction == 0 else (PBX, port, "10.1.1.1", 11900)
        e.packet(at, *((*args, p)))

    def test_absent_intercom_voice_and_comfort_noise(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        for seq in range(200):
            self.rtp(e, 5, 14738, 0, seq)
            self.rtp(e, 5, 11082, 1, seq)
            self.rtp(e, 5, 14738, 1, seq, 13)
        r = e.report_calls(25)
        site = next(x for x in r if x["extension"] == "30101")
        self.assertEqual(
            site["voice_packets"],
            {"site_rx": 0, "site_tx": 200, "operator_rx": 200, "operator_tx": 0},
        )
        self.assertTrue(site["capture_complete"])
        self.assertEqual(site["evidence_kind"], "passive_bridge_transport_v1")
        self.assertEqual(site["peer_extension"], "30199")
        self.assertIsNone(site["known_mute"])
        self.assertIsNone(site["connected_operator"])
        self.assertFalse(site["capture_dropped"])
        self.assertTrue(site["dtmf_excluded"])
        self.assertTrue(site["comfort_noise_excluded"])

    def test_unanswered_or_no_actual_bridge_does_not_report(self):
        e = self.setup_call()
        self.rtp(e, 5, 14738, 0, 1)
        self.assertEqual(e.report_calls(25), [])

    def test_duplicates_and_dtmf_excluded(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        for _i in range(3):
            self.rtp(e, 5, 11082, 0, 1)
        self.rtp(e, 5, 11082, 0, 2, 101)
        r = e.report_calls(25)
        self.assertEqual(
            next(x for x in r if x["extension"] == "30101")["voice_packets"]["site_rx"], 1
        )

    def test_drop_invalidates_window(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        e.complete = False
        self.assertFalse(e.report_calls(25)[0]["capture_complete"])

    def test_capture_loss_discards_dialogs_and_buffered_packets(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        e.capture_health(False, 10)
        e.packet(9, PBX, 5060, "10.1.1.1", 5060, sip("old", "30101", "999"))
        self.assertEqual(e.dialogs, {})
        e.capture_health(True, 30)
        self.assertEqual(e.report_calls(35), [])
        e.packet(31, PBX, 5060, "10.1.1.1", 5060, sip("new", "30101", "999"))
        self.assertIn("new", e.dialogs)

    def test_reinvite_hold_invalidates_window(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        e.packet(5, PBX, 5060, "10.1.1.1", 5060, sip("site", "30101", "999", cseq=2))
        self.assertFalse(e.report_calls(25)[0]["capture_complete"])

    def test_source_comfort_noise_is_not_missing_media(self):
        e = self.setup_call()
        e.confirm([("30101", "30199")], 4)
        for seq in range(200):
            self.rtp(e, 5, 14738, 0, seq)
            self.rtp(e, 5, 11082, 0, seq, 13)
        self.assertFalse(e.report_calls(25)[0]["capture_complete"])

    def test_auth_challenge_retry_is_not_reinvite(self):
        e = Evidence([PBX], ["30101"])
        e.complete = True
        e.packet(1, PBX, 5060, "10.1.1.1", 5060, sip("site", "30101", "999", cseq=1))
        e.packet(2, PBX, 5060, "10.1.1.1", 5060, sip("site", "30101", "999", cseq=2))
        self.assertTrue(e.dialogs["site"]["valid"])

    def test_late_capture_response_cannot_create_dialog(self):
        e = Evidence([PBX], ["30101"])
        e.complete = True
        e.packet(1, "10.1.1.1", 5060, PBX, 5060, sip("site", "30101", "999", response=True))
        self.assertEqual(e.dialogs, {})

    def test_distinct_bridges_require_local_connection(self):
        a = "a" * 8 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 12
        b = a.replace("a", "b")
        rows = [channel("PJSIP/30101-abcd", a), channel("PJSIP/105-cdef", b)]
        self.assertEqual(bridge_pairs("\n".join(rows)), [])
        rows.extend(
            [channel("Local/105@from-queue-abc;1", a), channel("Local/105@from-queue-abc;2", b)]
        )
        self.assertEqual(bridge_pairs("\n".join(rows)), [("30101", "105")])

    def test_ringing_is_not_bridged_media(self):
        a = "a" * 8 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 12
        self.assertEqual(
            bridge_pairs(
                "\n".join([channel("PJSIP/30101-abcd", a), channel("PJSIP/105-cdef", a, "Ringing")])
            ),
            [],
        )


class TestCaptureStats(unittest.TestCase):
    def sample(self, stats, drops):
        class Proc:
            def send_signal(self, unused):
                if drops is not None:
                    stats.record(drops)

        return stats.sample(Proc(), timeout=0.001)

    def test_historical_drops_do_not_poison_future_intervals(self):
        s = CaptureStats()
        self.assertFalse(self.sample(s, 6088148)[0])
        healthy, _, delta = self.sample(s, 6088148)
        self.assertTrue(healthy)
        self.assertEqual(delta, 0)
        self.assertFalse(self.sample(s, 6088149)[0])
        self.assertTrue(self.sample(s, 6088149)[0])

    def test_missing_fresh_stats_requires_new_baseline(self):
        s = CaptureStats()
        self.sample(s, 0)
        self.assertTrue(self.sample(s, 0)[0])
        self.assertFalse(self.sample(s, None)[0])
        self.assertFalse(self.sample(s, 0)[0])
        self.assertTrue(self.sample(s, 0)[0])

    def test_counter_reset_does_not_certify_window(self):
        s = CaptureStats()
        self.sample(s, 100)
        self.assertFalse(self.sample(s, 0)[0])
        self.assertTrue(self.sample(s, 0)[0])


if __name__ == "__main__":
    unittest.main()


def test_queue_file_missing_is_unknown(tmp_path):
    result = queue_evidence(str(tmp_path / "missing"), ["4301"], 1000)
    assert result["complete"] is False
    assert result["short_answered_calls_5m"] == {}


def test_queue_file_short_answered_calls(tmp_path):
    path = tmp_path / "queue_log"
    path.write_text(
        "600|NONE|NONE|NONE|QUEUESTART\n940|1.1|99|NONE|ENTERQUEUE||4301|1\n"
        "945|1.1|99|operator|CONNECT|5|other|1\n"
        "950|1.1|99|operator|COMPLETEAGENT|5|5|1\n"
    )
    result = queue_evidence(str(path), ["4301"], 1000)
    assert result["complete"] is True
    assert result["short_answered_calls_5m"] == {"4301": 1}


def test_guard_evidence_only_certifies_fresh_approved_destinations(tmp_path):
    status = tmp_path / "status.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"approved": [{"extension": "4301"}]}))
    value = {"at": 1000, "approved_count": 1, "alerts": [], "cloud_peer_handshake_age": 30}
    status.write_text(json.dumps(value))
    assert route_evidence(status, manifest, ["4301", "999"], 1000) == {"4301": True, "999": None}
    value["alerts"] = [["4301", "saved_peer_drift"]]
    status.write_text(json.dumps(value))
    assert route_evidence(status, manifest, ["4301"], 1000) == {"4301": False}
    assert route_evidence(status, manifest, ["4301"], 1091) == {"4301": None}
    value["alerts"] = [["4301", "registration_unavailable"]]
    status.write_text(json.dumps(value))
    assert route_evidence(status, manifest, ["4301"], 1000) == {"4301": None}


def test_bridge_can_anchor_legs_using_different_pbx_tunnel_addresses():
    other_pbx = "10.253.250.11"
    evidence = Evidence([PBX, other_pbx], ["4301", "110"])
    evidence.complete = True
    for cid, ext, address, port in [
        ("site", "4301", PBX, 11082),
        ("guard", "110", other_pbx, 14738),
    ]:
        evidence.packet(1, address, 5060, "10.1.1.1", 5060, sip(cid, ext, "999", port=port))
        evidence.packet(2, "10.1.1.1", 5060, address, 5060, sip(cid, ext, "999", response=True))
        evidence.packet(3, address, 5060, "10.1.1.1", 5060, sip(cid, ext, "999", method="ACK"))
    evidence.confirm([("4301", "110")], 4)
    for address, port in [(PBX, 11082), (other_pbx, 14738)]:
        for seq in range(100):
            payload = struct.pack("!BBHII", 128, 0, seq, seq * 160, port) + b"x" * 12
            evidence.packet(5, "10.1.1.1", 11900, address, port, payload)
            evidence.packet(5, address, port, "10.1.1.1", 11900, payload)
    site = next(row for row in evidence.report_calls(25) if row["extension"] == "4301")
    assert site["capture_complete"] is True
    assert site["peer_extension"] == "110"
    assert set(site["voice_packets"].values()) == {100}
