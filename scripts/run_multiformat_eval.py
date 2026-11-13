"""Run the multi-format question set through the chat and save a log.

    python -m scripts.run_multiformat_eval [--label NAME]

Uses MultiFormatChat directly (deterministic, no model call). A question the
multi-format chat does not take is logged as route "odi_path": in the app it
would fall through to the ODI chat. Writes
tests/evals/results/multiformat/<label>/answers.json and answers.md so a later
run can be compared with this one.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import yaml

from backend.app.multiformat.chat import MultiFormatChat, detect_scope
from backend.app.multiformat.service import MultiFormatService

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "tests" / "evals" / "multiformat_questions_100.yaml"
DB = ROOT / "data" / "cricket_all.duckdb"
OUT = ROOT / "tests" / "evals" / "results" / "multiformat"


def run(
    label: str, split: str = "dev", model: str | None = None, offline: bool = False
) -> Path:
    questions = yaml.safe_load(QUESTIONS.read_text())
    questions = [q for q in questions if split == "all" or q.get("split") == split]
    chat = MultiFormatChat(MultiFormatService(DB))
    if model:
        from concurrent.futures import ThreadPoolExecutor
        from backend.app.config import AppConfig
        from backend.app.services.gemini_client import GeminiClient
        from backend.app.multiformat.model_planner import GeminiPlanner

        config = AppConfig.from_env()
        client = GeminiClient(config.gemini_api_key, model, model, timeout_seconds=90)
        chat.reader = GeminiPlanner(
            client, model, chat.planner, OUT / "planner-cache", offline=offline
        )
        if not offline:
            # Each distinct prompt is paid at most once. Execute and grade all
            # subsequent iterations from the durable capture.
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(chat.reader.read, [q["question"] for q in questions]))
            chat.reader.offline = True
    records = []
    for q in questions:
        started = time.perf_counter()
        answer = chat.answer(q["question"])
        records.append(
            {
                **q,
                "route": "multiformat" if answer else "odi_path",
                "scope": (
                    [s["label"] for s in answer.plan["scopes"]]
                    if answer and answer.plan
                    else None
                ),
                "planner": model or "deterministic",
                "plan": answer.plan if answer else None,
                "validation_changes": answer.validation_changes if answer else [],
                "query_response": (
                    answer.query_response.model_dump(mode="json")
                    if answer and answer.query_response
                    else None
                ),
                "clarification": bool(answer and answer.clarification),
                "answer": answer.message if answer else None,
                "suggestions": answer.suggestions if answer else [],
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
    folder = OUT / label
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "answers.json").write_text(json.dumps(records, indent=2, default=str))
    md = [f"# Multi-format question run `{label}`", ""]
    for r in records:
        md += [
            f"## {r['id']} · {r['category']}",
            f"**Q:** {r['question']}",
            f"**Expect:** {r['expect']}",
            f"**Route:** {r['route']} · scope: {r['scope']}",
            "",
            "```",
            r["answer"] or "(not answered here)",
            "```",
            "",
        ]
    (folder / "answers.md").write_text("\n".join(md))
    if not (folder / "grading.md").exists():
        (folder / "grading.md").write_text(
            f"# {label}\n\nSplit: {split}. Planner: {model or 'deterministic'}.\n\nIndependent grading pending; no pass count claimed.\n"
        )
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default=datetime.now().strftime("%Y-%m-%d-baseline"))
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument("--model", default=None)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    print(run(args.label, args.split, args.model, args.offline))
