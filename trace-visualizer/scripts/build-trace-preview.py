"""Compatibility entrypoint for the shared, versioned trace exporter."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "narrow-shopping-agent"))
from evaluator.trace_export import STAGES, build_payload, diagnosis, main, snapshot_stage

if __name__ == "__main__":
    main()
