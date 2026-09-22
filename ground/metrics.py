"""The frozen metric definitions, re-exported.

They live in research/frozen_metrics.py now, because charter section 6.1 makes the ruler read-only for the
experiment loop while everything under ground/ is the mutable surface the loop is allowed to edit. A metric
the loop could edit is not a metric. Nothing forked: this module is the same objects under the old name, so
tools/replay.py, tools/run_report.py, tools/churn_check.py, tools/compare_runs.py and ground/after_action.py
keep working unchanged.

It is loaded by path rather than by putting research/ on sys.path, so importing metrics in a pilot process
does not also put the grader within reach (honesty test 6).
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "frozen_metrics.py")
_spec = importlib.util.spec_from_file_location("doomsat_frozen_metrics", _PATH)
_frozen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_frozen)
globals().update({k: v for k, v in vars(_frozen).items() if not k.startswith("__")})
