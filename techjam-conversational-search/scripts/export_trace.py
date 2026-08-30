"""Export an existing evaluation to trace.json without calling models."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluator.trace_export import main

if __name__ == "__main__":
    main()
