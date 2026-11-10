"""连续消息归组（#148）的离线回归：组边界、上限、消费层合并。

不读屏、不调 API：消息用合成 Message/SimpleNamespace，HUD 走既有测试夹具。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

from chat_context import reply_group, GROUP_MAX, GROUP_CHARS   # noqa: E402


def msg(text, side='them', y=0.30, h=0.02):
    return SimpleNamespace(text=text, side=side, y=y, h=h)


def stack(items):
    """items: [(text, side)] -> 纵向相邻的消息，间距 0.005。"""
    out, y = [], 0.20
    for text, side in items:
        out.append(msg(text, side, y))
        y += 0.03
    return out


class ReplyGroupTests(unittest.TestCase):
    def test_consecutive_them_messages_merge(self):
        msgs = stack([('在吗', 'them'), ('忙不', 'them'), ('帮我个忙', 'them')])
        text, start = reply_group(msgs, 2)
        self.assertEqual(text, '在吗\n忙不\n帮我个忙')
        self.assertEqual(start, 0)

    def test_my_message_breaks_the_group(self):
        msgs = stack([('在吗', 'them'), ('在的', 'me'), ('帮我个忙', 'them')])
        text, start = reply_group(msgs, 2)
        self.assertEqual(text, '帮我个忙')
        self.assertEqual(start, 2)

    def test_unknown_side_breaks_the_group(self):
        msgs = stack([('在吗', 'them'), ('未确认文字', 'unknown'), ('帮我个忙', 'them')])
        self.assertEqual(reply_group(msgs, 2)[0], '帮我个忙')

    def test_large_gap_breaks_the_group(self):
        msgs = [msg('早上好', 'them', 0.10), msg('现在才看到', 'them', 0.60)]
        self.assertEqual(reply_group(msgs, 1)[0], '现在才看到')

    def test_group_is_capped(self):
        msgs = stack([(f'第{i}句', 'them') for i in range(20)])
        text, start = reply_group(msgs, 19)
        self.assertEqual(len(text.split('\n')), GROUP_MAX)
        self.assertEqual(start, 19 - GROUP_MAX + 1)

    def test_merged_text_is_capped_but_keeps_the_tail(self):
        msgs = stack([('长' * 400, 'them'), ('最后一句', 'them')])
        text, _ = reply_group(msgs, 1)
        self.assertLessEqual(len(text), GROUP_CHARS)
        self.assertTrue(text.endswith('最后一句'))

    def test_empty_and_out_of_range(self):
        self.assertEqual(reply_group([], 0), ('', 0))
        msgs = stack([('在吗', 'them')])
        self.assertEqual(reply_group(msgs, 99), ('', 0))


class ReplyGroupHudTests(unittest.TestCase):
    """归组是消费层：HUD 的预判/生成请求用合并文本，历史存盘仍是逐条。"""

    def setUp(self):
        import test_hud_reply
        self.fixture = test_hud_reply.HudReplyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h
        self.scope = test_hud_reply.HUD
        self.h._wechat_frontmost = True
        self.h._input_window = {'wid': 1}
        self.h._input_next = float('inf')

    def read(self, messages):
        from perception import Message
        self.scope['read_conversation'].return_value = {
            'ok': True, 'unchanged': False, 'window': {'wid': 1},
            'chat_title': '聊天', 'messages': messages, 'manual_calibration': True}
        self.h._work_inner()
        self.fixture.flush()

    def test_burst_reaches_prejudge_as_one_text(self):
        from perception import Message
        self.read([Message('在吗', 'them', .30, 1, h=.02),
                   Message('帮我个忙', 'them', .33, 1, h=.02)])
        self.assertIsNotNone(self.h._prejudge_req)
        self.assertEqual(self.h._prejudge_req[0], '在吗\n帮我个忙')

    def test_my_reply_starts_a_new_group(self):
        from perception import Message
        self.read([Message('在吗', 'them', .30, 1, h=.02),
                   Message('在的', 'me', .33, 1, h=.02),
                   Message('帮我个忙', 'them', .36, 1, h=.02)])
        self.assertIsNotNone(self.h._prejudge_req)
        self.assertEqual(self.h._prejudge_req[0], '帮我个忙')


if __name__ == '__main__':
    unittest.main()
