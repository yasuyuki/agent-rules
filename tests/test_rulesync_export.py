"""One canonical policy source; export only native input, never consumer files."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('legacy_rules', ROOT/'bin/rules.py')
rules=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


class ExportTests(unittest.TestCase):
    def test_cursor_exports_always_on_common_policy_with_shared_codex_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            source.mkdir()
            (source / 'example.rule.md').write_text(
                '---\nid: example\ntitle: Example\nsummary: Example summary\n---\nCOMMON\n'
                '<!-- binding: codex -->\nCODEX\n<!-- binding: cursor-agent -->\nCURSOR\n', encoding='utf-8')
            dest = root / 'export'
            rules.export_sources([source], dest, ['codexcli', 'cursor', 'opencode'])
            common = (dest / 'rules/example-00.md').read_text(encoding='utf-8')
            self.assertIn('targets: ["codexcli", "cursor"]', common)
            self.assertIn('description: "Example summary"', common)
            self.assertIn('cursor: {alwaysApply: true}', common)
            self.assertIn('COMMON', common)
            shared = (dest / 'rules/example-01-shared.md').read_text()
            self.assertIn('targets: ["codexcli"]', shared)
            self.assertIn('CODEX', shared)
            cursor = (dest / 'rules/example-01-cursor.md').read_text()
            self.assertIn('targets: ["cursor"]', cursor)
            self.assertIn('CURSOR', cursor)

    def test_explicit_policy_binding_order_and_single_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'input'; source.mkdir()
            payload='---\nid: example\ntitle: Example\nsummary: Example\n---\nCOMMON\n<!-- binding: codex -->\nCODEX\n<!-- binding: claude -->\nCLAUDE\n'
            (source/'example.rule.md').write_text(payload,encoding='utf-8')
            dest=root/'export'
            self.assertEqual(rules.export_sources([source],dest,['codexcli','claudecode','grokcli']),1)
            files=sorted(p.name for p in (dest/'rules').iterdir())
            self.assertEqual(files,['example-00.md','example-01-claude.md','example-01-shared.md'])
            self.assertIn('["codexcli"]',(dest/'rules/example-01-shared.md').read_text())
            self.assertEqual((source/'example.rule.md').read_text(),payload)
            self.assertFalse((dest/'AGENTS.md').exists())
            with self.assertRaises(ValueError):
                rules.export_sources([source],dest,['codexcli'])
            empty = root/'excluded'
            self.assertEqual(rules.export_sources([source],empty,['codexcli'],['example']),0)
            self.assertFalse(list((empty/'rules').iterdir()))
            with self.assertRaisesRegex(ValueError, 'unknown excluded'):
                rules.export_sources([source],root/'typo',['codexcli'],['typo'])

    def test_opencode_export_is_root_only_and_has_one_project_shared_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'input'; source.mkdir()
            payload='---\nid: example\ntitle: Example\nsummary: Example\n---\nCOMMON\n<!-- binding: codex -->\nCODEX\n<!-- binding: claude -->\nCLAUDE\n'
            (source/'example.rule.md').write_text(payload,encoding='utf-8')
            project=root/'project'
            self.assertEqual(rules.export_sources([source],project,['codexcli','grokcli','opencode']),1)
            files=sorted(p.name for p in (project/'rules').iterdir())
            self.assertEqual(files,['example-00.md','example-01-shared.md'])
            self.assertIn('["codexcli"]',(project/'rules/example-01-shared.md').read_text())
            self.assertFalse(any('opencode' in p.name for p in (project/'rules').iterdir()))
            only=root/'opencode-only'
            self.assertEqual(rules.export_sources([source],only,['opencode']),1)
            only_rules=sorted((only/'rules').iterdir())
            self.assertEqual([p.name for p in only_rules],['example-00-opencode.md','example-01-shared.md'])
            self.assertTrue(all('root: true' in p.read_text() for p in only_rules))
            global_dest=root/'global'
            self.assertEqual(rules.export_sources([source],global_dest,['codexcli','grokcli','opencode'],global_mode=True),1)
            names=sorted(p.name for p in (global_dest/'rules').iterdir())
            self.assertEqual(names,['example-00-grok.md','example-00-opencode.md','example-00.md','example-01-grok.md','example-01-opencode.md','example-01-shared.md'])
            self.assertTrue(all('root: true' in (global_dest/'rules'/name).read_text() for name in ['example-00-grok.md','example-00-opencode.md','example-01-grok.md','example-01-opencode.md']))

    def test_all_current_sources_export_without_extra_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            dest=Path(temporary)/'native'
            count=rules.export_sources([ROOT/'rules'],dest,['codexcli','claudecode','grokcli'])
            self.assertEqual(count,len(list((ROOT/'rules').glob('*.rule.md'))))
            self.assertTrue(list((dest/'rules').glob('*.md')))
            self.assertFalse((dest/'skills').exists())


if __name__=='__main__':
    unittest.main()
