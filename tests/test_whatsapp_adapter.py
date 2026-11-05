"""WhatsApp 适配器的离线回归：消息归类、归属判定、AX 输入框定位节流。

不读屏、不调 API、不读凭据：消息用合成 TextBlock，AX 用 Mock 控制。
与仓库既有测试同一口径（见 tests/README 与 support_hud）。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from perception import TextBlock                      # noqa: E402
from calibration import Calibration                   # noqa: E402
from apps import whatsapp_app as wa                   # noqa: E402


def block(text, top, x, w=0.2, h=0.02, conf=0.9):
    """按解析器的口径造块：Vision 的 y 是底部原点，top = 1 - y - h。"""
    return TextBlock(text=text, conf=conf, x=x, y=1 - top - h, w=w, h=h)


CAL = Calibration(1024.0, 768.0, 498.0, 45.0, 520.0, 668.0)


class SideTests(unittest.TestCase):
    def test_left_edge_is_them(self):
        parsed = wa.classify_blocks([block('对方消息', 0.20, 0.50)])
        self.assertEqual([m.side for m in parsed['messages']], ['them'])

    def test_right_edge_is_me(self):
        parsed = wa.classify_blocks([block('我的消息', 0.20, 0.75)])
        self.assertEqual([m.side for m in parsed['messages']], ['me'])

    def test_middle_block_falls_back_to_center(self):
        # 不贴任何一边：按气泡中心与聊天区中线比较，偏左即对方
        parsed = wa.classify_blocks([block('中间偏左', 0.20, 0.52, w=0.10)])
        self.assertEqual(parsed['messages'][0].side, 'them')


class FilterTests(unittest.TestCase):
    def test_date_system_and_timestamp_lines_dropped(self):
        blocks = [
            block('昨天', 0.10, 0.50, w=0.05, h=0.012),
            block('8月27日 周四', 0.12, 0.45, w=0.15, h=0.012),
            block('你已开启限时消息功能。此聊天中的新消息将在发送 7 天后自动消失', 0.30, 0.50, w=0.40),
            block('正常消息', 0.35, 0.50, w=0.18),
        ]
        texts = [m.text for m in wa.classify_blocks(blocks)['messages']]
        self.assertEqual(texts, ['正常消息'])

    def test_trailing_timestamp_stripped(self):
        parsed = wa.classify_blocks([block('收到 09:45 ✓✓', 0.20, 0.50, w=0.2)])
        self.assertEqual(parsed['messages'][0].text, '收到')


class MergeTests(unittest.TestCase):
    def test_same_bubble_multiline_merged(self):
        blocks = [
            block('第一行', 0.20, 0.50, w=0.18),
            block('第二行', 0.225, 0.50, w=0.18),
        ]
        parsed = wa.classify_blocks(blocks)
        self.assertEqual(len(parsed['messages']), 1)
        self.assertIn('第二行', parsed['messages'][0].text)

    def test_different_x_not_merged(self):
        blocks = [
            block('对方一句', 0.20, 0.50, w=0.15),
            block('我的回复', 0.27, 0.75, w=0.15),
        ]
        self.assertEqual(len(wa.classify_blocks(blocks)['messages']), 2)


class CalibrationBoundsTests(unittest.TestCase):
    def test_header_and_input_excluded(self):
        blocks = [
            block('聊天', 0.02, 0.50, w=0.05, h=0.012),       # 顶部标题栏，校准区外
            block('正文消息', 0.30, 0.50, w=0.2),
            block('输入框草稿', 0.95, 0.55, w=0.3),            # 输入栏，校准区外
        ]
        texts = [m.text for m in wa.classify_blocks(blocks, CAL)['messages']]
        self.assertEqual(texts, ['正文消息'])

    def test_capacity_limited(self):
        blocks = [block(f'消息{i}', 0.10 + i * 0.05, 0.50, w=0.18) for i in range(30)]
        self.assertEqual(len(wa.classify_blocks(blocks)['messages']), wa.MAX_MESSAGES)


class AxThrottleTests(unittest.TestCase):
    def setUp(self):
        wa._INPUT_CACHE.update(wid=None, box=None, rect=None, reason="", next=0.0)

    def test_failure_is_cached_for_three_seconds(self):
        win = dict(wid=42, x=100, y=100, w=1024, h=768, pid=999)
        with patch.object(wa, '_ax_text_area', return_value=None) as mocked:
            first = wa.locate_input(win)
            second = wa.locate_input(win)
        self.assertIsNone(first['box'])
        self.assertEqual(mocked.call_count, 1)           # 第二次命中缓存，未再走 AX
        self.assertEqual(second['rect'], first['rect'])
        self.assertIn('剪贴板', second['reason'])

    def test_window_change_invalidates_cache(self):
        win1 = dict(wid=42, x=0, y=0, w=1024, h=768, pid=999)
        win2 = dict(wid=43, x=0, y=0, w=1024, h=768, pid=999)
        with patch.object(wa, '_ax_text_area', return_value=None) as mocked:
            wa.locate_input(win1)
            wa.locate_input(win2)
        self.assertEqual(mocked.call_count, 2)


class StripLabelTests(unittest.TestCase):
    """借鉴 #140：群聊昵称/引用块首行（字号更小）不并入正文。"""

    def _two_line(self, first, second, x=0.50, first_h=0.012, body_h=0.018):
        return [
            block(first, 0.20, x, w=0.18, h=first_h),
            block(second, 0.22, x, w=0.18, h=body_h),
        ]

    def test_smaller_first_line_stripped_for_them(self):
        parsed = wa.classify_blocks(self._two_line('Wenfeng', '下午三点开会'))
        self.assertEqual(parsed['messages'][0].text, '下午三点开会')

    def test_same_height_short_line_kept(self):
        parsed = wa.classify_blocks(self._two_line('好的', '明天见', first_h=0.018))
        self.assertIn('好的', parsed['messages'][0].text)

    def test_me_message_never_stripped(self):
        parsed = wa.classify_blocks(self._two_line('Wenfeng', '我的回复', x=0.75))
        self.assertEqual(parsed['messages'][0].side, 'me')
        self.assertIn('Wenfeng', parsed['messages'][0].text)

    def test_flag_off_keeps_label(self):
        with patch.object(wa, 'STRIP_SENDER', False):
            parsed = wa.classify_blocks(self._two_line('Wenfeng', '下午三点开会'))
        self.assertIn('Wenfeng', parsed['messages'][0].text)


