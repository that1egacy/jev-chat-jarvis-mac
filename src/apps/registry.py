"""按前台 App 分发到适配器。

frontmost_app() 三种返回值必须区分：某个适配器（在聊天 App 里）、None（在别的 App 里，
是一次真正的「离开」）、UNKNOWN（NSWorkspace 查询失败，不是离开的证据——HUD 对它冻结一个
短 tick，与原来 frontmost_app_is_wechat() 返回 None 的处理一致）。
"""
from __future__ import annotations

import modes

from apps.ax_app import AXApp
from apps.capture_app import CaptureApp
from apps.whatsapp_app import WhatsAppApp

UNKNOWN = object()          # 前台查询失败的哨兵；`is` 比较
APPS = (CaptureApp(), AXApp(), WhatsAppApp())


def _frontmost():
    """(bundle_id, localized_name) of the frontmost app, or None when the query fails."""
    try:
        import AppKit
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        return (app.bundleIdentifier() or "", app.localizedName() or "")
    except Exception:
        return None


def match(bundle: str, name: str):
    """先按 bundle id、再按显示名精确匹配——名字相近的兄弟应用不算。

    #153：再按当前场景的渠道白名单过滤；不在白名单里的聊天应用视为「离开」。
    """
    found = None
    for app in APPS:
        if bundle and bundle in app.bundle_ids:
            found = app
            break
    if found is None:
        for app in APPS:
            if name in app.app_names:
                found = app
                break
    if found is not None and not modes.allows(found.key):
        return None
    return found


def frontmost_app():
    ident = _frontmost()
    if ident is None:
        return UNKNOWN
    return match(*ident)


def app_by_key(key: str):
    for app in APPS:
        if app.key == key:
            return app
    return None
