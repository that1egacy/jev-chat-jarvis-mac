"""判断层标定台：指标计算、逐类命中率、门禁与报告输出。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'probe'))
sys.path.insert(0, str(ROOT / 'src'))

import judge_calibration as bench  # noqa: E402
import judge_zh_test  # noqa: E402


class _Judge:
    def __init__(self, mapping, raise_on=()):
        self.mapping = mapping
        self.raise_on = set(raise_on)
        self.calls = []

    def judge(self, message, context=None):
        self.calls.append(message)
        if message in self.raise_on:
            raise RuntimeError('模型挂了')
        return {'intent': self.mapping.get(message, '未知')}


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.cases = [('甲', '派活'), ('乙', '派活'), ('丙', '批评'), ('丁', '闲聊')]

    def test_accuracy_and_per_class(self):
        judge = _Judge({'甲': '派活', '乙': '催进度', '丙': '批评', '丁': '闲聊'})
        report = bench.evaluate(judge, self.cases)
        self.assertEqual(report.total, 4)
        self.assertEqual(report.correct, 3)
        self.assertAlmostEqual(report.accuracy, 0.75)
        self.assertEqual(report.per_class['派活'], [1, 2])
        self.assertEqual(report.per_class['批评'], [1, 1])

    def test_exceptions_are_collected_not_fatal(self):
        judge = _Judge({'甲': '派活'}, raise_on={'乙'})
        report = bench.evaluate(judge, self.cases)
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.total, 4)
        self.assertEqual(len(judge.calls), 4)

    def test_gate(self):
        perfect = bench.evaluate(_Judge({m: e for m, e in self.cases}), self.cases)
        self.assertTrue(perfect.passed(0.85))
        bad = bench.evaluate(_Judge({}), self.cases)
        self.assertFalse(bad.passed(0.85))
        self.assertFalse(bad.passed(0.0))          # 0 命中也不算通过
        with_errors = bench.evaluate(_Judge({m: e for m, e in self.cases},
                                            raise_on={c[0] for c in self.cases}), self.cases)
        self.assertFalse(with_errors.passed(0.0))

    def test_latency_summary_present(self):
        report = bench.evaluate(_Judge({m: e for m, e in self.cases}), self.cases)
        latency = report.latency_summary()
        self.assertIn('mean_ms', latency)
        self.assertIn('p90_ms', latency)


class ReportOutputTests(unittest.TestCase):
    def setUp(self):
        self.cases = [('甲', '派活'), ('乙', '批评')]
        self.report = bench.evaluate(_Judge({'甲': '派活'}), self.cases)

    def test_markdown_contains_table_and_verdict(self):
        text = self.report.to_markdown(0.85)
        self.assertIn('| 派活 |', text)
        self.assertIn('未通过', text)
        self.assertIn('总命中率', text)

    def test_dict_is_json_serialisable(self):
        payload = self.report.to_dict(0.85)
        json.dumps(payload)
        self.assertEqual(payload['total'], 2)
        self.assertIn('per_class', payload)

    def test_cli_writes_reports_and_returns_gate_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cal.json'
            md = Path(tmp) / 'cal.md'
            perfect = {message: intent for message, intent in judge_zh_test.CASES}
            code = bench.main(['--threshold', '0.1', '--out', str(out), '--markdown', str(md)],
                              judge=_Judge(perfect))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['accuracy'], 1.0)
            self.assertIn('通过', md.read_text(encoding='utf-8'))
            failing = bench.main(['--threshold', '0.99'], judge=_Judge({'甲': '派活'}))
            self.assertEqual(failing, 1)

    def test_cli_returns_2_when_the_judge_cannot_be_created(self):
        with patch.object(bench, '_make_judge', side_effect=ImportError('no torch')):
            self.assertEqual(bench.main(['--judge', 'local']), 2)


if __name__ == '__main__':
    unittest.main()
