import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/verify-funkot-player/scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# test_verify.py imports its sibling as `verify`; other skills also ship a verify.py.
_previous = sys.modules.get("verify")
sys.modules["verify"] = _load("funkot_player_verify", SCRIPTS / "verify.py")
try:
    tests = _load("funkot_player_verify_tests", SCRIPTS / "test_verify.py")
finally:
    if _previous is None:
        sys.modules.pop("verify")
    else:
        sys.modules["verify"] = _previous


class EvidenceTests(tests.EvidenceTests):
    pass


if __name__ == "__main__":
    unittest.main()
