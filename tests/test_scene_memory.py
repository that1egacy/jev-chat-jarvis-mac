"""会话级场景记忆：只存加盐哈希、原子落盘、HUD 的恢复/记忆接线。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hud
import modes
from chat_scene_memory import MAX_ENTRIES, ChatSceneMemory


class MemoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / 'chat_scenes.json'

    def test_round_trip(self):
        memory = ChatSceneMemory(self.path)
        self.assertIsNone(memory.recall('wechat', '老王'))
        self.assertTrue(memory.remember('wechat', '老王', 'work'))
        memory = ChatSceneMemory(self.path)          # 重新加载
        self.assertEqual(memory.recall('wechat', '老王'), 'work')

    def test_title_never_appears_in_plaintext(self):
        memory = ChatSceneMemory(self.path)
        memory.remember('wechat', '老王的工作群', 'work')
        raw = self.path.read_text(encoding='utf-8')
        self.assertNotIn('老王', raw)
        self.assertIn('salt', raw)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_app_is_part_of_the_key(self):
        memory = ChatSceneMemory(self.path)
        memory.remember('wechat', '同名会话', 'work')
        self.assertIsNone(memory.recall('mail', '同名会话'))

    def test_remember_moves_entry_to_the_end_and_trims(self):
        memory = ChatSceneMemory(self.path)
        for index in range(MAX_ENTRIES):
            memory.remember('wechat', f'会话{index}', 'im')
        self.assertEqual(len(memory), MAX_ENTRIES)
        memory.remember('wechat', '会话0', 'work')     # 旧条目重新记住 -> 变成最新
        memory.remember('wechat', '新会话', 'im')      # 触发淘汰
        self.assertEqual(memory.recall('wechat', '会话0'), 'work')
        self.assertIsNone(memory.recall('wechat', '会话1'))   # 最旧的那条被丢掉

    def test_forget(self):
        memory = ChatSceneMemory(self.path)
        memory.remember('wechat', '老王', 'work')
        self.assertTrue(memory.forget('wechat', '老王'))
        self.assertFalse(memory.forget('wechat', '老王'))
        self.assertIsNone(ChatSceneMemory(self.path).recall('wechat', '老王'))

    def test_empty_title_is_not_remembered(self):
        memory = ChatSceneMemory(self.path)
        self.assertFalse(memory.remember('wechat', '', 'work'))
        self.assertIsNone(memory.recall('wechat', ''))

    def test_corrupt_file_degrades_to_empty_memory(self):
        self.path.write_text('{not json', encoding='utf-8')
        memory = ChatSceneMemory(self.path)
        self.assertIsNone(memory.recall('wechat', '老王'))
        self.assertTrue(memory.remember('wechat', '老王', 'im'))   # 仍可写
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertTrue(payload.get('salt'))

    def test_missing_directory_is_created(self):
        nested = Path(self.dir.name) / 'a' / 'b' / 'chat_scenes.json'
        memory = ChatSceneMemory(nested)
        memory.remember('wechat', '老王', 'im')
        self.assertTrue(nested.exists())


class _StubHud:
    """只实现 _restore_chat_scene/apply_scene 会用到的表面。"""

    def __init__(self, app, title, memory):
        self._app = app
        self._chat_title = title
        self._memory = memory
        self.applied = []

    def _scene_memory(self):
        return self._memory

    def apply_scene(self, key, remember=True):
        self.applied.append((key, remember))
        modes.set_active(key)


class HudSceneMemoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.memory = ChatSceneMemory(Path(self.dir.name) / 'scene.json')
        self.app = SimpleNamespace(key='wechat')
        modes.set_active('im')
        self.addCleanup(modes.set_active, 'im')

    def test_restore_applies_the_remembered_scene(self):
        self.memory.remember('wechat', '老板', 'work')
        stub = _StubHud(self.app, '老板', self.memory)
        hud.HudController._restore_chat_scene(stub, '老板')
        self.assertEqual(stub.applied, [('work', False)])

    def test_restore_is_silent_without_memory(self):
        stub = _StubHud(self.app, '老王', self.memory)
        hud.HudController._restore_chat_scene(stub, '老王')
        self.assertEqual(stub.applied, [])

    def test_restore_ignores_unknown_or_current_scene(self):
        self.memory.remember('wechat', '老板', 'im')     # 与当前场景相同
        stub = _StubHud(self.app, '老板', self.memory)
        hud.HudController._restore_chat_scene(stub, '老板')
        self.assertEqual(stub.applied, [])

    def test_explicit_switch_remembers_for_the_current_chat(self):
        stub = _StubHud(self.app, '老板', self.memory)
        for name in ('_apply_scene_tones', '_refresh_scene_items', '_relayout'):
            setattr(stub, name, lambda *a, **k: None)
        stub._set_foreground_state = lambda *a, **k: None
        hud.HudController.apply_scene(stub, 'work')
        self.assertEqual(self.memory.recall('wechat', '老板'), 'work')

    def test_restore_does_not_rewrite_memory(self):
        self.memory.remember('wechat', '老板', 'work')
        stub = _StubHud(self.app, '老板', self.memory)
        hud.HudController._restore_chat_scene(stub, '老板')
        self.assertEqual(self.memory.recall('wechat', '老板'), 'work')


if __name__ == '__main__':
    unittest.main()
