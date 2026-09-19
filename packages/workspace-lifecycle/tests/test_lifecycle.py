import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from workspace_lifecycle.errors import LifecycleError
from workspace_lifecycle.service import begin, finish, retire, retire_pending, status


def run(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); base = Path(self.temp.name)
        self.remote = base / "remote.git"; self.root = base / "root"; self.topic = base / "topic"
        run(base, "init", "--bare", "--initial-branch=trunk", str(self.remote))
        run(base, "clone", str(self.remote), str(self.root))
        run(self.root, "config", "user.name", "Test"); run(self.root, "config", "user.email", "test@example.invalid")
        (self.root / "README").write_text("base\n")
        run(self.root, "add", "README"); run(self.root, "commit", "-m", "base"); run(self.root, "push", "origin", "trunk")
        self.remote_default = "origin"
        push = Path(__file__).parents[1] / "src" / "workspace_lifecycle" / "push.py"
        self.preflight = [sys.executable, "-m", "workspace_lifecycle.push", "{repo}", "--user-intent", "push"]

    def tearDown(self): self.temp.cleanup()

    def source_plan(self, workspace, name):
        import hashlib
        return {"commit": [{"path": name, "classification": "source", "owner": self.task,
                             "evidence": "created by this disposable task", "safe_to_commit": True,
                             "sha256": hashlib.sha256((workspace / name).read_bytes()).hexdigest()}]}

    def test_begin_finish_merge_and_retire(self):
        begin(self.root, task="one", request="issue/1", remote="origin", branch="topic/one", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        (self.topic / "feature.txt").write_text("done\n")
        plan = Path(self.temp.name) / "plan-one.json"
        self.task = "one"; plan.write_text(json.dumps(self.source_plan(self.topic, "feature.txt")))
        result = finish(self.topic, task="one", plan_path=str(plan), result_ref="issue/1")
        self.assertTrue(result["accepted"]); self.assertEqual(result["integration"]["destination"], "trunk")
        self.assertEqual((self.root / "feature.txt").read_text(), "done\n")
        self.assertEqual(status(self.topic, "one")["completion"], "accepted")
        retired = retire(self.root, task="one", result_ref="issue/1", users_released=True)
        self.assertTrue(retired["retired"]); self.assertFalse(self.topic.exists())

    def test_finish_rejects_unknown_dirty(self):
        begin(self.root, task="two", request="issue/2", remote="origin", branch="topic/two", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        (self.topic / "private.txt").write_text("keep\n")
        plan = Path(self.temp.name) / "plan-two.json"; plan.write_text("{}")
        with self.assertRaises(LifecycleError): finish(self.topic, task="two", plan_path=str(plan), result_ref="issue/2")
        self.assertTrue((self.topic / "private.txt").exists())

    def test_parent_child_requires_parent_acceptance(self):
        parent = Path(self.temp.name) / "parent"; child = Path(self.temp.name) / "child"
        begin(self.root, task="parent", request="i/p", remote="origin", branch="topic/parent", worktree=str(parent), validation=["git", "diff", "--check"], preflight=self.preflight)
        begin(self.root, task="child", request="i/c", remote="origin", branch="topic/child", worktree=str(child), parent="parent", dependencies=["parent"], validation=["git", "diff", "--check"], preflight=self.preflight)
        (child / "x").write_text("x")
        self.task = "child"; plan = Path(self.temp.name) / "plan-child.json"; plan.write_text(json.dumps(self.source_plan(child, "x")))
        with self.assertRaises(LifecycleError): finish(child, task="child", plan_path=str(plan), result_ref="i/c")

    def test_parent_child_reaches_non_main_default(self):
        parent = Path(self.temp.name) / "parent"; child = Path(self.temp.name) / "child"
        begin(self.root, task="parent", request="i/p", remote="origin", branch="topic/parent", worktree=str(parent), validation=["git", "diff", "--check"], preflight=self.preflight)
        (parent / "parent.txt").write_text("parent\n"); self.task = "parent"
        parent_plan = Path(self.temp.name) / "parent-plan.json"; parent_plan.write_text(json.dumps(self.source_plan(parent, "parent.txt")))
        finish(parent, task="parent", plan_path=str(parent_plan), result_ref="i/p")
        begin(self.root, task="child", request="i/c", remote="origin", branch="topic/child", worktree=str(child), parent="parent", dependencies=["parent"], validation=["git", "diff", "--check"], preflight=self.preflight)
        (child / "child.txt").write_text("child\n"); self.task = "child"
        child_plan = Path(self.temp.name) / "child-plan.json"; child_plan.write_text(json.dumps(self.source_plan(child, "child.txt")))
        result = finish(child, task="child", plan_path=str(child_plan), result_ref="i/c")
        self.assertIn("parent", result["integration"])
        self.assertEqual((self.root / "child.txt").read_text(), "child\n")
        self.assertEqual(run(self.root, "branch", "--show-current"), "trunk")

    def test_merge_conflict_can_be_resolved_and_retried(self):
        begin(self.root, task="conflict", request="i/x", remote="origin", branch="topic/conflict", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        (self.root / "README").write_text("default side\n"); run(self.root, "add", "README"); run(self.root, "commit", "-m", "default edit"); run(self.root, "push", "origin", "trunk")
        (self.topic / "README").write_text("topic side\n"); self.task = "conflict"
        plan = Path(self.temp.name) / "conflict-plan.json"; plan.write_text(json.dumps(self.source_plan(self.topic, "README")))
        with self.assertRaises(LifecycleError): finish(self.topic, task="conflict", plan_path=str(plan), result_ref="i/x")
        self.assertTrue(run(self.root, "rev-parse", "--verify", "MERGE_HEAD"))
        (self.root / "README").write_text("resolved\n"); run(self.root, "add", "README"); run(self.root, "commit", "-m", "resolve")
        result = finish(self.topic, task="conflict", plan_path=str(plan), result_ref="i/x")
        self.assertTrue(result["accepted"])
        self.assertEqual((self.root / "README").read_text(), "resolved\n")

    def test_retire_request_replays_after_native_lock_failure(self):
        begin(self.root, task="retire-retry", request="i/r", remote="origin", branch="topic/retire-retry", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        (self.topic / "r.txt").write_text("r\n"); self.task = "retire-retry"
        plan = Path(self.temp.name) / "retire-plan.json"; plan.write_text(json.dumps(self.source_plan(self.topic, "r.txt")))
        finish(self.topic, task="retire-retry", plan_path=str(plan), result_ref="i/r")
        run(self.root, "worktree", "lock", "--reason", "test retained use", str(self.topic))
        with self.assertRaises(LifecycleError): retire(self.root, task="retire-retry", result_ref="i/r", users_released=True)
        run(self.root, "worktree", "unlock", str(self.topic))
        replay = retire_pending(self.root)
        self.assertEqual(replay["pending"][0]["task"], "retire-retry")
        self.assertTrue(replay["pending"][0]["retired"])

    def test_status_from_default_discovers_registered_tasks(self):
        begin(self.root, task="discover", request="i/d", remote="origin", branch="topic/discover", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        listing = status(self.root)
        self.assertEqual(listing["tasks"], [{"task": "discover", "completion": "active", "retire_pending": False}])

    def test_validation_failure_preserves_task_for_retry(self):
        gate = Path(self.temp.name) / "validation.ok"
        validation = [sys.executable, "-c", "import pathlib,sys; sys.exit(not pathlib.Path(" + repr(str(gate)) + ").exists())"]
        begin(self.root, task="validate", request="i/v", remote="origin", branch="topic/validate", worktree=str(self.topic), validation=validation, preflight=self.preflight)
        (self.topic / "v.txt").write_text("v\n"); self.task = "validate"
        plan = Path(self.temp.name) / "validate-plan.json"; plan.write_text(json.dumps(self.source_plan(self.topic, "v.txt")))
        with self.assertRaises(LifecycleError): finish(self.topic, task="validate", plan_path=str(plan), result_ref="i/v")
        self.assertTrue((self.topic / "v.txt").exists())
        gate.write_text("ok\n")
        result = finish(self.topic, task="validate", plan_path=str(plan), result_ref="i/v")
        self.assertTrue(result["accepted"])

    def test_retire_refuses_ignored_data(self):
        (self.root / ".git" / "info" / "exclude").write_text("private.generated\n")
        begin(self.root, task="ignored", request="i/g", remote="origin", branch="topic/ignored", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        (self.topic / "g.txt").write_text("g\n"); self.task = "ignored"
        plan = Path(self.temp.name) / "ignored-plan.json"; plan.write_text(json.dumps(self.source_plan(self.topic, "g.txt")))
        finish(self.topic, task="ignored", plan_path=str(plan), result_ref="i/g")
        (self.topic / "private.generated").write_text("do not erase\n")
        with self.assertRaises(LifecycleError): retire(self.root, task="ignored", result_ref="i/g", users_released=True)
        self.assertTrue((self.topic / "private.generated").exists())

    def test_retire_rejects_unaccepted_task(self):
        begin(self.root, task="unaccepted", request="i/u", remote="origin", branch="topic/unaccepted", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=self.preflight)
        with self.assertRaises(LifecycleError): retire(self.root, task="unaccepted", result_ref="i/u", users_released=True)
        self.assertTrue(self.topic.exists())

    def test_child_then_parent_retirement(self):
        parent = Path(self.temp.name) / "parent"; child = Path(self.temp.name) / "child"
        begin(self.root, task="p", request="i/p", remote="origin", branch="topic/p", worktree=str(parent), validation=["git", "diff", "--check"], preflight=self.preflight)
        (parent / "p.txt").write_text("p\n"); self.task = "p"
        pplan = Path(self.temp.name) / "p.json"; pplan.write_text(json.dumps(self.source_plan(parent, "p.txt")))
        finish(parent, task="p", plan_path=str(pplan), result_ref="i/p")
        begin(self.root, task="c", request="i/c", remote="origin", branch="topic/c", worktree=str(child), parent="p", dependencies=["p"], validation=["git", "diff", "--check"], preflight=self.preflight)
        (child / "c.txt").write_text("c\n"); self.task = "c"
        cplan = Path(self.temp.name) / "c.json"; cplan.write_text(json.dumps(self.source_plan(child, "c.txt")))
        finish(child, task="c", plan_path=str(cplan), result_ref="i/c")
        with self.assertRaises(LifecycleError): retire(self.root, task="p", result_ref="i/p", users_released=True)
        self.assertTrue(retire(self.root, task="c", result_ref="i/c", users_released=True)["retired"])
        self.assertTrue(retire(self.root, task="p", result_ref="i/p", users_released=True)["retired"])

    def test_push_hold_then_retry_uses_same_finish_intent(self):
        gate = Path(self.temp.name) / "allow-push"
        code = ("import json,pathlib,subprocess; g=pathlib.Path(" + repr(str(gate)) + "); "
                "b=subprocess.check_output(['git','branch','--show-current'],text=True).strip(); "
                "print(json.dumps({'decision':'push','reason':'approved','push_argv':['git','push','origin','HEAD:refs/heads/'+b]} "
                "if g.exists() else {'decision':'hold','reason':'waiting'}))")
        hold_preflight = [sys.executable, "-c", code, "{repo}"]
        begin(self.root, task="hold", request="i/h", remote="origin", branch="topic/hold", worktree=str(self.topic), validation=["git", "diff", "--check"], preflight=hold_preflight)
        (self.topic / "h.txt").write_text("h\n"); self.task = "hold"
        plan = Path(self.temp.name) / "hold.json"; plan.write_text(json.dumps(self.source_plan(self.topic, "h.txt")))
        with self.assertRaises(LifecycleError): finish(self.topic, task="hold", plan_path=str(plan), result_ref="i/h")
        gate.write_text("go\n")
        result = finish(self.topic, task="hold", plan_path=str(plan), result_ref="i/h")
        self.assertTrue(result["accepted"])


class RecoveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = LifecycleTest('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        begin(f.root, task='boundary', request='issue/boundary', remote='origin', branch='topic/boundary',
              worktree=str(f.topic), validation=['git', 'diff', '--check'], preflight=f.preflight)
        path = f.topic / 'feature'; path.write_text('verified')
        import hashlib
        self.plan = Path(f.temp.name) / 'boundary.json'
        self.plan.write_text(json.dumps({'commit': [{'path': 'feature', 'classification': 'source',
            'owner': 'boundary', 'evidence': 'fixture authored file', 'safe_to_commit': True,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}))
        finish(f.topic, task='boundary', plan_path=str(self.plan), result_ref='issue/boundary')

    def test_compat_refuses_retiring_task(self):
        from workspace_lifecycle.compat import registered_checkout
        f = self.fixture
        retire(f.root, task='boundary', result_ref='issue/boundary', users_released=True, request_only=True)
        with self.assertRaises(LifecycleError):
            with registered_checkout(f.topic):
                self.fail('retiring checkout admitted')

    def test_compat_refuses_duplicate_git_checkout(self):
        from workspace_lifecycle.compat import registered_checkout
        f = self.fixture; duplicate = Path(f.temp.name) / 'duplicate'
        run(f.root, 'worktree', 'add', '--detach', str(duplicate), 'topic/boundary')
        run(duplicate, 'symbolic-ref', 'HEAD', 'refs/heads/topic/boundary')
        with self.assertRaises(LifecycleError):
            with registered_checkout(duplicate):
                self.fail('duplicate identity admitted')

    def test_absence_before_authorized_remove_is_not_success(self):
        f = self.fixture
        retire(f.root, task='boundary', result_ref='issue/boundary', users_released=True, request_only=True)
        run(f.root, 'worktree', 'remove', str(f.topic))
        with self.assertRaisesRegex(LifecycleError, 'disappeared before authorized'):
            retire(f.root, task='boundary', result_ref='issue/boundary')
        self.assertIn('boundary', [item['task'] for item in status(f.root)['tasks']])

    def test_absence_after_authorized_remove_recovers_receipt(self):
        from unittest.mock import patch
        from workspace_lifecycle import service
        f = self.fixture; original = service.git
        def interrupted(repo, *args, **kwargs):
            result = original(repo, *args, **kwargs)
            if args[:2] == ('worktree', 'remove'):
                raise OSError('crash after actual native removal')
            return result
        with patch.object(service, 'git', side_effect=interrupted):
            with self.assertRaises(LifecycleError):
                retire(f.root, task='boundary', result_ref='issue/boundary', users_released=True)
        self.assertFalse(f.topic.exists())
        self.assertTrue(retire(f.root, task='boundary', result_ref='issue/boundary')['retired'])
        self.assertEqual(status(f.root)['tasks'], [])
