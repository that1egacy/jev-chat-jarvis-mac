"""Apple Mail（macOS 自带）适配器：AX 只读 + AX 写入。

与 QQ 适配器同一路线（`needs_screen_capture=False`）：
- 读：聚焦窗口里的 `AXWebArea`（邮件正文/阅读窗格）逐段取 `AXStaticText`；
- 填：撰写窗口中可写的 `AXTextArea`，AX 设值并读回校验，失败回退复制 + 手动 ⌘V（#139 政策）。
不发送、不点按键、不解密任何邮件数据；只在用户把 Mail 置于前台时工作。

已知边界：
- 只取「阅读窗格」的可见正文（含邮件头里可读的字段），不读附件/图片内容；
- 同一会话里若选中的是自己发出的邮件，仍按「对方」处理（v1 不做收发判定）；
- 撰写窗与阅读窗是不同窗口，填入目标在撰写窗内，面板上的输入框描边只作参考。
"""
from __future__ import annotations

import hashlib
import time

import AppKit
import ApplicationServices as AS

import fill
from perception import Message, WindowInfo

KEY = "mail"
DISPLAY_NAME = "邮件"
BUNDLE_IDS = ("com.apple.mail",)
APP_NAMES = ("Mail", "邮件")

ERR_NO_APP = "没有找到正在运行的「邮件」应用"
ERR_NO_WINDOW = "没有找到邮件主窗口"
ERR_NO_BODY = "阅读窗格暂无可读正文"

MAX_MESSAGES = 12
MIN_BODY_CHARS = 8


class AX:
    """最小 AX 读取工具（与 apps/ax_app.py 同口径，但不互相依赖）。"""

    @staticmethod
    def attr(element, name):
        err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
        return value if err == 0 else None

    def children(self, element):
        return list(self.attr(element, AS.kAXChildrenAttribute) or [])

    def role(self, element) -> str:
        return self.attr(element, AS.kAXRoleAttribute) or ""

    def text_of(self, element) -> str:
        for name in (AS.kAXValueAttribute, AS.kAXDescriptionAttribute,
                     AS.kAXTitleAttribute):
            value = self.attr(element, name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def rect(self, element):
        """AXPosition/AXSize -> (x, y, w, h)；读不到返回 None。"""
        pos = self.attr(element, AS.kAXPositionAttribute)
        size = self.attr(element, AS.kAXSizeAttribute)
        if pos is None or size is None:
            return None
        try:
            ok_p, point = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
            ok_s, extent = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
        except Exception:                                # noqa: BLE001
            return None
        if not (ok_p and ok_s):
            return None
        return (float(point.x), float(point.y),
                float(extent.width), float(extent.height))


_AX = AX()


def _running():
    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        BUNDLE_IDS[0])
    return apps[0] if apps else None


def _app_element(pid: int):
    return AS.AXUIElementCreateApplication(int(pid))


def _windows(pid: int) -> list:
    app = _app_element(pid)
    focused = _AX.attr(app, AS.kAXFocusedWindowAttribute)
    windows = list(_AX.attr(app, AS.kAXWindowsAttribute) or [])
    if focused is not None:
        # 聚焦窗口优先：用户在写邮件时目标就是撰写窗
        windows = [focused] + [w for w in windows if w != focused]
    return windows


def _window_id(pid: int, rect) -> int:
    """按 AX 矩形匹配 CGWindow，拿 hud 需要的 wid（定位/回复缓存用）。"""
    import Quartz
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    for info in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        if info.get("kCGWindowOwnerPID") != pid:
            continue
        bounds = dict(info.get("kCGWindowBounds") or {})
        candidate = (float(bounds.get("X", 0)), float(bounds.get("Y", 0)),
                     float(bounds.get("Width", 0)), float(bounds.get("Height", 0)))
        if all(abs(a - b) <= 2 for a, b in zip(candidate, rect)):
            return int(info.get("kCGWindowNumber") or 0)
    return 0


