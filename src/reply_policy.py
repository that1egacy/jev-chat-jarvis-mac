"""回复策略（NextStep 的本地化最小版）：由判断结果决定「给不给候选」。

上游 Android 的 NextStep 有 6 个状态、还带立场选择 UI；这里只取对 macOS 版立刻有用
的一半——判断完先问一句「这轮该不该给候选」，避免在明显高风险或判断没把握时硬塞三条
回复让用户去选。

状态：
- hold    风险过高（或用户开了「只给风险」/群聊模式）→ 只展示判断与建议，不生成候选
- clarify 意图把握太低 → 仍给候选，但明确提示「先确认对方意思」
- caution 风险偏高 → 给候选，状态行提示风险
- draft   正常给候选
"""
from __future__ import annotations

HOLD_RISK = 8.0          # 风险 ≥8：只给风险与建议
CAUTION_RISK = 6.0       # 风险 ≥6：给候选但提示
CLARIFY_CONFIDENCE = 0.35  # 意图置信度 <0.35：先提示确认


def risk_only_default() -> bool:
    """`JEV_RISK_ONLY=1` 时启动即进入「只给风险」（群聊场景可当手动模式用）。"""
    try:
        import userconfig
        raw = userconfig.get("JEV_RISK_ONLY")
    except Exception:                                    # noqa: BLE001
        raw = None
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def decide(verdict: dict | None, *, risk_only: bool = False) -> str:
    """返回 'hold' / 'clarify' / 'caution' / 'draft'。verdict 缺失时按 draft 处理。"""
    if risk_only:
        return "hold"
    verdict = verdict or {}
    try:
        risk = float(verdict.get("risk") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    try:
        confidence = float(verdict.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if risk >= HOLD_RISK:
        return "hold"
    if confidence and confidence < CLARIFY_CONFIDENCE:
        return "clarify"
    if risk >= CAUTION_RISK:
        return "caution"
    return "draft"


def status_line(state: str, verdict: dict | None = None, *, risk_only: bool = False) -> str:
    """状态行文案；只写风险/建议，不写候选与消息正文。"""
    verdict = verdict or {}
    risk = verdict.get("risk")
    risk_text = f"风险 {float(risk):.1f}/9" if isinstance(risk, (int, float)) else "风险未知"
    if state == "hold":
        why = "已切换到「只给风险」" if risk_only else "风险偏高，只给建议"
        return f"{why}（{risk_text}）：先别急着回，看看判断与建议"
    if state == "clarify":
        return f"意图把握不高：先确认对方意思（{risk_text}）"
    if state == "caution":
        return f"提醒：{risk_text}，发之前想一下"
    return ""
