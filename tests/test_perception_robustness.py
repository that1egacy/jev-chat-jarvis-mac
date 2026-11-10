"""感知层鲁棒性：OCR 抖动容错、手动校准路径的指纹短路、气泡底色第二证据。"""
import unittest
from unittest.mock import patch

import Quartz as Q

import calibrated_messages
import chat_context
import perception
from calibration import Calibration
from test_calibration import canvas, block


def _window():
    return perception.WindowInfo(1, 1, '微信', 0, 0, 600, 600)


def _calibration():
    return Calibration(600, 600, .32 * 600, 60, .68 * 600, 450)


class SimilarTextTests(unittest.TestCase):
    def test_short_messages_are_never_fuzzy(self):
        self.assertFalse(chat_context._similar_text('嗯', '喂'))
        self.assertFalse(chat_context._similar_text('收到', '收丢'))

    def test_one_character_ocr_jitter_on_same_length_text_is_tolerated(self):
        self.assertTrue(chat_context._similar_text('不好意思', '不好竟思'))
        self.assertTrue(chat_context._similar_text('明天下午三点开会', '明天下午三点开会'))

    def test_digit_changes_are_never_noise(self):
        self.assertFalse(chat_context._similar_text('项086', '项087'))
        self.assertFalse(chat_context._similar_text('片段10', '片段11'))

    def test_inserted_character_in_short_text_is_a_different_message(self):
        self.assertFalse(chat_context._similar_text('明天见', '明天见吧'))


class ObserveContinuityTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.conversations = chat_context.Conversations(Path(self._dir.name) / 'h.json')

    def test_ocr_jitter_does_not_open_a_new_segment(self):
        first, _ = self.conversations.observe('测试群', [('不好意思', 'them', '')])
        second, start = self.conversations.observe('测试群', [('不好竟思', 'them', '')])
        self.assertEqual(len(second), 1)
        self.assertEqual(self.conversations.data['测试群']['breaks'], [])

    def test_different_numbers_stay_separate_messages(self):
        self.conversations.observe('测试群', [('片段10', 'them', '')])
        second, _ = self.conversations.observe('测试群', [('片段11', 'them', '')])
        # 无重叠 → 先按「未知缺口」处理（本帧单独返回、暂不入历史），
        # 关键是别被相似度当成同一条并进原段。
        self.assertEqual([m[0] for m in second], ['片段11'])
        self.assertEqual([m[0] for m in self.conversations.history('测试群')], ['片段10'])


class CalibratedFingerprintTests(unittest.TestCase):
    def _read(self, image, **kwargs):
        with patch.object(perception, 'find_wechat_window', return_value=_window()), \
             patch.object(perception, 'capture_window', return_value=True), \
             patch.object(perception, '_load_png_image', return_value=image), \
             patch.object(perception, 'ocr_image',
                          return_value=[block('测试群', 230, 20, 80),
                                        block('你好', 300, 300, 60)]):
            return perception.read_conversation(calibration=_calibration(), **kwargs)

    def test_unchanged_calibrated_frame_skips_ocr(self):
        image = canvas([(300, 280, 220, 70, (.91, .91, .92))])
        first = self._read(image)
        self.assertFalse(first['unchanged'])
        self.assertIsNotNone(first['fingerprint'])
        with patch.object(perception, 'ocr_image',
                          side_effect=AssertionError('unchanged frame must not re-run OCR')):
            with patch.object(perception, 'find_wechat_window', return_value=_window()), \
                 patch.object(perception, 'capture_window', return_value=True), \
                 patch.object(perception, '_load_png_image', return_value=image):
                second = perception.read_conversation(
                    calibration=_calibration(),
                    prev_fingerprint=first['fingerprint'], prev_layout=first['layout'])
        self.assertTrue(second['unchanged'])

    def test_changed_calibrated_frame_still_reads(self):
        first = self._read(canvas([(300, 280, 220, 70, (.91, .91, .92))]))
        changed = canvas([(300, 280, 220, 70, (.91, .91, .92)),
                          (300, 200, 220, 70, (.91, .91, .92))])
        second = self._read(changed, prev_fingerprint=first['fingerprint'],
                            prev_layout=first['layout'])
        self.assertFalse(second['unchanged'])


class OwnBubbleColorTests(unittest.TestCase):
    def test_wechat_green_is_own_bubble(self):
        self.assertTrue(calibrated_messages.own_bubble((149, 236, 105)))

    def test_grey_and_white_are_not(self):
        self.assertFalse(calibrated_messages.own_bubble((232, 232, 232)))
        self.assertFalse(calibrated_messages.own_bubble((255, 255, 255)))

    def _messages(self, boxes, blocks):
        return calibrated_messages.extract(canvas(boxes), blocks, (.2, .1, .75, .8))

    def test_green_bubble_on_the_left_is_flagged_as_a_contradiction(self):
        # 绿气泡只可能是自己发的；若几何把它判成对方，就不猜，退回 unknown。
        msgs = self._messages([(140, 120, 120, 60, (.6, .94, .56))],
                              [block('我方消息', 155, 135, 90)])
        self.assertEqual([m.side for m in msgs], ['unknown'])

    def test_green_bubble_in_the_middle_resolves_to_me(self):
        msgs = self._messages([(260, 120, 200, 60, (.6, .94, .56))],
                              [block('我方消息', 280, 135, 120)])
        self.assertEqual([m.side for m in msgs], ['me'])


if __name__ == '__main__':
    unittest.main()
