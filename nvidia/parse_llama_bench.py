"""Pure validation of the pinned llama-bench JSON schema."""

import json
import math
import re


def parse(data):
    rows = json.loads(data)
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError("expected a nonempty array of result objects")
    return rows


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_row(row, expect):
    for key, want in expect.items():
        if key.endswith("_contains"):
            if want not in str(row.get(key[:-9], "")):
                raise ValueError(key + " mismatch")
        elif row.get(key) != want:
            raise ValueError(key + " mismatch")
    for field in ("avg_ts", "avg_ns", "stddev_ts", "stddev_ns"):
        value = row.get(field)
        if not finite(value) or value < 0 or (field.startswith("avg_") and value == 0):
            raise ValueError(field + " invalid")


def evaluate(packet, stdout_text, stderr_text, rc, xid_before, xid_after):
    failures = []
    if rc != 0:
        failures.append("nonzero exit: " + str(rc))
    if re.search(r"device[ _]?lost|errordevice|vk_error|out of memory", stdout_text + stderr_text, re.I):
        failures.append("device failure diagnostic")
    if xid_before is None or xid_after is None or xid_after != xid_before:
        failures.append("Xid gate failed or unavailable")
    for needle in packet["expect"]["stderr_contains"]:
        if needle not in stderr_text:
            failures.append("missing physical device diagnostic: " + needle)
    try:
        rows = parse(stdout_text)
        if len(rows) != packet["expect"]["rows"]:
            raise ValueError("unexpected result count")
        repetitions = int(packet["input"]["argv"][packet["input"]["argv"].index("-r") + 1])
        for row in rows:
            check_row(row, packet["expect"]["row"])
            commit = row.get("build_commit", "")
            if (
                not isinstance(commit, str)
                or not re.fullmatch("[0-9a-f]{7,40}", commit)
                or not packet["binary"]["source_commit"].startswith(commit)
            ):
                raise ValueError("build commit mismatch")
            for field in ("samples_ns", "samples_ts"):
                samples = row.get(field)
                if (
                    not isinstance(samples, list)
                    or len(samples) != repetitions
                    or not all(finite(x) and x > 0 for x in samples)
                ):
                    raise ValueError(field + " incomplete or invalid")
    except (ValueError, KeyError, TypeError) as error:
        failures.append(str(error))
    return failures
