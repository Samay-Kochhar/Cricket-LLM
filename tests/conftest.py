from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)

if root_str not in sys.path:
    sys.path.insert(0, root_str)


# The AI investigation is never enabled in tests (no network, no paid calls),
# and questions saved as unanswered go to a temporary file, not data/.
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ["MULTIFORMAT_INVESTIGATION_MODEL"] = "off"
os.environ.setdefault(
    "UNANSWERED_BACKLOG_PATH",
    str(Path(tempfile.mkdtemp(prefix="cricatlas-backlog-")) / "unanswered_questions.jsonl"),
)
