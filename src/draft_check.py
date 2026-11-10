"""草稿自查：只读输入框里我自己写的文字，用判断层给意图 / 风险 / 建议。

边界：
- 只读。不写入、不清空、不发送、不进剪贴板。
- 不外发：走当前判断层（`local` 是本地小模型，默认；切到 `cloud` 时这条草稿会发给
  配置的判断服务——与「判断对方消息」同一条路径，README 已注明）。
- 只给一句提示，不把草稿写进日志（日志只记耗时与意图名）。
"""
from __future__ import annotations

MAX_DRAFT_CHARS = 500      # 判断层窗口很小，草稿再长也只截前 500 字参与判断


def summarize(verdict: dict) -> str:
    """把判断结果折成一行面板文案。"""
    intent = (verdict or {}).get("intent") or "?"
    risk = (verdict or {}).get("risk")
    actions = (verdict or {}).get("actions") or []
    parts = [f"草稿自查：意图「{intent}」"]
    if isinstance(risk, (int, float)):
        parts.append(f"风险 {float(risk):.1f}/9")
    if actions:
        parts.append("建议 " + "；".join(str(a) for a in actions[:2]))
    return " · ".join(parts)


def check(judge, text: str) -> tuple[str, str]:
    """返回 (一行摘要, 错误)。空草稿直接提示，不调用判断层。"""
    draft = (text or "").strip()
    if not draft:
        return "", "草稿是空的：先在输入框里写点内容再自查"
    try:
        verdict = judge.judge(draft[:MAX_DRAFT_CHARS])
    except Exception as exc:                            # noqa: BLE001
        return "", f"草稿自查失败：{type(exc).__name__}"
    if not isinstance(verdict, dict):
        return "", "草稿自查失败：判断层返回格式异常"
    return summarize(verdict), ""