class StripQuoteTests(unittest.TestCase):
    """引用卡片：标签行 + 引用文字（都是小字号）一起剥离，只留正文。"""

    def _stack(self, lines):
        """lines: [(text, height)]，同一气泡内从上到下。"""
        blocks, top = [], 0.20
        for text, h in lines:
            blocks.append(block(text, top, 0.50, w=0.18, h=h))
            top += h + 0.004
        return blocks

    def test_label_and_quote_stripped_together(self):
        blocks = self._stack([
            ('Wenfeng', 0.011),           # 发言人昵称
            ('明天能来开会吗？', 0.012),   # 引用卡片文字
            ('可以', 0.018),              # 真正的正文
        ])
        parsed = wa.classify_blocks(blocks)
        self.assertEqual(parsed['messages'][0].text, '可以')

    def test_quote_without_label_still_stripped(self):
        blocks = self._stack([
            ('收到，明天见', 0.012),
            ('好的我改一下方案', 0.018),
        ])
        parsed = wa.classify_blocks(blocks)
        self.assertEqual(parsed['messages'][0].text, '好的我改一下方案')

    def test_small_font_head_with_punctuation_still_stripped(self):
        # 引用原文以句号结尾很常见；字号才是标签判据，不按标点拦截
        blocks = self._stack([
            ('好的。', 0.011),
            ('那就这样', 0.018),
        ])
        parsed = wa.classify_blocks(blocks)
        self.assertEqual(parsed['messages'][0].text, '那就这样')

    def test_keeps_one_body_line_when_all_small(self):
        blocks = self._stack([
            ('短句一', 0.012),
            ('短句二', 0.012),
        ])
        parsed = wa.classify_blocks(blocks)
        self.assertTrue(parsed['messages'][0].text.strip())


if __name__ == '__main__':
    unittest.main()
