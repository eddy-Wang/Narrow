from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise SystemExit("OPENAI_API_KEY is empty")
    os.environ["SHOPPING_AGENT_ENABLE_LLM"] = "true"

    # Import after loading the provider settings so graph construction and every
    # evaluator turn observe the same process environment.
    from evaluator.local_evaluator import main as evaluator_main

    evaluator_main()


if __name__ == "__main__":
    main()
