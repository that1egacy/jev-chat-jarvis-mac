"""回复策略（NextStep 最小版）：阈值、只给风险开关、状态行文案、HUD 拦截。"""
import unittest
from unittest.mock import Mock

import perception
import reply_policy
import test_hud_reply as fixtures


class DecideTests(unittest.TestCase):
    def test_low_risk_drafts(self):
        self.assertEqual(reply_policy.decide({'intent': '闲聊', 'risk': 1, 'confidence': .9}),
                         'draft')

    def test_high_risk_holds(self):
        self.assertEqual(reply_policy.decide({'intent': '批评', 'risk': 8.2,
                                              'confidence': .9}), 'hold')
        self.assertEqual(reply_policy.decide({'intent': '批评', 'risk': 9}), 'hold')

    def test_mid_risk_only_warns(self):
        self.assertEqual(reply_policy.decide({'intent': '催进度', 'risk': 6.5,
                                              'confidence': .8}), 'caution')

    def test_low_confidence_asks_first(self):
        self.assertEqual(reply_policy.decide({'intent': '派活', 'risk': 3,
                                              'confidence': .2}), 'clarify')

    def test_risk_only_overrides_everything(self):
        self.assertEqual(reply_policy.decide({'risk': 0, 'confidence': .99},
                                             risk_only=True), 'hold')

    def test_missing_or_dirty_verdict_drafts(self):
        self.assertEqual(reply_policy.decide(None), 'draft')
        self.assertEqual(reply_policy.decide({'risk': 'oops', 'confidence': None}), 'draft')


class EnvironmentDefaultTests(unittest.TestCase):
    def test_env_switch(self):
        from unittest.mock import patch
        for value, expected in ((None, False), ('1', True), ('true', True),
                                ('0', False), ('off', False)):
            with patch('userconfig.get', return_value=value):
                self.assertEqual(reply_policy.risk_only_default(), expected, value)


class StatusLineTests(unittest.TestCase):
    def test_hold_and_caution_text(self):
        self.assertIn('只给建议', reply_policy.status_line('hold', {'risk': 8.4}))
        self.assertIn('只给风险', reply_policy.status_line('hold', {'risk': 0.0},
                                                         risk_only=True))
        self.assertIn('提醒', reply_policy.status_line('caution', {'risk': 6.4}))
        self.assertIn('确认对方意思', reply_policy.status_line('clarify', {'risk': 2}))
        self.assertEqual(reply_policy.status_line('draft'), '')

    def test_status_never_contains_message_text(self):
        text = reply_policy.status_line('hold', {'risk': 8.0, 'message': '老板的私密内容'})
        self.assertNotIn('私密', text)


class HudHoldIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HudReplyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h
        self.h.generator = Mock()
        # _reply_current 需要：有前台应用、有回复 key、未暂停
        self.h._app = fixtures.HUD['FAKE_APP']
        self.h._reply_key = ('wechat', 'chat')
        self.h._paused = False
        self.h._active_context = ''
        self.h.slot_tones = ['高情商话术']
        self.messages = [perception.Message('老板的消息', 'them', .5, .9, h=.05, x=.3, w=.4,
                                            sender='老板')]

    def _run(self, verdict):
        try:
            self.h._reply_task(self.h._reply_epoch, self.h._run_generation,
                               self.messages[-1], self.messages, verdict)
        except Exception:                                  # 线程边界的异常由 HUD 自己兜
            pass

    def _selectors(self):
        return [selector for selector, _payload in self.fixture.queue]

    def test_high_risk_discards_candidates(self):
        self._run({'intent': '批评', 'risk': 8.6, 'confidence': .9})
        self.h.generator.generate.assert_not_called()
        self.assertIn('applyRiskHold:', self._selectors())

    def test_risk_only_toggle_holds_even_on_low_risk(self):
        self.h._risk_only = True
        self._run({'intent': '闲聊', 'risk': 1.0, 'confidence': .9})
        self.h.generator.generate.assert_not_called()
        self.assertIn('applyRiskHold:', self._selectors())

    def test_low_risk_still_generates(self):
        self.h.generator.generate.return_value = {'groups': [], 'elapsed_s': 0.0}
        self._run({'intent': '闲聊', 'risk': 1.0, 'confidence': .9})
        self.h.generator.generate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
