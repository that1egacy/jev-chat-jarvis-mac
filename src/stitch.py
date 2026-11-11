"""跨屏拼接（读更多历史）的纯算法：重叠对缝 + 断层保留。

只做拼接，**不做滚动**。真正滚动会向目标应用写输入事件，违反本项目「唯一写动作是
用户点击填入」的约束；这里先把算法与回归做好，等明确批准再谈接入。

对缝规则（借鉴上游 Android `core/stitch/Stitcher.kt`）：用「上一帧尾部 k 条 == 新帧
头部 k 条」对齐，k≥2 才算可靠重叠（k=1 可能只是同一句短消息重复）。没有可靠重叠就
当成断层：不拼接，只有新帧自己，避免把两段不相邻的历史接在一起。
"""
from __future__ import annotations

MIN_OVERLAP = 2


def overlap(previous, current, min_overlap: int = MIN_OVERLAP) -> int:
    """返回可拼接的重叠条数；0 表示没有可靠重叠。"""
    if not previous or not current:
        return 0
    limit = min(len(previous), len(current))
    for k in range(limit, min_overlap - 1, -1):
        if _same(previous[-k:], current[:k]):
            return k
    return 0


def _text(item):
    return item.text if hasattr(item, "text") else item[0]


def _side(item):
    if hasattr(item, "side"):
        return item.side
    return item[1] if len(item) > 1 else ""


def _same(left, right) -> bool:
    """逐条比正文 + 方向；元数据（sender/y）跨帧会变，不参与。"""
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if _text(a) != _text(b) or _side(a) != _side(b):
            return False
    return True


def merge(previous, current, min_overlap: int = MIN_OVERLAP) -> tuple[list, bool]:
    """把新一帧接到已读历史上。返回 (合并结果, 是否接上)。

    接不上（断层）时只返回新帧：历史不跨未知断层拼接，与 chat_context 的口径一致。
    """
    if not previous:
        return list(current), True
    k = overlap(previous, current, min_overlap)
    if not k:
        return list(current), False
    return list(previous) + list(current[k:]), True


def merge_frames(frames, min_overlap: int = MIN_OVERLAP) -> list:
    """按顺序拼接多帧；任何一帧接不上就从此重新开始（保留已拼好的段落）。"""
    merged: list = []
    for frame in frames or []:
        merged, _joined = merge(merged, frame, min_overlap)
    return merged
