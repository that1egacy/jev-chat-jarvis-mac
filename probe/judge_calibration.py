#!/usr/bin/env python3
"""判断层标定台：跑 22 条意图回归，出逐类命中率 / 延迟 / 退出码门禁。

借鉴上游 Android 的 `cn/tools/jev/calibrate.py`：把「回归能跑」升级成「可对比的报告」——
每次改判断层 prompt 或换模型后，跑一遍就能看到总命中率、每一类的命中率、延迟分位，
并且用退出码直接进 CI（0 通过 / 1 不达标 / 2 环境问题）。

用法：
    uv run python probe/judge_calibration.py                 # 自动选判断层（cloud 优先）
    uv run python probe/judge_calibration.py --judge local   # 强制本地 decider-2b
    uv run python probe/judge_calibration.py --out cal.json --markdown cal.md
    uv run python probe/judge_calibration.py --threshold .88 # 改通过门限

注意：本地判断要先把 decider-2b 下到本机（首次会下载 ~3.8GB）。纯离线环境的 CI 用
`evaluate()` 注入假 judge 即可，不需要跑这个 CLI。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import judge as judge_mod  # noqa: E402
import judge_zh_test  # noqa: E402

DEFAULT_THRESHOLD = 0.85        # 上游 README 的 86.4% 是无上下文基线，留一点余量
DEFAULT_EXIT_GATE = 2           # 判定错误（异常）达到这个数就不通过


@dataclass
class Report:
    total: int = 0
    correct: int = 0
    per_class: dict[str, list[int]] = field(default_factory=dict)   # 类 -> [命中, 总数]
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def latency_summary(self) -> dict:
        if not self.latencies_ms:
            return {}
        values = sorted(self.latencies_ms)
        return {
            "mean_ms": round(statistics.fmean(values), 1),
            "p50_ms": round(values[len(values) // 2], 1),
            "p90_ms": round(values[min(len(values) - 1, int(len(values) * .9))], 1),
        }

    def class_rows(self) -> list[tuple[str, float, int, int]]:
        rows = []
        for name, (hit, total) in sorted(self.per_class.items(), key=lambda kv: kv[0]):
            rows.append((name, hit / total if total else 0.0, hit, total))
        return rows

    def passed(self, threshold: float = DEFAULT_THRESHOLD,
               max_errors: int = DEFAULT_EXIT_GATE) -> bool:
        # 至少命中一条才算通过：门限设成 0 也不能把「全错」判成合格。
        return (self.total > 0 and self.correct > 0
                and self.accuracy >= threshold and len(self.errors) < max_errors)

    def to_dict(self, threshold: float = DEFAULT_THRESHOLD) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "threshold": threshold,
            "passed": self.passed(threshold),
            "per_class": {name: {"hit": hit, "total": total, "accuracy": round(hit / total, 4)}
                          for name, (hit, total) in sorted(self.per_class.items())},
            "latency": self.latency_summary(),
            "errors": self.errors,
        }

    def to_markdown(self, threshold: float = DEFAULT_THRESHOLD) -> str:
        lines = [
            "# 判断层标定",
            "",
            f"- 用例：{self.total} 条，命中 {self.correct} 条",
            f"- 总命中率：**{self.accuracy:.1%}**（门限 {threshold:.0%}，"
            f"{'通过' if self.passed(threshold) else '未通过'}）",
        ]
        latency = self.latency_summary()
        if latency:
            lines.append(f"- 延迟：均值 {latency['mean_ms']}ms · P50 {latency['p50_ms']}ms"
                         f" · P90 {latency['p90_ms']}ms")
        if self.errors:
            lines.append(f"- 异常：{len(self.errors)} 次")
        lines += ["", "| 意图 | 命中率 | 命中/总数 |", "|---|---|---|"]
        for name, accuracy, hit, total in self.class_rows():
            lines.append(f"| {name} | {accuracy:.0%} | {hit}/{total} |")
        return "\n".join(lines) + "\n"


def evaluate(judge, cases=None, clock=time.perf_counter) -> Report:
    """跑一遍用例；单条异常记进 errors，不中断整轮（一条坏数据不该毁掉报告）。"""
    cases = judge_zh_test.CASES if cases is None else cases
    report = Report()
    for message, expected in cases:
        report.total += 1
        hit, total = report.per_class.get(expected, [0, 0])
        report.per_class[expected] = [hit, total + 1]
        started = clock()
        try:
            verdict = judge.judge(message)
        except Exception as exc:                           # noqa: BLE001
            report.errors.append(f"{message[:20]} -> {type(exc).__name__}")
            continue
        finally:
            report.latencies_ms.append((clock() - started) * 1000)
        got = (verdict or {}).get("intent")
        if got == expected:
            report.correct += 1
            report.per_class[expected][0] += 1
    return report


def _make_judge(which: str):
    if which == "cloud":
        import judge_jev
        return judge_jev.JevJudge()
    if which == "local":
        return judge_mod.Judge()
    return judge_mod.make_judge()


def main(argv: list[str] | None = None, judge=None) -> int:
    parser = argparse.ArgumentParser(description="判断层标定台（22 条意图回归）")
    parser.add_argument("--judge", choices=("auto", "local", "cloud"), default="auto")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--out", type=Path, help="把 JSON 报告写到这个路径")
    parser.add_argument("--markdown", type=Path, help="把 Markdown 报告写到这个路径")
    args = parser.parse_args(argv)

    if judge is None:
        try:
            judge = _make_judge(args.judge)
        except Exception as exc:                           # noqa: BLE001
            print(f"无法初始化判断层：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    report = evaluate(judge)
    print(report.to_markdown(args.threshold))
    if args.out:
        args.out.write_text(json.dumps(report.to_dict(args.threshold),
                                       ensure_ascii=False, indent=1), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(report.to_markdown(args.threshold), encoding="utf-8")
    return 0 if report.passed(args.threshold) else 1


if __name__ == "__main__":
    raise SystemExit(main())
