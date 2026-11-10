"""生成总超时、滚动历史门、内置明文中转开关、适配器健康文案。"""
import types
import unittest
from unittest.mock import patch

import generate
from apps import registry


class _FakeStream:
    """最小 SSE 响应：一行 data satisfied 迭代协议 + headers。"""

    def __init__(self, lines):
        self._lines = lines
        self.headers = {'content-type': 'text/event-stream'}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


class DeadlineTests(unittest.TestCase):
    def test_deadline_setting_accepts_env_and_rejects_junk(self):
        with patch('userconfig.get', return_value='20'):
            self.assertEqual(generate._deadline_setting(), 20.0)
        with patch('userconfig.get', return_value='abc'):
            self.assertEqual(generate._deadline_setting(), generate.DEFAULT_DEADLINE_S)
        with patch('userconfig.get', return_value='999'):
            self.assertEqual(generate._deadline_setting(), generate.DEFAULT_DEADLINE_S)
        with patch('userconfig.get', return_value=None):
            self.assertEqual(generate._deadline_setting(), generate.DEFAULT_DEADLINE_S)

    def test_stream_raises_when_total_deadline_is_exhausted(self):
        gen = generate.Generator()
        gen.deadline_s = 0.0
        body = {'model': 'm'}
        line = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n'
        with patch.object(generate.urllib.request, 'urlopen',
                          return_value=_FakeStream([line])):
            with self.assertRaises(generate.RequestTimeout):
                gen._stream_openai('http://x', {}, body, 'm', 'alt', lambda frag: None)

    def test_timeout_becomes_a_retryable_error_on_screen(self):
        gen = generate.Generator()
        with patch.object(generate.Generator, '_call',
                          side_effect=generate.RequestTimeout('t')):
            texts, error = gen._one_tone('在吗', '闲聊', '高情商话术')
        self.assertEqual(texts, [])
        self.assertIn('超时', error)
        self.assertIn('重试', error)


class ScrollGateTests(unittest.TestCase):
    @staticmethod
    def _msgs(*texts):
        return [types.SimpleNamespace(text=text) for text in texts]

    def test_new_message_below_the_previous_one_is_not_scroll(self):
        messages = self._msgs('一', '二', '三')
        self.assertFalse(chat_context_scrolled('二', 2, messages))

    def test_older_target_above_the_previous_one_is_scroll(self):
        messages = self._msgs('一', '二', '三')
        self.assertTrue(chat_context_scrolled('三', 1, messages))

    def test_previous_message_out_of_view_is_never_guessed_as_scroll(self):
        messages = self._msgs('十一', '十二', '十三')
        self.assertFalse(chat_context_scrolled('三', 2, messages))

    def test_no_previous_target_means_not_scroll(self):
        self.assertFalse(chat_context_scrolled(None, 0, self._msgs('一')))


def chat_context_scrolled(previous_text, newest_index, messages):
    import chat_context
    return chat_context.scrolled_back(previous_text, newest_index, messages)


class BuiltinSwitchTests(unittest.TestCase):
    def test_switch_values(self):
        for value in ('1', 'true', 'YES', ' on '):
            with patch('userconfig.get', return_value=value):
                self.assertTrue(generate._builtin_disabled(), value)
        for value in ('', '0', 'no', None):
            with patch('userconfig.get', return_value=value):
                self.assertFalse(generate._builtin_disabled(), value)

    def test_disabled_switch_skips_builtin_credentials(self):
        empty = {'key': '', 'base': None, 'model': None, 'source': ''}
        with patch('userconfig.provider', return_value=empty), \
             patch.object(generate.builtin, 'API_KEY', 'sk-builtin-placeholder'), \
             patch('userconfig.get',
                   side_effect=lambda name: '1' if name == 'JEV_DISABLE_BUILTIN' else None):
            base, key, model, source, api = generate.load_credentials()
        self.assertEqual(key, '')
        self.assertNotEqual(source, generate.BUILTIN_SOURCE)

    def test_enabled_switch_still_uses_builtin(self):
        empty = {'key': '', 'base': None, 'model': None, 'source': ''}
        with patch('userconfig.provider', return_value=empty), \
             patch.object(generate.builtin, 'API_KEY', 'sk-builtin-placeholder'), \
             patch.object(generate.builtin, 'BASE_URL', 'https://example.com/v1'), \
             patch.object(generate, '_resolve_builtin_model', return_value='glm-4-flash'), \
             patch('userconfig.get', return_value=None):
            _base, key, _model, source, _api = generate.load_credentials()
        self.assertEqual(key, 'sk-builtin-placeholder')
        self.assertEqual(source, generate.BUILTIN_SOURCE)


class ReadHealthTests(unittest.TestCase):
    def test_never_read(self):
        self.assertIn('尚未成功', registry.read_health_text({}, 'wechat', now=1000))

    def test_recent_failure_shows_seconds_minutes_hours(self):
        self.assertIn('30s', registry.read_health_text({'wechat': 970}, 'wechat', now=1000))
        self.assertIn('分钟', registry.read_health_text({'wechat': 1000 - 180}, 'wechat', now=1000))
        self.assertIn('小时', registry.read_health_text({'wechat': 1000 - 7200}, 'wechat', now=1000))
        self.assertIn('刚刚', registry.read_health_text({'wechat': 999}, 'wechat', now=1000))

    def test_other_app_does_not_borrow_the_stamp(self):
        self.assertIn('尚未成功', registry.read_health_text({'wechat': 999}, 'mail', now=1000))


if __name__ == '__main__':
    unittest.main()
