"""Offline release-regression test list for CricAtlas versions.

Paid Gemini runs are rare checkpoints. Every versioned change is instead
checked offline, with network access disabled, against a stable version:

* **Golden answers**: the verified answer fingerprint of every benchmark case
  (mode, status, failure state, tables, clarification options and answer
  numbers), recorded from a stable version.
* **Recorded corpora**: every saved production extraction (fresh Gemini runs)
  is replayed through the real chat/database path. A case that matched the
  golden answer at the stable version must still match.
* **Extraction variants**: recorded extractions are rewritten in ways the model
  has varied without changing meaning (typed operators, a restated subject
  filter, the role moved between fields, a generic dimension label). A variant
  may answer correctly or refuse safely; it must never answer wrongly.
* **Known limitations**: question families that are not answerable yet are
  listed with a note. They are reported for later work and do not block.
* **Contract drift**: when the extraction prompt/schema source differs from the
  source that produced the newest corpus, a small paid sample is recommended.

Commands (from the repository root, ``PYTHONPATH=.``):

    python -m scripts.release_regression check            # every versioned change
    python -m scripts.release_regression check --no-variants
    python -m scripts.release_regression record --stable-version <tag>   # new stable version only
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from backend.app.services.gemini_client import GeminiStructuredResult
from scripts.odi_correctness_gate import load_benchmark
from scripts.replay_planner_capture import captured_responses, replay_case

ROOT = Path(__file__).resolve().parents[1]
REGRESSION_DIR = ROOT / "tests" / "evals" / "regression"
MANIFEST = REGRESSION_DIR / "manifest.yaml"
GOLDEN = REGRESSION_DIR / "golden-answers.json"
BASELINE = REGRESSION_DIR / "stable-baseline.json"
LIMITATIONS = REGRESSION_DIR / "known-limitations.yaml"
CONTRACT_SOURCE = "backend/app/cricket_analytics/language_meaning.py"
TABLE_ROWS = 10


# --------------------------------------------------------------------------- #
# Offline guard
# --------------------------------------------------------------------------- #


def disable_network() -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network access is disabled during the release regression check")

    os.environ["GEMINI_API_KEY"] = ""
    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    socket.create_connection = blocked  # type: ignore[assignment]
    socket.getaddrinfo = blocked  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Answer fingerprints
# --------------------------------------------------------------------------- #

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")


def fingerprint(turn: dict[str, Any]) -> dict[str, Any]:
    """The comparable facts of one displayed answer."""
    response = turn.get("response") or {}
    evidence = turn.get("displayed_answer_evidence") or {}
    summaries = " ".join(str(item.get("body", "")) for item in evidence.get("summaries") or [])
    return {
        "mode": response.get("mode"),
        "status": response.get("status"),
        "failure_state": response.get("failure_state"),
        "clarification_options": list(evidence.get("clarification_options") or []),
        "tables": [
            {
                "title": table.get("title"),
                "columns": table.get("columns"),
                "rows": (table.get("rows") or [])[:TABLE_ROWS],
            }
            for table in evidence.get("tables") or []
        ],
        "answer_numbers": sorted(set(NUMBER.findall(summaries))),
    }


def classify(actual: dict[str, Any], golden: dict[str, Any]) -> str:
    """match, safe_refusal (a non-answer where an answer is expected) or wrong."""
    if actual == golden:
        return "match"
    answered = actual["status"] == "supported" and actual["mode"] == "analysis"
    if not answered and golden["status"] == "supported":
        return "safe_refusal"
    return "wrong"


def case_outcome(turn_outcomes: list[str]) -> str:
    for outcome in ("wrong", "safe_refusal"):
        if outcome in turn_outcomes:
            return outcome
    return "match"


# --------------------------------------------------------------------------- #
# Meaning-preserving extraction variants
# --------------------------------------------------------------------------- #


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _subject(candidate: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            entity
            for entity in candidate.get("entities") or []
            if entity.get("kind") == "player" and entity.get("relationship") == "subject"
        ),
        None,
    )


def typed_operators(candidate: dict[str, Any]) -> bool:
    """Add the operator the filter's own values imply (the #37 extraction contract)."""
    changed = False
    for fact in candidate.get("filters") or []:
        values = fact.get("values") or []
        if fact.get("operator") or not values:
            continue
        if len(values) == 2 and all(_is_number(value) for value in values):
            fact["operator"] = "between"
        elif not any(_is_number(value) for value in values):
            fact["operator"] = "eq" if len(values) == 1 else "in"
        else:
            continue
        changed = True
    return changed


def restated_subject(candidate: dict[str, Any]) -> bool:
    """Repeat the extracted subject as a generic player filter."""
    subject = _subject(candidate)
    if subject is None:
        return False
    candidate.setdefault("filters", []).append(
        {"concept": "player", "evidence": subject["name"], "operator": "eq", "values": [subject["name"]]}
    )
    return True


