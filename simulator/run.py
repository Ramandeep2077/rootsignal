"""Simulator CLI.

python simulator/run.py --list
python simulator/run.py --scenario db_pool_exhaustion
python simulator/run.py --scenario db_pool_exhaustion --dry-run     # simulate only, no DB/HTTP
python simulator/run.py --all                                       # every scenario, waiting for analysis
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from oncall_sim.engine import simulate
from oncall_sim.runner import run_scenario, wait_for_analysis
from oncall_sim.scenarios import SCENARIOS, get_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate labelled incident scenarios for oncall-copilot")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--scenario", help="scenario name (see --list)")
    target.add_argument("--all", action="store_true", help="run every scenario sequentially")
    target.add_argument("--list", action="store_true", help="list scenarios")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--burst-seconds", type=float, default=12.0, help="wall-clock time to replay the alert storm"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="simulate and summarise without writing anywhere"
    )
    parser.add_argument("--wait", action="store_true", help="wait for agent analysis (implied by --all)")
    parser.add_argument("--no-wait", action="store_true", help="with --all, don't wait between scenarios")
    parser.add_argument(
        "--timeout", type=float, default=900.0, help="seconds to wait for analysis per scenario"
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args(argv)

    if args.list:
        for name, scenario in sorted(SCENARIOS.items()):
            print(f"{name:24s} {scenario.title}")
        return 0

    names = sorted(SCENARIOS) if args.all else [args.scenario]
    try:
        for name in names:
            get_scenario(name)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    if args.dry_run:
        for name in names:
            out = simulate(get_scenario(name), seed=args.seed)
            print(
                f"{name}: {len(out.alerts)} alerts {dict(Counter(a.service for a in out.alerts))}, "
                f"{len(out.logs)} log lines, {len(out.metrics)} metric points, {len(out.changes)} changes"
            )
        return 0

    wait = (args.wait or args.all) and not args.no_wait
    results = []
    for name in names:
        result = run_scenario(name, seed=args.seed, burst_seconds=args.burst_seconds)
        record = result.to_dict()
        if wait:
            incidents = wait_for_analysis(
                result.run_id, expected_alerts=len(result.alert_ids), timeout=args.timeout
            )
            record["incidents"] = [{k: str(v) for k, v in i.items()} for i in incidents]
        results.append(record)
        if not args.json:
            print(
                f"[{name}] run_id={result.run_id} posted {len(result.alert_ids)} alerts "
                f"across {result.alerts_by_service}"
                + (f" -> {len(record['incidents'])} incident(s)" if wait else "")
            )
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
