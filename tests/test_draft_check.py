"""草稿自查：只读读取、判断层复用、文案与隐私边界。"""
import unittest
from unittest.mock import Mock, patch

import draft_check
import fill


class _Judge:
    def __init__(self, verdict=None, exc=None):
        self.calls = []
        self._verdict = verdict
        self._exc = exc

    def judge(self, text, context=None):
        self.calls.append(text)
        if self._exc:
            raise self._exc
        return self._verdict


class SummarizeTests(unittest.TestCase):
    def test_full_verdict(self):
        text = draft_check.summarize({'intent': '批评', 'risk': 6.4,
                                      'actions': ['先确认需求', '别急着解释']})
        self.assertIn('批评', text)
        self.assertIn('6.4/9', text)
        self.assertIn('先确认需求', text)

    def test_missing_fields_degrade(self):
        self.assertIn('?', draft_check.summarize({}))
        self.assertNotIn('/9', draft_check.summarize({'intent': '闲聊'}))


class CheckTests(unittest.TestCase):
    def test_empty_draft_does_not_call_the_judge(self):
        judge = _Judge({'intent': '闲聊'})
        summary, error = draft_check.check(judge, '   ')
        self.assertEqual(summary, '')
        self.assertIn('空', error)
        self.assertEqual(judge.calls, [])

    def test_success_returns_a_one_line_summary_without_the_draft(self):
        judge = _Judge({'intent': '请求', 'risk': 3.0, 'actions': ['给个时间']})
        summary, error = draft_check.check(judge, '明天能把报告发我吗')
        self.assertEqual(error, '')
        self.assertIn('请求', summary)
        self.assertNotIn('报告', summary)      # 摘要里不带草稿正文

    def test_long_draft_is_truncated_before_the_judge(self):
        judge = _Judge({'intent': '闲聊'})
        draft_check.check(judge, '字' * (draft_check.MAX_DRAFT_CHARS + 200))
        self.assertEqual(len(judge.calls[0]), draft_check.MAX_DRAFT_CHARS)

    def test_judge_failure_becomes_a_readable_error(self):
        summary, error = draft_check.check(_Judge(exc=RuntimeError('boom')), '在吗')
        self.assertEqual(summary, '')
        self.assertIn('RuntimeError', error)

    def test_non_dict_verdict_is_an_error(self):
        summary, error = draft_check.check(_Judge('nonsense'), '在吗')
        self.assertEqual(summary, '')
        self.assertIn('格式异常', error)


class ReadDraftTests(unittest.TestCase):
    def test_missing_box_reports_the_adapter_reason(self):
        text, reason = fill.read_draft({'box': None, 'reason': '输入控件已定位，文字不可读取'})
        self.assertEqual(text, '')
        self.assertIn('文字不可读取', reason)

    def test_reads_and_strips_the_value(self):
        with patch.object(fill, '_ax_value', return_value='  明天见  '):
            text, reason = fill.read_draft({'box': object()})
        self.assertEqual((text, reason), ('明天见', ''))

    def test_unreadable_value_reports_the_boundary(self):
        with patch.object(fill, '_ax_value', return_value=None):
            text, reason = fill.read_draft({'box': object()})
        self.assertEqual(text, '')
        self.assertIn('不暴露文字', reason)


if __name__ == '__main__':
    unittest.main()
