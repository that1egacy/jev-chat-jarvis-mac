"""产品主界面（控制台窗口）。

菜单栏之外的一个可停靠 Dock 的 GUI 页面：看当前状态、切场景、开关行为、打开设置/校准。
纯展示 + 调用 hud 已有 action，不改读屏/判断/生成逻辑；关闭窗口后应用回到纯菜单栏形态。
"""
from __future__ import annotations

import AppKit as A
import objc

import modes
import ui_style

PALETTE = ui_style.PALETTE
W, H = 720, 560


def _label(view, text, x, y, w, h, size=13, color=None, bold=False):
    label = A.NSTextField.alloc().initWithFrame_(A.NSMakeRect(x, y, w, h))
    label.setStringValue_(text)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setFont_(A.NSFont.boldSystemFontOfSize_(size) if bold
                   else A.NSFont.systemFontOfSize_(size))
    label.setTextColor_(color or PALETTE["text"])
    view.addSubview_(label)
    return label


def _card(view, x, y, w, h):
    card = A.NSView.alloc().initWithFrame_(A.NSMakeRect(x, y, w, h))
    card.setWantsLayer_(True)
    card.layer().setBackgroundColor_(PALETTE["surface"].CGColor())
    card.layer().setCornerRadius_(12.0)
    view.addSubview_(card)
    return card