def role_moved(candidate: dict[str, Any]) -> bool:
    """Move the requested role between the candidate and its subject entity."""
    subject = _subject(candidate)
    if subject is None:
        return False
    if candidate.get("role") and not subject.get("role"):
        subject["role"], candidate["role"] = candidate["role"], None
        return True
    if subject.get("role") and not candidate.get("role"):
        candidate["role"], subject["role"] = subject["role"], None
        return True
    return False


def generic_dimension_label(candidate: dict[str, Any]) -> bool:
    """Name the one requested split/breakdown axis with an unregistered label."""
    fields = [
        field
        for field in ("breakdown_dimensions", "split_dimensions")
        if candidate.get(field)
    ]
    if len(fields) != 1 or len(candidate[fields[0]]) != 1:
        return False
    candidate[fields[0]] = ["category"]
    return True


VARIANTS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "typed_operators": typed_operators,
    "restated_subject": restated_subject,
    "role_moved": role_moved,
    "generic_dimension_label": generic_dimension_label,
}


def mutate_responses(
    responses: list[GeminiStructuredResult], mutation: Callable[[dict[str, Any]], bool]
) -> list[GeminiStructuredResult] | None:
    """Apply a mutation to every language-meaning extraction; None if it never applies."""
    mutated: list[GeminiStructuredResult] = []
    applied = False
    for response in responses:
        try:
            candidate = json.loads(response.text or "")
        except json.JSONDecodeError:
            mutated.append(response)
            continue
        if not isinstance(candidate, dict) or "family" not in candidate or "version" not in candidate:
            mutated.append(response)
            continue
        candidate = copy.deepcopy(candidate)
        if mutation(candidate):
            applied = True
            response = dataclasses.replace(response, text=json.dumps(candidate))
        mutated.append(response)
    return mutated if applied else None


