"""Evaluation CLI.

    python -m rootsignal_evals.run --runs 3                                   # default profiles, all scenarios
    python -m rootsignal_evals.run --profiles routed=3,small_only=2,heuristic=3
    python -m rootsignal_evals.run --scenarios db_pool_exhaustion,dns_failure --runs 1 --no-judge
    python -m rootsignal_evals.run --report-only                              # rebuild EVALS.md from recorded runs

Runs are appended to a JSONL file as they finish, so an interrupted eval resumes where it stopped.
The dockerised agent-service must be stopped first (`make eval` does this): the harness runs its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from rootsignal_agent.llm.ollama import OllamaChat
from rootsignal_agent.llm.router import ModelRouter
from rootsignal_agent.routing import load_routing
from rootsignal_agent.settings import AgentSettings
from rootsignal_evals.guardrail_suite import run_suite
from rootsignal_evals.harness import Harness, load_records
from rootsignal_evals.report import render
from rootsignal_sim.scenarios import SCENARIOS

EVALS_DIR = Path(__file__).resolve().parents[2]
RESULTS = EVALS_DIR / "results"
log = logging.getLogger("rootsignal_evals")


def parse_profiles(value: str, default_runs: int) -> list[tuple[str, int]]:
    profiles = []
    for part in value.split(","):
        name, _, runs = part.strip().partition("=")
        profiles.append((name, int(runs) if runs else default_runs))
    return profiles


def environment(results_file: Path) -> dict[str, str]:
    settings = AgentSettings()
    try:
        shown = results_file.resolve().relative_to(EVALS_DIR.parent).as_posix()
    except ValueError:
        shown = str(results_file)
    env = {"date": datetime.now(UTC).strftime("%Y-%m-%d"), "results_file": shown}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        env["Git commit"] = commit.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    env["Machine"] = f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}"
    try:
        import psutil  # optional

        env["RAM"] = f"{psutil.virtual_memory().total / 2**30:.1f} GB"
    except ImportError:
        pass
    try:
        version = httpx.get(f"{settings.ollama_base_url}/api/version", timeout=5).json()["version"]
        models = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json()["models"]
        env["Ollama"] = f"{version} (Vulkan iGPU offload enabled)"
        env["Models"] = ", ".join(
            f"{m['name']} ({m['details'].get('quantization_level', '?')})"
            for m in models
            if m["name"].startswith("qwen")
        )
    except (httpx.HTTPError, KeyError):
        env["Ollama"] = "unreachable"
    env["Embeddings"] = f"{settings.embeddings_provider}: {settings.embeddings_model}"
    env["Grouping"] = (
        f"similarity >= {settings.similarity_threshold}, quiet {settings.triage_quiet_seconds:g} s, "
        f"window {settings.triage_window_seconds:g} s"
    )
    env["Guardrails"] = (
        f"min confidence {settings.min_confidence_for_action}, dry run {settings.remediation_dry_run}"
    )
    return env


async def main_async(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else RESULTS / "runs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    guardrails_file = out.with_name(out.stem + "-guardrails.json")

    if not args.report_only:
        try:
            if httpx.get("http://localhost:8000/health", timeout=2).status_code == 200:
                print(
                    "The dockerised agent-service is running and would also consume the alerts. "
                    "Stop it first: docker compose stop agent-service (make eval does this).",
                    file=sys.stderr,
                )
                return 2
        except httpx.HTTPError:
            pass
        scenarios = sorted(SCENARIOS) if args.scenarios == "all" else args.scenarios.split(",")
        if args.guardrails:
            settings = AgentSettings(llm_provider="ollama")
            router = ModelRouter(load_routing(settings, "routed"), OllamaChat(settings.ollama_base_url))
            log.info("running guardrail suite (static + live prompt injection)")
            guardrails_file.write_text(json.dumps(await run_suite(router), indent=2), encoding="utf-8")
        harness = Harness(out=out, timeout=args.timeout, use_judge=args.judge)
        try:
            for profile, runs in parse_profiles(args.profiles, args.runs):
                log.info("profile %s: %d run(s) x %d scenarios", profile, runs, len(scenarios))
                await harness.run_profile(profile, scenarios, runs)
        finally:
            await harness.aclose()

    records = load_records(out)
    guardrails = json.loads(guardrails_file.read_text(encoding="utf-8")) if guardrails_file.exists() else None
    report = render(records, guardrails, environment(out))
    report_path = Path(args.report) if args.report else EVALS_DIR / "EVALS.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"wrote {report_path} from {len(records)} runs")
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("httpx", "aiokafka", "mcp", "rootsignal_agent.service"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="rootsignal evaluation suite")
    parser.add_argument(
        "--profiles",
        default="routed,small_only,heuristic",
        help="comma list, optionally name=runs (e.g. routed=3,heuristic=3)",
    )
    parser.add_argument("--runs", type=int, default=3, help="seeds per scenario (default for --profiles)")
    parser.add_argument("--scenarios", default="all")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds per run")
    parser.add_argument("--out", help="JSONL results file (default evals/results/runs.jsonl)")
    parser.add_argument("--no-judge", dest="judge", action="store_false")
    parser.add_argument("--no-guardrails", dest="guardrails", action="store_false")
    parser.add_argument("--report", help="where to write the markdown report (default evals/EVALS.md)")
    parser.add_argument("--report-only", action="store_true")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
