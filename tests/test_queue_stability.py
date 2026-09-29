import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "queue_stability", Path(__file__).parents[1] / "tools/pbx_media/queue_stability.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
summarize_queue_calls = _module.summarize_queue_calls


def call(cid, at, duration, ext="4301"):
    return "\n".join(
        [
            f"{at - duration - 2}|{cid}|99|NONE|ENTERQUEUE||{ext}|1",
            f"{at - duration}|{cid}|99|operator|CONNECT|2|other|1",
            f"{at}|{cid}|99|operator|COMPLETECALLER|2|{duration}|1",
        ]
    )


def test_short_calls_deduplicate_and_ignore_long_unanswered_and_other_extensions():
    text = "600|NONE|NONE|NONE|QUEUESTART\n" + "\n".join(
        [
            call("1.1", 950, 4),
            call("1.1", 950, 4),
            call("1.2", 960, 45),
            call("1.3", 970, 2, "999"),
            "975|1.4|99|NONE|ABANDON|1|1|3",
        ]
    )
    result = summarize_queue_calls(text, ["4301"], 1000, True)
    assert result["short_answered_calls_5m"] == {"4301": 1}


def test_partial_window_is_unknown_not_zero_or_fault():
    result = summarize_queue_calls(call("1.1", 950, 4), ["4301"], 1000)
    assert result["complete"] is False
    assert result["short_answered_calls_5m"] == {}


def test_complete_window_and_old_calls():
    text = call("1.0", 600, 4) + "\n" + call("1.1", 950, 4)
    assert summarize_queue_calls(text, ["4301"], 1000)["short_answered_calls_5m"] == {"4301": 1}


def test_invalid_duration_prevents_false_healthy_result():
    text = call("1.1", 950, 4).replace("COMPLETECALLER|2|4", "COMPLETECALLER|2|bad")
    assert not summarize_queue_calls(text, ["4301"], 1000, True)["complete"]


def test_size_bound():
    with pytest.raises(ValueError):
        summarize_queue_calls("x" * (2 * 1024 * 1024 + 1), ["4301"], 1000)
