"""Optional Gemini reading with durable, content-addressed offline replay."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from backend.app.multiformat.knowledge import knowledge_pack
from backend.app.multiformat.plans import UnderstandingPlan


class GeminiPlanner:
    def __init__(self, client, model, deterministic, cache_dir: Path, *, offline=False):
        self.client = client
        self.model = model
        self.deterministic = deterministic
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.pack = knowledge_pack(deterministic.names.competitions)

    def cache_path(self, question):
        key = sha256(
            (self.model + "\n" + self.pack + "\n" + question).encode()
        ).hexdigest()
        return self.cache_dir / self.model / (key + ".json")

    def read(self, question):
        gate = self.deterministic.read(question)
        if gate is None:
            return None
        path = self.cache_path(question)
        if path.exists():
            record = json.loads(path.read_text())
        elif self.offline:
            record = {"error": "missing offline capture"}
        else:
            candidates = []
            for hit in self.deterministic.names.spot(question):
                candidates.append(
                    {
                        "mention": hit[2],
                        "candidates": [
                            p["name"] for p in self.deterministic.names.choose(hit[2])
                        ],
                    }
                )
            result = self.client.generate_structured(
                self.pack
                + "\nDatabase name candidates: "
                + json.dumps(candidates)
                + "\nDatabase venue candidates: "
                + str(gate.venue or "")
                + "\nQuestion: "
                + question,
                response_schema=UnderstandingPlan.model_json_schema(),
                model_name=self.model,
                max_output_tokens=4096,
                thinking_level="low",
            )
            record = {
                "question": question,
                "model": self.model,
                "response": asdict(result),
            }
            try:
                record["plan"] = UnderstandingPlan.model_validate_json(
                    result.text or ""
                ).model_dump()
            except ValueError:
                record["error"] = result.error_kind or "invalid structured plan"
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(record, indent=2))
            temp.replace(path)
        if record.get("plan"):
            return UnderstandingPlan.model_validate(record["plan"])
        # No usable model reading exists. Choose the standard reader rather
        # than exposing transport errors as a cricket capability limitation.
        # Valid model plans, including unsupported requests, are never rewritten.
        return gate

    def diagnostic(self, question):
        path = self.cache_path(question)
        record = json.loads(path.read_text()) if path.exists() else {}
        if not record.get("plan"):
            return "The model reader was unavailable, so this answer uses the standard question reader. The displayed filters show its interpretation."
        return None
