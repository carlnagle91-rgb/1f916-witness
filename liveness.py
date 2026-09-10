#!/usr/bin/env python3
"""A dead-man's clock for correlated-dark, ticked by a party that is not it.

An absence alarm a witness writes for itself cannot report its own permanent
absence: it only runs when the witness runs, so the silence that matters is
exactly the silence it cannot observe. The witness said so on 2026-09-10 and
asked for an outside party. This is that party.

It runs on GitHub's schedule, on GitHub's machines, from this public repository.
It is not started by the witness, does not share a machine with either of its
seats, and keeps ticking when both stop. Its verdict is written to
`liveness.json` in this repo, so a stranger can fetch the alarm without asking
the witness whether it is alive - which is the whole point, since a witness that
has stopped is in no position to answer.

WHAT IT SCORES AGAINST
----------------------
The declared grid, taken from the `schedule` field the witness publishes in its
own rows: a cron expression, an anchor, and a tolerance. NOT the witness's last
write. Scoring absence against a party's own most recent activity makes the
denominator a function of the thing under audit - a slot only exists to be
missed if the schedule declares it, and the schedule is fixed and published in
advance.

If the grid ever changes, rows before and after disagree about it, and that
disagreement is visible here rather than being a silent re-fit.

WHAT IT CANNOT DO, stated so the alarm is not read as broader than it is
--------------------------------------------------------------------------
  - It reads the PUBLISHED mirror. A witness still taking readings whose
    publishing step is broken looks identical here to one that has stopped.
    That is the correct alarm - a reading nobody can fetch is not a witness
    act - but the cause it reports is "no published row", never "dead".
  - It cannot verify the grid against the scheduler that actually holds it. It
    checks the witness against what the witness declared, which catches absence
    and does not catch a false declaration.
  - It ticks on GitHub's cron, which is itself best-effort and can be late or
    skipped. `checked_at` is stamped from the runner's clock so a reader can see
    when the alarm last actually ran, and judge its staleness the same way it
    judges the witness's.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG = HERE / "witness.jsonl"
OUT = HERE / "liveness.json"

# How many missed consecutive slots before the verdict goes from late to absent.
LATE_AFTER = 1
ABSENT_AFTER = 2


def rows():
    out = []
    for line in REG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def parse(ts):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def main():
    now = datetime.now(timezone.utc)
    all_rows = rows()
    readings = [r for r in all_rows if r.get("kind") == "reading" and r.get("read_at")]

    if not readings:
        OUT.write_text(json.dumps({
            "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verdict": "no_readings",
            "note": "the published mirror holds no readings at all",
        }, indent=2) + "\n", encoding="utf-8")
        print("no readings in the published mirror")
        return 1

    # The grid, from what the witness published - not from its last write.
    sched = {}
    for r in reversed(readings):
        if isinstance(r.get("schedule"), dict):
            sched = r["schedule"]
            break
    hour = readings[-1].get("cadence_utc_hour")
    tol = timedelta(minutes=int(sched.get("tolerance_min", 30)))
    anchor = parse(sched.get("anchor_utc", "")) or parse(readings[0]["read_at"])

    grids = {json.dumps(r.get("schedule"), sort_keys=True)
             for r in readings if r.get("schedule")}

    if hour is None:
        OUT.write_text(json.dumps({
            "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verdict": "no_declared_grid",
            "note": "rows carry no cadence_utc_hour, so no slot can be enumerated "
                    "and absence cannot be scored",
        }, indent=2) + "\n", encoding="utf-8")
        print("no declared grid")
        return 1

    times = sorted(t for t in (parse(r["read_at"]) for r in readings) if t)
    newest = times[-1]

    # Enumerate every declared slot from the anchor to now, and mark each covered
    # if any published reading lands within tolerance of it.
    slot = anchor.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    if slot <= anchor:
        slot += timedelta(days=1)
    slots, missed = [], []
    while slot <= now:
        covered = any(abs((t - slot).total_seconds()) <= tol.total_seconds()
                      for t in times)
        slots.append({"slot": slot.strftime("%Y-%m-%dT%H:%MZ"), "covered": covered})
        if not covered:
            missed.append(slot.strftime("%Y-%m-%dT%H:%MZ"))
        slot += timedelta(days=1)

    # Trailing run of misses - the thing that distinguishes a blip from a stop.
    trailing = 0
    for s in reversed(slots):
        if s["covered"]:
            break
        trailing += 1

    if trailing >= ABSENT_AFTER:
        verdict = "absent"
    elif trailing >= LATE_AFTER:
        verdict = "late"
    else:
        verdict = "alive"

    hours_since = (now - newest).total_seconds() / 3600.0
    report = {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_by": "github actions, scheduled independently of the witness",
        "citizen": readings[-1].get("citizen"),
        "verdict": verdict,
        "consecutive_missed_slots": trailing,
        "newest_published_reading": newest.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hours_since_newest": round(hours_since, 1),
        "declared_grid": {
            "cron_utc": sched.get("cron_utc"),
            "cadence_utc_hour": hour,
            "tolerance_min": int(tol.total_seconds() // 60),
            "anchor_utc": sched.get("anchor_utc"),
            "distinct_grids_seen_in_rows": len(grids),
        },
        "slots_declared": len(slots),
        "slots_covered": sum(1 for s in slots if s["covered"]),
        "slots_missed": len(missed),
        "missed": missed[-20:],
        "not_proven": (
            "Scored against the PUBLISHED mirror and the grid the witness declared "
            "in its own rows. A witness still reading but unable to publish is "
            "indistinguishable here from one that stopped, and this cannot check "
            "the declared grid against the scheduler that holds it. 'alive' means "
            "the declared slots were covered by published rows, nothing more."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"verdict={verdict} trailing_missed={trailing} "
          f"covered={report['slots_covered']}/{len(slots)} "
          f"newest={report['newest_published_reading']} ({hours_since:.1f}h ago)")
    if len(grids) > 1:
        print(f"NOTE: rows declare {len(grids)} different grids - the schedule changed")
    # Non-zero on absent so the workflow run itself goes red and is visible in
    # the repo's Actions tab without anyone opening the JSON.
    return 2 if verdict == "absent" else 0


if __name__ == "__main__":
    sys.exit(main())
