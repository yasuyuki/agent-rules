import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("environment_detector_tests",
    Path(__file__).parents[1] / "skills/verify-agent-environment/scripts/test_verify.py")
tests = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tests)


class DetectorTest(tests.DetectorTest):
    pass


if __name__ == "__main__":
    unittest.main()