class ConsoleController(A.NSObject):
    """控制台窗口控制器；动作方法保持 objc 可调用，其余方法标注 python_method。"""

    @objc.python_method
    def setup(self, hud):
        self.hud = hud
        self.fields = {}
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            A.NSMakeRect(0, 0, W, H),
            A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable
            | A.NSWindowStyleMaskMiniaturizable,
            A.NSBackingStoreBuffered, False)
        self.window.setTitle_("jev-jarvis")
        self.window.setAppearance_(A.NSAppearance.appearanceNamed_(A.NSAppearanceNameAqua))
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(A.NSColor.clearColor())
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)
        self.window.setLevel_(A.NSNormalWindowLevel)
        self._build()
        self.window.center()
        return self

    @objc.python_method
    def _build(self):
        view = A.NSVisualEffectView.alloc().initWithFrame_(A.NSMakeRect(0, 0, W, H))
        view.setMaterial_(getattr(A, "NSVisualEffectMaterialSidebar", 1))
        view.setBlendingMode_(A.NSVisualEffectBlendingModeBehindWindow)
        view.setState_(A.NSVisualEffectStateActive)
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(PALETTE["bg"].CGColor())
        self.window.setContentView_(view)
        self.view = view

        _label(view, "jev-jarvis", 24, H - 52, 240, 30, 22, PALETTE["text"], True)
        _label(view, "聊天意图助手 · 只读感知 · 本地/在线推理", 24, H - 76,
               480, 18, 12, PALETTE["muted"])

        # ---- 状态卡
        card = _card(view, 16, H - 250, W - 32, 150)
        self.fields["app"] = _label(card, "当前应用：—", 16, 112, 340, 20, 13)
        self.fields["scene"] = _label(card, "场景：—", 16, 88, 340, 20, 13)
        self.fields["panel"] = _label(card, "面板：—", 16, 64, 340, 20, 13)
        self.fields["status"] = _label(card, "最近状态：—", 16, 40, W - 80, 20, 12,
                                       PALETTE["muted"])
        self.fields["flag0"] = _label(card, "自动显示：关", 380, 112, 300, 18, 12, PALETTE["muted"])
        self.fields["flag1"] = _label(card, "检测框：关", 380, 90, 300, 18, 12, PALETTE["muted"])
        self.fields["flag2"] = _label(card, "置顶：开", 380, 68, 300, 18, 12, PALETTE["muted"])
        self.fields["flag3"] = _label(card, "读屏：运行中", 380, 46, 300, 18, 12, PALETTE["muted"])

        # ---- 场景
        _label(view, "场景", 24, H - 284, 56, 20, 13, PALETTE["muted"])
        self.scene = A.NSSegmentedControl.alloc().initWithFrame_(
            A.NSMakeRect(90, H - 288, 320, 28))
        self.scene.setSegmentCount_(len(modes.MODES))
        for index, (_key, mode) in enumerate(modes.MODES.items()):
            self.scene.setLabel_forSegment_(mode["name"], index)
            self.scene.setWidth_forSegment_(150, index)
        self.scene.setSelectedSegment_(list(modes.MODES).index(modes.active_key()))
        self.scene.setTarget_(self)
        self.scene.setAction_("sceneChanged:")
        view.addSubview_(self.scene)

        # ---- 行为开关
        _label(view, "行为", 24, H - 326, 56, 20, 13, PALETTE["muted"])
        self.switches = {}
        titles = (("autoshow", "有新消息时自动显示"),
                  ("boxes", "YOLO 检测框"),
                  ("pinned", "固定在最前面"),
                  ("paused", "暂停读屏"))
        for index, (key, title) in enumerate(titles):
            button = A.NSButton.alloc().initWithFrame_(
                A.NSMakeRect(90 + (index % 2) * 300, H - 332 - (index // 2) * 34, 280, 22))
            button.setButtonType_(A.NSButtonTypeSwitch)
            button.setTitle_(title)
            button.setFont_(A.NSFont.systemFontOfSize_(12))
            button.setTarget_(self)
            button.setAction_("toggleFlag:")
            button.setTag_(index)
            view.addSubview_(button)
            self.switches[key] = button

        # ---- 操作按钮
        _label(view, "操作", 24, H - 406, 56, 20, 13, PALETTE["muted"])
        actions = (
            ("显示 / 收起面板", "collapsePanel:", 90),
            ("打开设置…", "openSettings:", 220),
            ("校准区域…", "calibrateMessages:", 350),
            ("立即分析", "reanalyze:", 480),
        )
        for title, selector, x in actions:
            button = A.NSButton.buttonWithTitle_target_action_(title, self, "doAction:")
            button.setFrame_(A.NSMakeRect(x, H - 414, 120, 30))
            button.setIdentifier_(selector)
            view.addSubview_(button)

        self.quit_button = A.NSButton.buttonWithTitle_target_action_(
            "退出 jev-jarvis", self, "quitApp:")
        self.quit_button.setFrame_(A.NSMakeRect(24, 24, 140, 30))
        view.addSubview_(self.quit_button)
        _label(view, "关闭窗口不退出：点 Dock 图标或菜单栏 J 可重新打开。", 24, 62,
               460, 18, 11, PALETTE["muted"])

        self.refresh()

    # ------------------------------------------------------------- actions
    @objc.python_method
    def refresh(self):
        state = self.hud.console_state() if self.hud else {}
        self.fields["app"].setStringValue_(f"当前应用：{state.get('app_name', '—')}")
        self.fields["scene"].setStringValue_(f"场景：{state.get('scene_name', '—')}")
        visible = "显示中" if state.get("panel_visible") else "隐藏（菜单栏可开）"
        self.fields["panel"].setStringValue_(f"面板：{visible}")
        self.fields["status"].setStringValue_(f"最近状态：{state.get('status_text', '—')}")
        self.fields["flag0"].setStringValue_(
            "自动显示：" + ("开" if state.get("autoshow") else "关"))
        self.fields["flag1"].setStringValue_(
            "检测框：" + ("开" if state.get("boxes") else "关"))
        self.fields["flag2"].setStringValue_(
            "置顶：" + ("开" if state.get("always_top") else "关"))
        self.fields["flag3"].setStringValue_(
            "读屏：" + ("已暂停" if state.get("paused") else "运行中"))
        self.scene.setSelectedSegment_(list(modes.MODES).index(modes.active_key()))
        mapping = {"autoshow": state.get("autoshow"), "boxes": state.get("boxes"),
                   "pinned": state.get("always_top"), "paused": state.get("paused")}
        for key, button in self.switches.items():
            button.setState_(A.NSControlStateValueOn if mapping.get(key)
                             else A.NSControlStateValueOff)

    def sceneChanged_(self, sender):
        keys = list(modes.MODES)
        index = sender.selectedSegment()
        if 0 <= index < len(keys):
            self.hud.apply_scene(keys[index])
        self.refresh()

    def toggleFlag_(self, sender):
        handler = {0: "toggleAutoshow_", 1: "toggleBoxes_",
                   2: "toggleAlwaysOnTop_", 3: "togglePause_"}[sender.tag()]
        getattr(self.hud, handler)(None)
        self.refresh()

    def doAction_(self, sender):
        getattr(self.hud, str(sender.identifier()))(None)
        self.refresh()

    def quitApp_(self, sender):
        A.NSApp.terminate_(None)

    # ------------------------------------------------------------- window
    @objc.python_method
    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        if getattr(self, "timer", None) is None:
            self.timer = A.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, self, "tick:", None, True)
        self.refresh()

    def tick_(self, timer):
        self.refresh()

    def windowWillClose_(self, notification):
        timer = getattr(self, "timer", None)
        if timer is not None:
            timer.invalidate()
            self.timer = None
        if self.hud is not None:
            self.hud.on_console_closed()


@objc.python_method
def build_console(hud):
    controller = ConsoleController.alloc().init()
    return controller.setup(hud)