def _find_all(element, role: str, limit: int = 40) -> list:
    """深度优先收集指定 role 的节点（上限保护，避免遍历整棵树）。"""
    found: list = []

    def walk(node, depth=0):
        if depth > 25 or len(found) >= limit:
            return
        if _AX.role(node) == role:
            found.append(node)
            if len(found) >= limit:
                return
        for child in _AX.children(node):
            walk(child, depth + 1)

    walk(element)
    return found


def _collect_text(root) -> list[str]:
    """按文档顺序收集 AXStaticText / AXHeading / AXLink 的可读文本。"""
    out: list[str] = []
    budget = [2500]

    def walk(node, depth=0):
        if depth > 25 or budget[0] <= 0:
            return
        budget[0] -= 1
        role = _AX.role(node)
        if role in ("AXStaticText", "AXHeading", "AXLink"):
            text = _AX.text_of(node)
            if text:
                out.append(text)
        for child in _AX.children(node):
            walk(child, depth + 1)

    walk(root)
    return out


def _body_lines(win) -> list[str]:
    """阅读窗格的正文：AXWebArea 里文本最多的那棵子树（排除消息列表 AXTable）。"""
    best: list[str] = []
    for web in _find_all(win, "AXWebArea", limit=8):
        lines = _collect_text(web)
        if sum(len(line) for line in lines) > sum(len(line) for line in best):
            best = lines
    if best:
        return best
    # 有些邮件（纯文本/无 WebArea）直接以静态文本呈现：退化为窗口内非表格文本
    fallback: list[str] = []

    def walk(node, depth=0, in_table=False):
        if depth > 25:
            return
        role = _AX.role(node)
        if role == "AXTable":
            in_table = True
        if role in ("AXStaticText", "AXHeading") and not in_table:
            text = _AX.text_of(node)
            if text:
                fallback.append(text)
        for child in _AX.children(node):
            walk(child, depth + 1, in_table)

    walk(win)
    return fallback


def _fingerprint(title: str, body: str) -> str:
    return hashlib.sha1(f"{title}\x1f{body}".encode("utf-8")).hexdigest()[:16]


def find_window(previous_wid=None) -> WindowInfo | None:
    app = _running()
    if app is None:
        return None
    pid = int(app.processIdentifier())
    for win in _windows(pid):
        rect = _AX.rect(win)
        if rect is None or rect[2] < 300 or rect[3] < 200:
            continue                         # 排除浮层/提示窗
        title = _AX.text_of(win) or ""
        return WindowInfo(wid=_window_id(pid, rect) or 0, pid=pid, title=title,
                          x=rect[0], y=rect[1], w=rect[2], h=rect[3])
    return None


def read_conversation(max_messages: int = MAX_MESSAGES, previous_wid=None,
                      prev_fingerprint=None, prev_layout=None, ax=None) -> dict:
    """一次读取：聚焦邮件窗口 → 阅读窗格正文 → 一条「对方」消息。"""
    t0 = time.perf_counter()
    if not fill.has_accessibility():
        return {"ok": False, "error": fill.REASON_NO_ACCESS, "messages": []}
    app = _running()
    if app is None:
        return {"ok": False, "error": ERR_NO_APP, "messages": []}
    pid = int(app.processIdentifier())
    windows = _windows(pid)
    win = next((w for w in windows if (_AX.rect(w) or (0, 0, 0, 0))[2] >= 300), None)
    rect = _AX.rect(win) if win is not None else None
    if win is None or rect is None:
        return {"ok": False, "error": ERR_NO_WINDOW, "messages": []}
    wid = _window_id(pid, rect) or 0
    title = _AX.text_of(win)
    lines = _body_lines(win)
    body = "\n".join(line for line in lines if line).strip()
    layout = (wid, rect[2], rect[3])
    fp = _fingerprint(title, body)
    total = (time.perf_counter() - t0) * 1000
    window = {"wid": wid, "title": title, "x": rect[0], "y": rect[1],
              "w": rect[2], "h": rect[3]}
    editor = _find_editor(windows)
    input_rect = _AX.rect(editor) if editor is not None else None
    base = {"ok": True, "layout": layout, "input_rect": input_rect,
            "input_unresolved": False, "chat_title": title, "window": window,
            "fingerprint": fp, "timing_ms": {"capture": total, "ocr": 0.0,
                                             "total": total, "capture_path": "ax"}}
    if layout == prev_layout and fp == prev_fingerprint:
        return dict(base, unchanged=True, messages=[], n_blocks=0)
    if len(body) < MIN_BODY_CHARS:
        return dict(base, unchanged=False, messages=[], n_blocks=0)
    messages = [Message(text=body, side="them", y=0.5, conf=1.0,
                        lines=[line for line in lines if line],
                        x=0.0, w=1.0, last_y=0.5)][-max_messages:]
    return dict(base, unchanged=False, messages=messages, n_blocks=len(lines))


