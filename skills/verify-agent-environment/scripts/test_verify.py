import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("environment_verifier", Path(__file__).with_name("verify.py"))
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


@unittest.skipUnless(platform.system() == "Linux", "Verification recipe targets Linux")
class DetectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        repo = self.root / "environment"
        (repo / "examples/rulesync/sources/rules").mkdir(parents=True)
        (repo / "examples/rulesync/placement.json").write_text(json.dumps({
            "version": 1, "input_roots": ["sources"], "targets": ["codexcli", "claudecode", "grokcli"],
            "features": ["rules", "skills"], "output_root": "scratch/project", "global": False,
        }))
        (repo / "examples/rulesync/sources/rules/private-example.md").write_text(
            "---\nroot: false\ntargets: [codexcli, claudecode]\n---\n"
            "# Synthetic private policy\n\nKeep this project's handwritten inputs intact.\n")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-q", "--allow-empty", "-m", "fixture"], check=True)
        self.entry = self.root / "wrong-output-cli"
        self.entry.write_text("#!/usr/bin/env python3\n"
                              "import sys\nfrom pathlib import Path\n"
                              "if '--version' in sys.argv:\n print('0.1.0')\n"
                              "else:\n"
                              " p=Path('scratch/project/AGENTS.md')\n p.write_text('# Wrong policy\\n')\n print('true')\n")
        self.entry.chmod(0o755)
        backend = self.root / "backend"
        backend.write_text("#!/usr/bin/env python3\nprint('16.39.1')\n")
        backend.chmod(0o755)
        evidence = self.root / "evidence"
        evidence.mkdir()
        self.args = argparse.Namespace(environment_repo=repo, entry=self.entry, rulesync=backend,
                                       evidence_root=evidence, agent="detector fixture", doctor_only=False)

    def tearDown(self):
        self.temp.cleanup()

    def attempt(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = verify.run(self.args)
        path = Path(output.getvalue().strip())
        return code, path, json.loads(path.read_text())

    def test_exit_zero_with_wrong_output_fails_and_preserves_evidence(self):
        code, path, result = self.attempt()
        self.assertEqual(code, 1)
        self.assertEqual(result["feature_result"], "fail")
        self.assertTrue(result["cleanup"]["ok"])
        self.assertFalse(Path(result["owned_resources"][0]).exists())
        self.assertEqual((path.parent / "failed-output/AGENTS.md").read_text(), "# Wrong policy\n")
        self.assertTrue(path.is_file())

    def test_missing_prerequisite_is_blocked_without_drive(self):
        self.args.rulesync = self.root / "missing-backend"
        code, path, result = self.attempt()
        self.assertEqual(code, 2)
        self.assertEqual(result["feature_result"], "blocked")
        self.assertFalse(result["drive_started"])
        self.assertTrue(result["cleanup"]["ok"])
        self.assertTrue(path.is_file())

    def test_unrelated_nonzero_failure_is_not_collision_proof(self):
        self.entry.write_text("#!/usr/bin/env python3\n" + textwrap.dedent('''\
            import hashlib, json, sys
            from pathlib import Path
            if '--version' in sys.argv:
                print('0.1.0')
                sys.exit(0)
            if Path('sources/skills/handwritten').exists():
                print('FAIL: unrelated backend failure', file=sys.stderr)
                sys.exit(1)
            if sys.argv[1] == 'check':
                print('true')
                sys.exit(0)
            body = Path('sources/rules/private-example.md').read_bytes().split(b'---', 2)[2].lstrip(b'\\r\\n')
            files = {'AGENTS.md': body, '.claude/rules/private-example.md': body}
            for prefix in ('.agents', '.claude', '.grok'):
                for name in ('SKILL.md', 'reference.txt'):
                    files[f'{prefix}/skills/environment-proof/{name}'] = Path('sources/skills/environment-proof', name).read_bytes()
            out = Path('scratch/project')
            changed = any(not (out / name).exists() or (out / name).read_bytes() != data for name, data in files.items())
            owned = []
            for name, data in files.items():
                p = out / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                owned.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'mode': p.stat().st_mode & 0o777})
            (out / '.rulesync-ownership.json').write_text(json.dumps({'version': 1, 'files': owned}))
            print(json.dumps(changed))
            '''))
        code, path, result = self.attempt()
        self.assertEqual(code, 1)
        self.assertEqual(result["feature_result"], "fail")
        self.assertEqual(result["error"], "collision refused for the unowned handwritten skill")
        self.assertTrue(result["cleanup"]["ok"])
        self.assertFalse(Path(result["owned_resources"][0]).exists())
        self.assertTrue((path.parent / "failed-output/AGENTS.md").is_file())

    def test_doctor_only_is_not_run(self):
        self.args.doctor_only = True
        code, path, result = self.attempt()
        self.assertEqual(code, 3)
        self.assertEqual(result["feature_result"], "not-run")
        self.assertFalse(result["drive_started"])
        self.assertTrue(result["cleanup"]["ok"])
        self.assertTrue(path.is_file())

    def test_cleanup_failure_cannot_pass(self):
        with patch.object(verify, "drive"), patch.object(verify.shutil, "rmtree", side_effect=OSError("fixture cleanup refusal")):
            code, path, result = self.attempt()
        scratch = Path(result["owned_resources"][0])
        try:
            self.assertEqual(code, 1)
            self.assertEqual(result["feature_result"], "pass")
            self.assertEqual(result["result"], "fail")
            self.assertFalse(result["cleanup"]["ok"])
            self.assertTrue(scratch.is_dir())
            self.assertTrue(path.is_file())
        finally:
            shutil.rmtree(scratch)


if __name__ == "__main__":
    unittest.main()
