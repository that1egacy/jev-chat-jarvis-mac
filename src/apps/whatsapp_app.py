"""WhatsApp（macOS Catalyst）适配器：截图 + OCR。

为什么读屏不走 AX：WhatsApp 是 Mac Catalyst 应用，AX 能读到消息文本（AXDescription）和可写输入框，
但消息节点属性完全一致、没有「自己/对方」信号，AXFrame 也不可信（见 #151 实测注释），
因此读屏走截图 OCR，AX 只用于「填入」。
为什么不复用微信解析：微信的 `calibrated_messages` 用「气泡像素检测」判归属，而 WhatsApp 的
接收气泡是极浅灰底，与背景色差低于检测阈值（<7），几乎检不出；本适配器改用**文本块几何**
判归属：左贴聊天区左缘 = 对方（them），右贴聊天区右缘 = 自己（me）。

版式常量来自 1024x768 窗口的实测比例；三栏布局（左导航 / 会话列表 / 聊天区）。
"""
from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import Quartz
import ApplicationServices as AS

import perception
from perception import Message, WindowInfo

KEY = "whatsapp"
DISPLAY_NAME = "WhatsApp"
BUNDLE_IDS = ("net.whatsapp.WhatsApp",)
APP_NAMES = ("WhatsApp", "WhatsApp Desktop")

OWNER_NAMES = ("WhatsApp",)          # 窗口 owner 名带 U+200E 前缀，比较前 strip
_BIDI = "\u200e\u200f\u202a\u202b\u202c"

PANE_X0 = 0.486      # 聊天区左缘（会话列表结束处）
HEADER_Y = 0.055     # 顶部联系人栏高度
INPUT_Y = 0.945      # 输入栏起始（此线以下不算消息）
MAX_MESSAGES = 12

# 借鉴 #140 的「昵称/引用头不并入正文」：群聊里发言人昵称、引用块的首行字号更小。
# 默认开；出现误删可用 export JEV_WHATSAPP_STRIP_SENDER=0 关掉。
STRIP_SENDER = True
try:
    import userconfig as _userconfig
    _raw_strip = _userconfig.get("JEV_WHATSAPP_STRIP_SENDER")
    if _raw_strip is not None:
        STRIP_SENDER = str(_raw_strip).strip().lower() not in ("0", "false", "no", "off")
except Exception:                                  # noqa: BLE001  测试环境无配置也能导入
    pass

DATE_RE = re.compile(r"^(昨天|今天|前天|星期[一二三四五六日天]|\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})")
SYS_RE = re.compile(r"自动消失|更改计时器|已加密|撤回了一条|你已开启|消息已保留")
TIME_TAIL = re.compile(r"\s*\d{1,2}:\d{2}\s*[^\u4e00-\u9fff\w]{0,6}\s*$|\s*\d{1,2}:\d{2}\s*[Ww✓✔/]{0,3}\s*$")



# ── AX（只用于「填入」；读屏仍走 OCR，因为 AX 消息节点无法区分自己/对方）──────────
def _ax_attr(element, name):
    err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None


def _ax_rect(element):
    """AXFrame -> (x, y, w, h)：优先 AXValueGetValue，取不到再从字符串兜底。

    AX 与 CGWindow 的坐标同为左上原点、点单位，可以直接比较（同上游 #92 的结论）。
    """
    frame = _ax_attr(element, "AXFrame")
    if frame is None:
        return None
    try:
        ok, rect = AS.AXValueGetValue(frame, AS.kAXValueCGRectType, None)
        if ok and rect is not None:
            return (float(rect.origin.x), float(rect.origin.y),
                    float(rect.size.width), float(rect.size.height))
    except Exception:                                  # noqa: BLE001  老系统/类型不符
        pass
    m = re.search(r"x:([-\d.]+) y:([-\d.]+) w:([-\d.]+) h:([-\d.]+)", str(frame))
    return tuple(float(m.group(i)) for i in range(1, 5)) if m else None


def _ax_focused_frame(pid: int):
    """应用 AX 焦点窗口的 (x, y, w, h)；读不到返回 None（与上游 #92 同一思路）。"""
    if not pid:
        return None
    try:
        focused = _ax_attr(AS.AXUIElementCreateApplication(int(pid)),
                           AS.kAXFocusedWindowAttribute)
    except Exception:                                  # noqa: BLE001
        return None
    return _ax_rect(focused) if focused is not None else None


def _ax_first_window(pid: int):
    windows = _ax_attr(AS.AXUIElementCreateApplication(pid),
                       AS.kAXWindowsAttribute) or []
    return windows[0] if windows else None


