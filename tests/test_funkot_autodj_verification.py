import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "skills/verify-funkot-autodj/scripts/verify.py"
spec = importlib.util.spec_from_file_location("autodj_verify", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

FIXTURE_PROGRAM = r'''
import hashlib, json, os, struct, sys
from pathlib import Path

def wav(path, seconds, value):
    frames = 44100 * seconds
    data = struct.pack('<ff', value, value) + bytes((frames - 1) * 8)
    fmt = struct.pack('<HHIIHHHHI', 65534, 2, 44100, 352800, 8, 32, 22, 32, 3)
    fmt += bytes.fromhex('0300000000001000800000aa00389b71')
    chunks = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(data)) + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(chunks)+4) + b'WAVE' + chunks)

args = sys.argv[1:]
if '--artifact-complete' in args:
    sys.exit(0)
if Path(sys.argv[0]).name == 'gen_synth':
    root = Path(args[0])
    wav(root / 'track_a_180_i16_o16.wav', 1, 0.2)
    wav(root / 'track_b_178_i32_o8.wav', 1, 0.3)
else:
    out = Path(args[args.index('--render') + 1])
    fault = os.environ.get('AUTODJ_FIXTURE_FAULT', '')
    wav(out, 1 if '--transitions-only' in args else 61, 0.0 if fault == 'silent' else 0.5)
    wav(out.with_name(out.stem + '_transitions') / '01.wav', 1, 0.5)
    if fault == 'wrong-cleanup' and out.name == 'mix.wav':
        out.with_name('.mix.wav.owned').write_text(json.dumps(dict(output=str(out), generation='fixture', state='held')))
    cache = Path(args[args.index('--cache-dir') + 1]); cache.mkdir(exist_ok=True)
    playlist = Path(args[args.index('-l') + 1])
    tracks = [playlist.parent / row for row in playlist.read_text().splitlines() if row and not row.startswith('#')]
    for track in tracks[:1] if fault == 'missing-cache' else tracks:
        data = track.read_bytes()
        digest = hashlib.sha256(struct.pack('<Q',len(data)) + data[:65536])
        if len(data) > 65536: digest.update(data[-65536:])
        entry = dict(version=14, file_name=track.name, total_frames=44100, intro_bpm=180,
                     outro_bpm=180, intro_bars=16, outro_bars=32, needs_reanalysis=False)
        (cache / (digest.hexdigest()+'.json')).write_text(json.dumps(entry))
'''


@unittest.skipUnless(sys.platform.startswith("linux"), "Verification recipe uses Linux process groups")
class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for name, contents in {"Cargo.toml": "[workspace]\n", "Cargo.lock": "",
                               "funkot-core/src/cache.rs": "pub const CACHE_VERSION: u32 = 14;\n",
                               "funkot-core/examples/gen_synth.rs": "",
                               "funkot-cli/src/main.rs": ""}.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        program = "#!" + sys.executable + "\n" + textwrap.dedent(FIXTURE_PROGRAM)
        self.program = self.root / "fixture.py"
        self.program.write_text(program)
        cargo = self.bin / "cargo"
        cargo.write_text("#!" + sys.executable + "\n" + textwrap.dedent(f'''
            import os, shutil, sys
            from pathlib import Path
            if '--version' in sys.argv:
                print('cargo fixture')
            else:
                target = Path(sys.argv[sys.argv.index('--target-dir')+1])
                dest = target / ('release/examples/gen_synth' if '--example' in sys.argv else 'release/funkot-autodj')
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile({str(self.program)!r}, dest)
                dest.chmod(0o755)
        '''))
        cargo.chmod(0o755)
        rustc = self.bin / "rustc"
        rustc.write_text("#!/bin/sh\nprintf 'rustc fixture\\n'\n")
        rustc.chmod(0o755)
        self.args = [sys.executable, str(SCRIPT), "--repo", str(self.repo),
                     "--target-dir", str(self.root / "target"),
                     "--evidence-root", str(self.root / "evidence"), "--agent", "test-fixture"]
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}
        self.env.pop("WORKSPACE_LIFECYCLE_CONTEXT", None)

    def run_recipe(self, fault="", doctor=False, repo=None):
        args = list(self.args)
        if repo is not None:
            args[args.index("--repo") + 1] = str(repo)
        if doctor:
            args.append("--doctor-only")
        completed = subprocess.run(args, env={**self.env, "AUTODJ_FIXTURE_FAULT": fault},
                                   capture_output=True, text=True)
        self.assertTrue(completed.stdout, completed.stderr)
        info = json.loads(completed.stdout)
        path = Path(info["record"])
        record = json.loads(path.read_text())
        self.assertTrue(record["cleanup"]["evidence_exists"])
        self.assertTrue(record["cleanup"]["ok"])
        self.assertTrue(all((path.parent / p).is_file() for p in record["artifacts"]))
        if "scratch" in record["owned"]:
            self.assertFalse(Path(record["owned"]["scratch"]).exists())
            self.assertTrue((path.parent / "scratch-manifest.json").is_file())
        return completed, record

    def test_complete_recipe_passes_observable_outputs(self):
        completed, record = self.run_recipe()
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(record["feature_result"], "pass")
        self.assertEqual(record["observations"]["mix"]["frames"], 2690100)
        self.assertEqual(record["observations"]["transition_only"]["frames"], 44100)
        self.assertEqual(len(record["observations"]["analyses"]), 2)

    def test_zero_exit_with_silent_wav_fails_and_cleans(self):
        completed, record = self.run_recipe("silent")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(record["feature_result"], "fail")
        self.assertIn("silent WAV", record["error"])
        self.assertEqual(record["commands"][-1]["exit_code"], 0)

    def test_zero_exit_with_missing_side_effect_fails_and_cleans(self):
        completed, record = self.run_recipe("missing-cache")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(record["feature_result"], "fail")
        self.assertIn("exactly two analysis caches", record["error"])
        self.assertEqual(record["commands"][-1]["exit_code"], 0)

    def test_missing_source_is_blocked_without_drive(self):
        missing = self.root / "missing"
        missing.mkdir()
        completed, record = self.run_recipe(repo=missing)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(record["result"], "blocked")
        self.assertEqual(record["feature_result"], "not-run")
        self.assertNotIn("scratch", record["owned"])

    def test_doctor_cannot_pass_feature(self):
        completed, record = self.run_recipe(doctor=True)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(record["result"], "not-run")
        self.assertEqual(record["feature_result"], "not-run")
        self.assertNotIn("scratch", record["owned"])

    def test_failed_cleanup_prevents_completed_proof(self):
        args = type("Args", (), dict(repo=self.repo, target_dir=self.root / "target",
                                   evidence_root=self.root / "evidence", agent="test-fixture",
                                   doctor_only=False))()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(verify.shutil, "rmtree", side_effect=OSError("fixture cleanup refused")):
            record, path = verify.verify(args)
        self.assertEqual(record["feature_result"], "pass")
        self.assertEqual(record["result"], "fail")
        self.assertFalse(record["cleanup"]["ok"])
        self.assertIn("fixture cleanup refused", record["cleanup"]["error"])
        self.assertTrue(path.is_file())
        self.assertTrue(Path(record["owned"]["scratch"]).is_dir())
        verify.shutil.rmtree(record["owned"]["scratch"])

    def test_zero_exit_native_cleanup_without_reclamation_fails(self):
        completed = subprocess.run(self.args, env={**self.env, "AUTODJ_FIXTURE_FAULT": "wrong-cleanup"},
                                   capture_output=True, text=True)
        info = json.loads(completed.stdout)
        path = Path(info["record"])
        record = json.loads(path.read_text())
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(record["feature_result"], "pass")
        self.assertEqual(record["result"], "fail")
        self.assertFalse(record["cleanup"]["ok"])
        self.assertTrue(record["cleanup"]["evidence_exists"])
        self.assertIn("did not reclaim", record["cleanup"]["error"])
        self.assertEqual(record["commands"][-1]["exit_code"], 0)
        scratch = Path(record["owned"]["scratch"])
        self.assertTrue((scratch / "mix.wav").is_file())
        self.assertTrue((path.parent / "scratch-manifest.json").is_file())
        verify.shutil.rmtree(scratch)


if __name__ == "__main__":
    unittest.main()
