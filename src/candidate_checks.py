"""候选硬检查：对准备填入的候选做静态风险检查（借鉴 Android CandidateCheck 核心 4 条）。

上游用模型逐条 yes/no；这里先落 4 条**模型无关**的规则，生成之后、填入之前跑：
命中只做提示 + 要求二次确认，**不自动改写候选**——用户要发的话不该被静默替换。

规则（与源消息/上下文里的同一表达比对，只在「候选新引入」时命中）：
1. 未授权承诺：一定 / 保证 / 包在我身上 / 我马上办 …
2. 替别人承诺：他会 / 对方一定 / 公司保证 …
3. 编造数字或时间：源消息里没有的日期、时间点、数量
4. 越权拍板：就这么定了 / 我说了算 / 不用问了 …

关掉检查：`JEV_CANDIDATE_GUARD=0`（关掉后仍然保留 ChatDiff 的「聊天变了要二次确认」）。
"""
from __future__ import annotations

import re

PROMISE = re.compile(r"一定|保证|肯定能|包在我身上|我马上|我立刻|我负责|放心交给我|我来搞定")
OTHERS_PROMISE = re.compile(r"(?:他|她|他们|她们|对方|公司|团队|老板)(?:会|一定|肯定|保证|负责)")
OVERREACH = re.compile(r"就这么定了|我说了算|我决定了|不用问了|拍板|一言为定")
DETAIL = re.compile(
    r"\d+"
    r"|[零一二三四五六七八九十百千万两半]+\s*(?:点|号|日|天|周|个月|年)"
    r"|今天|明天|后天|昨天|下周|周[一二三四五六日天]|上午|下午|晚上"
)

CHECKS: dict[str, tuple[str, re.Pattern]] = {
    "unauthorized_promise": ("未授权承诺", PROMISE),
    "promise_for_others": ("替别人承诺", OTHERS_PROMISE),
    "invented_detail": ("编造数字/时间", DETAIL),
    "overreach": ("越权拍板", OVERREACH),
}


def _tokens(pattern: re.Pattern, text: str) -> set[str]:
    return {match.group(0) for match in pattern.finditer(text or "")}


def enabled() -> bool:
    """`JEV_CANDIDATE_GUARD`：0/false/off/no 关闭，其余（含未配置）开启。"""
    try:
        import userconfig
        raw = userconfig.get("JEV_CANDIDATE_GUARD")
    except Exception:                                    # noqa: BLE001
        raw = None
    return str(raw or "").strip().lower() not in ("0", "false", "off", "no")


def audit(message: str, candidate: str, context: str = "") -> list[str]:
    """返回命中的规则 id（顺序固定）。候选为空或没有新引入的风险表达时返回 []。"""
    source = f"{message or ''}\n{context or ''}"
    hits = []
    for check_id, (_label, pattern) in CHECKS.items():
        introduced = _tokens(pattern, candidate or "") - _tokens(pattern, source)
        if introduced:
            hits.append(check_id)
    return hits


def describe(hits: list[str]) -> str:
    """把命中 id 折成一句中文，用于状态行。"""
    labels = [CHECKS[hit][0] for hit in hits if hit in CHECKS]
    return "、".join(labels)