def _ax_text_area(pid: int):
    """窗口里的第一个 AXTextArea（WhatsApp 只有输入框是文本区）。"""
    root = _ax_first_window(pid)
    if root is None:
        return None

    def walk(element, depth=0):
        if depth > 16:
            return None
        if _ax_attr(element, AS.kAXRoleAttribute) == "AXTextArea":
            return element
        for child in _ax_attr(element, AS.kAXChildrenAttribute) or []:
            found = walk(child, depth + 1)
            if found is not None:
                return found
        return None

    return walk(root)


def _ax_text(element) -> str:
    value = _ax_attr(element, AS.kAXValueAttribute)
    return value if isinstance(value, str) else ""


def _clean_owner(name: str) -> str:
    return (name or "").strip().strip(_BIDI + " ")


def _pid_for(bundle: str = BUNDLE_IDS[0]) -> int:
    try:
        import AppKit
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle)
        if apps:
            return int(apps[0].processIdentifier())
    except Exception:
        pass
    return 0


def find_window(previous_wid: int | None = None) -> WindowInfo | None:
    """读用户正在看的窗口：AX 焦点窗口优先，其次沿用上一帧 wid，最后取最大窗口。"""
    pid = _pid_for()
    opts = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    best = None
    eligible: list[WindowInfo] = []
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID):
        if int(w.get("kCGWindowLayer") or 0) != 0:
            continue
        if _clean_owner(w.get("kCGWindowOwnerName") or "") not in OWNER_NAMES:
            continue
        b = dict(w.get("kCGWindowBounds") or {})
        ww, hh = float(b.get("Width", 0)), float(b.get("Height", 0))
        if ww < 400 or hh < 400:      # 排除浮层/气泡/输入法候选等
            continue
        wid = int(w.get("kCGWindowNumber") or 0)
        title = (w.get("kCGWindowName") or "").strip().strip(_BIDI)
        # 主窗口必带标题；无标题的 500x500 浮层/辅助窗一律不猜
        if not title:
            continue
        wi = WindowInfo(wid=wid, pid=pid, title=title,
                        x=float(b.get("X", 0)), y=float(b.get("Y", 0)),
                        w=ww, h=hh)
        eligible.append(wi)
        score = ww * hh
        if previous_wid == wid:
            score += 2e9
        if best is None or score > best[0]:
            best = (score, wi)

    if not eligible:
        return None
    # ① 用户在看的窗口：AX 焦点窗口与候选逐项比对（±2pt，AX/CG 坐标系一致）
    focused = _ax_focused_frame(pid)
    if focused is not None:
        fx, fy, fw, fh = focused
        for wi in eligible:
            if (abs(wi.x - fx) <= 2 and abs(wi.y - fy) <= 2
                    and abs(wi.w - fw) <= 2 and abs(wi.h - fh) <= 2):
                return wi
    # ② 沿用上一帧的 wid（避免等大窗口每 tick 重新挑）
    for wi in eligible:
        if previous_wid == wi.wid:
            return wi
    # ③ 兜底：面积最大
    return max(eligible, key=lambda wi: wi.w * wi.h)


def _rows(blocks):
    rows = []
    for b in sorted(blocks, key=lambda x: 1 - x.y - x.h):
        top = 1 - b.y - b.h
        if rows and abs(top - rows[-1][0]) < 0.010:
            rows[-1][1].append(b)
        else:
            rows.append((top, [b]))
    return rows


def _merge(rows) -> list[dict]:
    merged = []
    for top, grp in rows:
        grp.sort(key=lambda b: b.x)
        text = " ".join(b.text for b in grp).strip()
        if not text or DATE_RE.match(text) or SYS_RE.search(text):
            continue
        maxh = max(b.h for b in grp)
        text = TIME_TAIL.sub("", text).strip()
        if not text or (re.fullmatch(r"\d{1,2}:\d{2}", text) and maxh < 0.014):
            continue
        merged.append({"top": top, "x": min(b.x for b in grp),
                       "right": max(b.x + b.w for b in grp), "h": maxh, "lh": [maxh],
                       "conf": min(b.conf for b in grp), "text": text})
    messages = []
    for m in merged:
        if messages:
            p = messages[-1]
            gap = m["top"] - (p["top"] + p["h"])
            if abs(m["x"] - p["x"]) < 0.04 and -0.004 < gap < 0.028:
                p["text"] += "\n" + m["text"]
                p["right"] = max(p["right"], m["right"])
                p["h"] = m["top"] + m["h"] - p["top"]
                p["conf"] = min(p["conf"], m["conf"])
                p.setdefault("lh", []).append(m["h"])
                continue
        messages.append(dict(m))
    return messages


