"""#153 场景预设：白名单、话术预设与 registry 过滤的离线回归。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import modes                      # noqa: E402
import styles                     # noqa: E402
from apps import registry         # noqa: E402


class ModesTests(unittest.TestCase):
    def tearDown(self):
        modes.set_active(modes.DEFAULT_KEY)

    def test_default_is_im_and_allows_known_channels(self):
        self.assertEqual(modes.active_key(), 'im')
        for key in ('wechat', 'qq', 'whatsapp'):
            self.assertTrue(modes.allows(key))
        self.assertFalse(modes.allows('mail'))      # 邮件渠道尚未适配

    def test_work_mode_allows_mail_and_uses_formal_tones(self):
        modes.set_active('work')
        self.assertTrue(modes.allows('mail'))
        self.assertIn('稳如老狗', modes.tones())
        for tone in modes.tones():
            self.assertIn(tone, styles.PRESETS)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            modes.set_active('nope')
        self.assertEqual(modes.active_key(), 'im')


class RegistryModeFilterTests(unittest.TestCase):
    class FakeApp:
        key = 'mail'
        bundle_ids = ('com.apple.mail',)
        app_names = ('Mail',)

    def test_channel_outside_whitelist_is_treated_as_leave(self):
        with patch.object(registry, 'APPS', (self.FakeApp(),)):
            with patch.object(modes, 'allows', return_value=False):
                self.assertIsNone(registry.match('com.apple.mail', 'Mail'))
            with patch.object(modes, 'allows', return_value=True):
                self.assertIs(registry.match('com.apple.mail', 'Mail'), registry.APPS[0])

    def test_bundle_match_still_first(self):
        with patch.object(registry, 'APPS', (self.FakeApp(),)):
            with patch.object(modes, 'allows', return_value=True):
                self.assertIs(registry.match('com.apple.mail', 'Mail'), registry.APPS[0])
                self.assertIs(registry.match('', 'Mail'), registry.APPS[0])  # 名字兜底


if __name__ == '__main__':
    unittest.main()