# --------------------------------------------------------------------------- #
# Manifest, corpora and contract drift
# --------------------------------------------------------------------------- #


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["case_id"]] = record
    return records


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contract_hash(revision: str | None = None) -> str | None:
    if revision is None:
        return sha256_text((ROOT / CONTRACT_SOURCE).read_text(encoding="utf-8"))
    try:
        source = subprocess.run(
            ["git", "show", f"{revision}:{CONTRACT_SOURCE}"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return sha256_text(source)


def contract_drift(manifest: dict[str, Any]) -> list[str]:
    current = contract_hash()
    newest = [
        corpus for corpus in manifest["corpora"]
        if corpus.get("recorded_at_revision")
    ]
    if not newest:
        return ["No corpus records the revision it was captured at."]
    latest = newest[-1]
    recorded = contract_hash(latest["recorded_at_revision"])
    if recorded != current:
        return [
            f"The extraction prompt/schema source ({CONTRACT_SOURCE}) changed since corpus "
            f"'{latest['name']}' was captured at {latest['recorded_at_revision']}. Recorded "
            "extractions may not reflect what the model now returns: run a small paid sample "
            "(for example the priority-8) once, with approval, and add it as a corpus."
        ]
    return []


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


def replay_corpus(
    corpus: dict[str, Any],
    *,
    mutation: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, dict[str, Any]]:
    """Replay a corpus (optionally mutated); return per-case turn fingerprints and scoring errors."""
    capture = ROOT / corpus["capture"]
    if not capture.exists():
        if corpus.get("optional"):
            print(f"[skip] {corpus['name']}: optional capture {corpus['capture']} is not present", flush=True)
            return {}
        raise FileNotFoundError(capture)
    benchmark = load_benchmark(ROOT / corpus["benchmark"])
    captured = load_records(capture)
    results: dict[str, dict[str, Any]] = {}
    for case in benchmark["cases"]:
        record = captured.get(case["id"])
        if record is None:
            continue
        responses = captured_responses(record)
        if mutation is not None:
            responses = mutate_responses(responses, mutation)
            if responses is None:
                continue
        try:
            replayed = replay_case(case, responses)
        except AssertionError as error:
            if "uncaptured model call" not in str(error):
                raise
            # The variant needs a model call that was never recorded (for
            # example a refinement): a cost signal, not an answer.
            results[case["id"]] = {"outcome": "needs_model_call", "error": str(error)}
            continue
        turns = replayed["turns"]
        results[case["id"]] = {
            "fingerprints": [fingerprint(turn) for turn in turns],
            "benchmark_errors": [error for turn in turns for error in turn.get("errors", [])],
        }
    return results


def golden_key(case_id: str) -> str:
    return case_id


def evaluate(
    results: dict[str, dict[str, Any]], golden: dict[str, list[dict[str, Any]]]
) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for case_id, result in results.items():
        if "outcome" in result:
            outcomes[case_id] = result["outcome"]
            continue
        expected = golden.get(golden_key(case_id))
        if expected is None or len(expected) != len(result["fingerprints"]):
            outcomes[case_id] = "no_golden"
            continue
        outcomes[case_id] = case_outcome(
            [classify(actual, wanted) for actual, wanted in zip(result["fingerprints"], expected)]
        )
    return outcomes


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def record(stable_version: str) -> int:
    """Record golden answers and the per-corpus baseline at a stable version."""
    manifest = load_yaml(MANIFEST)
    golden: dict[str, list[dict[str, Any]]] = {}
    intended = {item["case_id"]: item["reason"] for item in manifest.get("intended_changes", [])}
    unverified: list[str] = []
    for corpus in manifest["corpora"]:
        if not corpus.get("golden_source"):
            continue
        for case_id, result in replay_corpus(corpus).items():
            if result.get("outcome") or (result["benchmark_errors"] and case_id not in intended):
                unverified.append(case_id)
                continue
            golden[golden_key(case_id)] = result["fingerprints"]  # verified above
    baseline: dict[str, dict[str, str]] = {}
    for corpus in manifest["corpora"]:
        baseline[corpus["name"]] = evaluate(replay_corpus(corpus), golden)
    GOLDEN.write_text(
        json.dumps(
            {"stable_version": stable_version, "contract_sha256": contract_hash(), "cases": golden},
            indent=1, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    BASELINE.write_text(
        json.dumps({"stable_version": stable_version, "corpora": baseline}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded {len(golden)} golden answers for {stable_version}.")
    if unverified:
        print(f"Not recorded (fails its benchmark and is not an intended change): {sorted(unverified)}")
    for name, outcomes in baseline.items():
        print(f"  {name}: {dict(Counter(outcomes.values()))}")
    return 0


def check(*, variants: bool, corpus_names: set[str] | None, report_path: Path | None) -> int:
    manifest = load_yaml(MANIFEST)
    golden_file = json.loads(GOLDEN.read_text(encoding="utf-8"))
    golden = golden_file["cases"]
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["corpora"]
    limitations = {
        (item["case_id"], item.get("scope", "*")): item["note"]
        for item in (load_yaml(LIMITATIONS).get("limitations") or [])
    }

    def limited(case_id: str, scope: str) -> str | None:
        return limitations.get((case_id, scope)) or limitations.get((case_id, "*"))

    failures: list[str] = []
    backlog: list[str] = []
    report: dict[str, Any] = {
        "stable_version": golden_file["stable_version"],
        "revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "corpora": {},
        "variants": {},
    }
    corpora = [
        corpus for corpus in manifest["corpora"]
        if corpus_names is None or corpus["name"] in corpus_names
    ]
    for corpus in corpora:
        outcomes = evaluate(replay_corpus(corpus), golden)
        stable = baseline.get(corpus["name"], {})
        report["corpora"][corpus["name"]] = dict(Counter(outcomes.values()))
        print(f"[corpus] {corpus['name']}: {dict(Counter(outcomes.values()))}", flush=True)
        for case_id, outcome in sorted(outcomes.items()):
            note = limited(case_id, corpus["name"])
            if outcome == "wrong":
                failures.append(f"{corpus['name']}/{case_id}: wrong answer")
            elif outcome != "match" and stable.get(case_id) == "match":
                message = f"{corpus['name']}/{case_id}: regressed from match to {outcome}"
                (backlog if note else failures).append(message + (f" (known: {note})" if note else ""))
            elif outcome != "match":
                backlog.append(
                    f"{corpus['name']}/{case_id}: {outcome} (also at the stable version)"
                    + (f" (known: {note})" if note else "")
                )
    if variants:
        for name, mutation in VARIANTS.items():
            totals: Counter[str] = Counter()
            for corpus in corpora:
                if not corpus.get("variant_source"):
                    continue
                outcomes = evaluate(replay_corpus(corpus, mutation=mutation), golden)
                totals.update(outcomes.values())
                for case_id, outcome in sorted(outcomes.items()):
                    if outcome == "wrong":
                        failures.append(f"variant {name} {corpus['name']}/{case_id}: wrong answer")
                    elif outcome != "match":
                        note = limited(case_id, f"variant:{name}")
                        backlog.append(
                            f"variant {name} {corpus['name']}/{case_id}: {outcome}"
                            + (f" (known: {note})" if note else "")
                        )
            report["variants"][name] = dict(totals)
            print(f"[variant] {name}: {dict(totals)}", flush=True)
    drift = contract_drift(manifest)
    report.update({"failures": failures, "backlog": backlog, "contract_drift": drift})
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for line in drift:
        print(f"WARNING: {line}")
    print(f"Backlog (reported, not blocking): {len(backlog)}")
    for line in backlog:
        print(f"  - {line}")
    print(f"Failures: {len(failures)}")
    for line in failures:
        print(f"  - {line}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="Offline gate for a versioned change.")
    check_parser.add_argument("--no-variants", action="store_true")
    check_parser.add_argument("--corpus", action="append", help="Limit to named corpora.")
    check_parser.add_argument("--report", type=Path)
    record_parser = commands.add_parser("record", help="Record golden answers at a stable version.")
    record_parser.add_argument("--stable-version", required=True)
    args = parser.parse_args()
    logging.disable(logging.INFO)
    disable_network()
    if args.command == "record":
        return record(args.stable_version)
    return check(
        variants=not args.no_variants,
        corpus_names=set(args.corpus) if args.corpus else None,
        report_path=args.report,
    )


if __name__ == "__main__":
    sys.exit(main())