def _strip_label_line(m: dict) -> None:
    """去掉气泡首行的「发言人昵称 / 引用块头」。

    依据字号：首行明显小于正文行高（<=0.8 倍）、长度 <=16、且不以句末标点结尾，
    才判定为标签行。只对对方消息生效——自己的气泡不显示发言人。
    """
    if not STRIP_SENDER or m.get("side") != "them":
        return
    lines = m["text"].split("\n")
    heights = m.get("lh") or []
    if len(lines) < 2 or len(heights) < 2:
        return
    first = lines[0].strip()
    if not first or len(first) > 16:
        return
    if re.search(r"[。！？!?，,；;：:）)]$", first):
        return
    body_max = max(heights[1:]) or 0
    if body_max <= 0 or heights[0] > body_max * 0.8:
        return
    m["text"] = "\n".join(lines[1:])
    m["lh"] = heights[1:]


def _side(m, pane_x0: float = PANE_X0) -> str:
    if m["right"] >= 0.92:                 # 右贴边 = 自己的绿色气泡
        return "me"
    if m["x"] <= pane_x0 + 0.03:           # 左贴边 = 对方
        return "them"
    center = (m["x"] + m["right"]) / 2
    return "them" if center < (pane_x0 + 1) / 2 else "me"


def _chat_title(blocks, pane_x0: float = PANE_X0, header_y: float = HEADER_Y) -> str:
    cands = [b for b in blocks if b.x >= pane_x0 - 0.01 and (1 - b.y - b.h) < header_y]
    if not cands:
        return ""
    top = min(1 - b.y - b.h for b in cands)
    line = [b for b in cands if (1 - b.y - b.h) - top < 0.014]
    return " ".join(b.text for b in sorted(line, key=lambda b: b.x)).strip()


def parse_image(image, calibration=None) -> dict:
    """按 WhatsApp 版式解析一张窗口截图（不负责截图）。

    calibration 是 Calibration（窗口点尺寸 + 区域）；None 时用内置常量。
    返回 {"messages": [...], "chat_title": str, "n_blocks": int, "bounds": (x0,top,bottom)}。
    """
    blocks = perception.ocr_image(image, chat_only=False)
    parsed = classify_blocks(blocks, calibration)
    return {**parsed, "n_blocks": len(blocks)}


def classify_blocks(blocks, calibration=None) -> dict:
    """把 OCR 文本块按 WhatsApp 版式归类成消息（纯函数，不读屏，单元测试入口）。"""
    if calibration is not None:
        _W, _H = calibration.window_width, calibration.window_height
        pane_x0 = calibration.x / _W
        pane_top = calibration.y / _H
        pane_bottom = (calibration.y + calibration.height) / _H
    else:
        pane_x0, pane_top, pane_bottom = PANE_X0, HEADER_Y, INPUT_Y
    pane = [b for b in blocks
            if b.x >= pane_x0 - 0.01
            and (1 - b.y - b.h) >= pane_top
            and (1 - b.y) <= pane_bottom]
    raw = _merge(_rows(pane))
    msgs: list[Message] = []
    for m in raw:
        side = _side(m, pane_x0)
        m["side"] = side
        _strip_label_line(m)
        msgs.append(Message(text=m["text"], side=side, y=m["top"], conf=m["conf"],
                            h=m["h"], lines=m["text"].split("\n"),
                            x=m["x"], w=m["right"] - m["x"], last_y=m["top"]))
    return {"messages": msgs[-MAX_MESSAGES:],
            "chat_title": _chat_title(blocks, pane_x0, pane_top),
            "n_blocks": len(blocks),
            "bounds": (pane_x0, pane_top, pane_bottom)}


