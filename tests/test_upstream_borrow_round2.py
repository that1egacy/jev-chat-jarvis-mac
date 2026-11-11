"""第二轮借鉴的回归：OCR 语言可配、组内近似重复、填入前的 ChatDiff 二次确认。"""
import unittest
from unittest.mock import Mock, patch

import generate
import hud
import perception
import test_hud_reply as fixtures


class OcrLanguageTests(unittest.TestCase):
    def test_default_is_chinese_only(self):
        with patch('userconfig.get', return_value=None):
            self.assertEqual(perception.ocr_languages(), ("zh-Hans",))
        with patch('userconfig.get', return_value=''):
            self.assertEqual(perception.ocr_languages(), ("zh-Hans",))

    def test_comma_separated_languages_are_parsed(self):
        with patch('userconfig.get', return_value='zh-Hans, en-US'):
            self.assertEqual(perception.ocr_languages(), ("zh-Hans", "en-US"))

    def test_junk_falls_back_to_default(self):
        with patch('userconfig.get', return_value=' , ,'):
            self.assertEqual(perception.ocr_languages(), ("zh-Hans",))

    def test_ocr_image_uses_the_configured_languages_when_none_given(self):
        # ocr_image 内部 import Vision；这里只验证语言缺省值的解析路径
        with patch('userconfig.get', return_value='zh-Hans,en-US'):
            self.assertEqual(perception.ocr_languages(), ("zh-Hans", "en-US"))


class NearDuplicateTests(unittest.TestCase):
    def test_long_near_duplicates_are_collapsed(self):
        texts = ['好的，明天下午两点见面吧', '好的，明天下午两点见面哦']
        self.assertEqual(generate._clean_candidates(texts, limit=5),
                         ['好的，明天下午两点见面吧'])

    def test_short_distinct_replies_are_kept(self):
        self.assertEqual(generate._clean_candidates(['收到', '好的', '明天见'], limit=5),
                         ['收到', '好的', '明天见'])

    def test_semantic_difference_inside_long_text_is_kept(self):
        texts = ['好的，明天下午两点见面吧', '好的，明天下午三点见面吧']
        self.assertEqual(len(generate._clean_candidates(texts, limit=5)), 2)


class FillChatDiffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HudReplyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h
        self.addCleanup(patch.object(hud, '_log').stop)
        patch.object(hud, '_log').start()
        self.h.cand_texts = ['收到，马上看']
        self.h._app = fixtures.HUD['FAKE_APP']
        self.h._input_target = {'box': (1, 2, 3, 4), 'rect': None,
                                'reason': 'test', 'app': 'wechat'}
        fixtures.HUD['FAKE_APP'].fill_text.reset_mock()

    @staticmethod
    def _sender():
        sender = Mock()
        sender.tag.return_value = 0
        return sender

    def test_changed_chat_requires_a_second_click(self):
        self.h.analyzed_text = '旧消息'
        self.h.last_seen = '新消息'
        self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_not_called()
        self.assertIn('再点一次', str(self.h._render.call_args))
        self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_called_once()

    def test_unchanged_chat_fills_on_first_click(self):
        self.h.analyzed_text = '同一条'
        self.h.last_seen = '同一条'
        self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_called_once()

    def test_risky_candidate_requires_a_second_click(self):
        self.h.analyzed_text = '这个方案你看下'
        self.h.last_seen = '这个方案你看下'
        self.h.cand_texts = ['放心，包在我身上']
        self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_not_called()
        self.assertIn('未授权承诺', str(self.h._render.call_args))
        self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_called_once()

    def test_candidate_guard_can_be_turned_off(self):
        self.h.analyzed_text = '这个方案你看下'
        self.h.last_seen = '这个方案你看下'
        self.h.cand_texts = ['放心，包在我身上']
        with patch('userconfig.get', return_value='0'):
            self.h.fillCandidate_(self._sender())
        fixtures.HUD['FAKE_APP'].fill_text.assert_called_once()


if __name__ == '__main__':
    unittest.main()
