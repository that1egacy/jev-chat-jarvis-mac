"""控制台诊断计数与候选区默认条数的配置读取。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chat_context
import hud
import perception
import test_hud_reply as fixtures
from test_calibration import block


class CompactRowsTests(unittest.TestCase):
    def test_default_is_one(self):
        with patch('userconfig.get', return_value=None):
            self.assertEqual(hud._compact_rows_setting(), 1)

    def test_valid_value_is_used(self):
        with patch('userconfig.get', return_value='2'):
            self.assertEqual(hud._compact_rows_setting(), 2)

    def test_out_of_range_falls_back_to_one(self):
        for raw in ('0', '9', 'abc', ''):
            with patch('userconfig.get', return_value=raw):
                self.assertEqual(hud._compact_rows_setting(), 1, raw)


class DiagnosticsCounterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HudReplyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.h.conversations = chat_context.Conversations(Path(directory) / 'history.json')
        self.h.history_enabled = True
        self.h._show_boxes = False

    def read(self, texts):
        messages = [perception.Message(text, 'them', 0.5 + index * .05, .9,
                                       h=0.03, x=0.3, w=0.4, sender='甲')
                    for index, text in enumerate(texts)]
        fixtures.HUD['read_conversation'].return_value = {
            'ok': True, 'unchanged': False, 'fingerprint': None,
            'window': {'wid': 1}, 'chat_title': 'chat', 'messages': messages,
        }
        self.h._work_inner()
        return messages

    def test_successful_reads_are_counted(self):
        self.read(['一'])
        self.read(['一', '二'])
        self.assertGreaterEqual(self.h._diag['read'], 2)

    def test_scrolling_up_to_an_older_message_is_counted_and_skipped(self):
        self.read(['一', '二', '三'])
        self.assertEqual(self.h._diag.get('scroll_skip', 0), 0)
        self.h._prejudge_req = None
        self.h._pregen_req = None
        # 画面回滚：回复目标从「三」变成更早的「二」
        self.read(['一', '二'])
        self.assertEqual(self.h._diag.get('scroll_skip', 0), 1)
        self.assertIsNone(self.h._prejudge_req)


if __name__ == '__main__':
    unittest.main()