def read_conversation(max_messages: int = MAX_MESSAGES, previous_wid=None,
                      prev_fingerprint=None, prev_layout=None, calibration=None) -> dict:
    t0 = time.perf_counter()
    win = find_window(previous_wid)
    if win is None:
        return {"ok": False, "error": "WhatsApp main window not found", "messages": []}
    window = {"wid": win.wid, "title": win.title, "w": win.w, "h": win.h,
              "x": win.x, "y": win.y}
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "chat.png"
        if not perception.capture_window(win.wid, png):
            return {"ok": False, "error": "capture failed", "messages": []}
        image = perception._load_png_image(png, int(max(win.w, win.h)))
    if image is None:
        return {"ok": False, "error": "capture failed", "messages": []}
    t_cap = time.perf_counter()
    parsed = parse_image(image, calibration)
    msgs = parsed["messages"][-max_messages:]
    elapsed = (time.perf_counter() - t_cap) * 1000
    return {"ok": True, "unchanged": False, "window": window,
            "messages": msgs, "chat_title": parsed["chat_title"],
            "n_blocks": parsed["n_blocks"], "fingerprint": None,
            "layout": (window["wid"], window["w"], window["h"], "whatsapp"),
            "input_rect": None, "input_unresolved": False,
            "timing_ms": {"capture": (t_cap - t0) * 1000, "ocr": elapsed,
                          "total": (t_cap - t0 + elapsed / 1000) * 1000,
                          "capture_path": "subprocess"}}


# AX 输入框定位缓存（借用上游 #143 的节流：成功 1s、失败 3s 再试，窗口 id 变了立即失效）。
_INPUT_CACHE: dict = {"wid": None, "box": None, "rect": None, "reason": "",
                      "next": 0.0}


def locate_input(win: dict) -> dict:
    """定位 WhatsApp 的 AX 输入框；定位不到时给出视觉兜底框（填入走剪贴板）。

    AX 树遍历一次约几毫秒，HUD 每个读屏 tick 都会问，所以按 #143 的做法缓存：
    命中 1s、未命中 3s，避免 box 抖动，也避免失败时每 tick 重走整棵树。
    """
    wid = win.get("wid")
    now = time.monotonic()
    cache = _INPUT_CACHE
    if cache["wid"] == wid and now < cache["next"]:
        return {"box": cache["box"], "rect": cache["rect"], "window": dict(win),
                "reason": cache["reason"]}

    x, y, w, h = win.get("x", 0), win.get("y", 0), win.get("w", 0), win.get("h", 0)
    fallback_rect = (x + (PANE_X0 + 0.01) * w, y + 0.935 * h,
                     (1 - PANE_X0 - 0.03) * w, 0.055 * h)
    pid = int(win.get("pid") or _pid_for())
    try:
        area = _ax_text_area(pid) if pid else None
    except Exception:                                  # noqa: BLE001  AX 不可用走剪贴板
        area = None
    if area is not None:
        rect = _ax_rect(area)
        if rect:
            cache.update(wid=wid, box=area, rect=rect,
                         reason="WhatsApp AX 输入框（可写入）", next=now + 1.0)
            return {"box": area, "rect": rect, "window": dict(win),
                    "reason": cache["reason"]}
    cache.update(wid=wid, box=None, rect=fallback_rect,
                 reason="未取得 AX 输入框，填入改为复制到剪贴板", next=now + 3.0)
    return {"box": None, "rect": fallback_rect, "window": dict(win),
            "reason": cache["reason"]}


def fill_text(text: str, target=None) -> tuple[bool, str]:
    """AX 写入优先（写入后读回校验），失败才回退剪贴板。绝不发送、不合成按键。"""
    box = (target or {}).get("box")
    if box is not None:
        try:
            err = AS.AXUIElementSetAttributeValue(box, AS.kAXValueAttribute, text)
            if err == 0 and _ax_text(box) == text:
                return True, "已写入 WhatsApp 输入框（未发送，如需发送请你自己按回车）"
        except Exception:                              # noqa: BLE001  回退剪贴板
            pass
    try:
        import AppKit
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    except Exception as exc:                     # noqa: BLE001
        return False, f"复制失败：{type(exc).__name__}"
    return False, "已复制到剪贴板，请在 WhatsApp 输入框按 ⌘V 粘贴"


def warm() -> float | None:
    return perception.warm_ocr()


class WhatsAppApp:
    """ChatApp 协议实现（薄封装，全部转调本模块函数）。"""
    key = KEY
    display_name = DISPLAY_NAME
    bundle_ids = BUNDLE_IDS
    app_names = APP_NAMES
    needs_screen_capture = True

    def find_window(self, previous_wid=None):
        return find_window(previous_wid)

    def read_conversation(self, **kwargs):
        return read_conversation(**kwargs)

    def locate_input(self, win):
        return locate_input(win)

    def preview_messages(self, image, calibration, window=None) -> dict:
        """校准预览用：对已截好的图按给定校准区域解析（不重新截图）。"""
        parsed = parse_image(image, calibration)
        return {"messages": parsed["messages"], "chat_title": parsed["chat_title"],
                "n_blocks": parsed["n_blocks"]}

    def fill_text(self, text, target=None):
        return fill_text(text, target=target)

    def warm(self):
        return warm()
