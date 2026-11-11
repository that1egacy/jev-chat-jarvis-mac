"""候选硬检查：4 条规则、只报新引入的表达、开关与中文描述。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import candidate_checks as cc  # noqa: E402


class PromiseRuleTests(unittest.TestCase):
    def test_new_promise_is_flagged(self):
        self.assertIn("unauthorized_promise",
                      cc.audit("这个方案你看下", "放心，包在我身上"))

    def test_promise_already_in_the_source_is_not_flagged(self):
        self.assertEqual(cc.audit("你放心，我一定看完", "好的，我一定看"), [])

    def test_promise_for_someone_else_is_flagged(self):
        self.assertIn("promise_for_others", cc.audit("客户在催", "他会今天给你的"))

    def test_plain_reply_has_no_hits(self):
        self.assertEqual(cc.audit("明天开会吗", "好的，我看下日程"), [])


class DetailRuleTests(unittest.TestCase):
    def test_new_date_or_time_is_flagged(self):
        hits = cc.audit("明天开个会", "明天下午三点可以吗")
        self.assertIn("invented_detail", hits)

    def test_details_present_in_the_source_are_not_flagged(self):
        self.assertEqual(cc.audit("明天下午三点开会", "好的，明天下午三点见"), [])

    def test_number_introduced_by_the_candidate_is_flagged(self):
        self.assertIn("invented_detail", cc.audit("预算报一下", "预算是 3000"))


class OverreachRuleTests(unittest.TestCase):
    def test_overreach_is_flagged(self):
        self.assertIn("overreach", cc.audit("这事怎么办", "就这么定了，按我的来"))

    def test_overreach_already_agreed_is_not_flagged(self):
        self.assertEqual(cc.audit("那就这么定了", "好，就这么定了"), [])


class DescribeAndSwitchTests(unittest.TestCase):
    def test_describe_uses_chinese_labels(self):
        text = cc.describe(["unauthorized_promise", "invented_detail", "nope"])
        self.assertIn("未授权承诺", text)
        self.assertIn("编造数字/时间", text)
        self.assertNotIn("nope", text)

    def test_guard_switch(self):
        for value in (None, "", "1", "true"):
            with patch('userconfig.get', return_value=value):
                self.assertTrue(cc.enabled(), value)
        for value in ("0", "false", "OFF", "no"):
            with patch('userconfig.get', return_value=value):
                self.assertFalse(cc.enabled(), value)

    def test_audit_is_order_stable(self):
        self.assertEqual(cc.audit("", "包在我身上，明天三点，就这么定了"),
                         ["unauthorized_promise", "invented_detail", "overreach"])


if __name__ == '__main__':
    unittest.main()