def _find_editor(windows) -> object | None:
    """撰写窗口里可写的文本区（AXValue 可 set 才算）。"""
    for win in windows:
        for area in _find_all(win, "AXTextArea", limit=6):
            try:
                result = AS.AXUIElementIsAttributeSettable(
                    area, AS.kAXValueAttribute, None)
                settable = result[1] if isinstance(result, tuple) else bool(result)
            except Exception:                            # noqa: BLE001
                settable = False
            if settable:
                return area
    return None


def locate_input(win: dict) -> dict:
    """只读定位：撰写窗的 AX 文本区；没有撰写窗时给出原因（面板显示复制兜底）。"""
    if not fill.has_accessibility():
        return {"box": None, "rect": None, "window": win,
                "reason": fill.REASON_NO_ACCESS}
    app = _running()
    if app is None:
        return {"box": None, "rect": None, "window": win, "reason": ERR_NO_APP}
    editor = _find_editor(_windows(int(app.processIdentifier())))
    rect = _AX.rect(editor) if editor is not None else None
    if editor is None or rect is None:
        return {"box": None, "rect": None, "window": win,
                "reason": "未打开撰写窗口，填入改为复制到剪贴板"}
    return {"box": editor, "rect": rect, "window": win, "reason": "邮件撰写窗输入框（可写入）"}


def _ax_text(element) -> str:
    value = _AX.attr(element, AS.kAXValueAttribute)
    return value if isinstance(value, str) else ""


def fill_text(text: str, target=None) -> tuple[bool, str]:
    """AX 写入优先（读回校验），失败回退复制 + 由用户 ⌘V；绝不发送。"""
    text = (text or "").strip()
    if not text:
        return False, fill.REASON_EMPTY
    box = (target or {}).get("box")
    if box is not None:
        try:
            before = _ax_text(box)
            err = AS.AXUIElementSetAttributeValue(box, AS.kAXValueAttribute, text)
            if err == 0 and _ax_text(box) != before and _ax_text(box).endswith(text):
                return True, "已写入邮件撰写窗口（未发送，请自行检查后发送）"
        except Exception:                                # noqa: BLE001
            pass
    try:
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, AppKit.NSPasteboardTypeString)
    except Exception as exc:                             # noqa: BLE001
        return False, f"复制失败：{type(exc).__name__}"
    return False, "已复制到剪贴板，请打开邮件撰写窗口按 ⌘V 粘贴"


def warm() -> None:
    return None


class MailApp:
    key = KEY
    display_name = DISPLAY_NAME
    bundle_ids = BUNDLE_IDS
    app_names = APP_NAMES
    needs_screen_capture = False

    def find_window(self, previous_wid=None):
        return find_window(previous_wid)

    def read_conversation(self, **kwargs):
        return read_conversation(**kwargs)

    def locate_input(self, win):
        return locate_input(win)

    def fill_text(self, text, target=None):
        return fill_text(text, target=target)

    def warm(self):
        return warm()
