"""Bounded Asterisk queue evidence; short calls are symptoms, not hangup causes.

Kept compatible with the deployed Python 2 collector. No I/O, audio, SIP auth,
caller names, or destination addresses are returned.
"""

import math
import re

MAX_TEXT = 2 * 1024 * 1024
WINDOW_SECONDS = 300
SHORT_SECONDS = 10


def summarize_queue_calls(text, expected, now, starts_at_beginning=False):
    if len(text) > MAX_TEXT or (math.isnan(float(now)) or math.isinf(float(now))):
        raise ValueError("Invalid queue evidence bound")
    cutoff = now - WINDOW_SECONDS
    parsed = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            at = int(parts[0])
        except ValueError:
            continue
        if at > now + 30:
            continue
        parsed.append((at, parts))
    # Even a complete file may have just rotated; require five minutes of history.
    complete = any(at <= cutoff for at, _ in parsed)
    expected = set(expected)
    owners = {}
    answered = set()
    ended = {}
    for at, parts in parsed:
        event, call = parts[4], parts[1]
        if not re.match(r"^[0-9.]{1,64}$", call):
            continue
        if event == "ENTERQUEUE" and len(parts) > 6 and re.match(r"^[0-9]{1,64}$", parts[6]):
            old = owners.get(call)
            owners[call] = parts[6] if old in (None, parts[6]) else ""
        elif event == "CONNECT":
            answered.add(call)
        elif event in ("COMPLETECALLER", "COMPLETEAGENT") and len(parts) > 6:
            try:
                duration = int(parts[6])
            except ValueError:
                complete = False
                continue
            if duration < 0:
                complete = False
                continue
            ended[call] = (at, duration)
    counts = dict((ext, 0) for ext in expected)
    for call, (at, duration) in ended.items():
        ext = owners.get(call)
        if cutoff < at <= now and (ext is None or call not in answered):
            complete = False
        if ext in counts and call in answered and cutoff < at <= now and duration <= SHORT_SECONDS:
            counts[ext] += 1
    return {
        "complete": complete,
        "window_seconds": WINDOW_SECONDS,
        "observed_at": now,
        "short_answered_calls_5m": counts if complete else {},
    }
