"""场景预设（#153）：按场景限定渠道白名单与默认话术。

- 通讯类（im）：当前全部 IM 渠道 + 现有三格话术。
- 工作·邮件类（work）：正式文体话术；邮件的渠道适配（#152）落地前，先沿用 IM 渠道，
  白名单里预留 "mail"，等 Apple Mail 适配器注册后无需再改这里。
"""
from __future__ import annotations

MODES: dict[str, dict] = {
    "im": {
        "name": "通讯类",
        "apps": ("wechat", "qq", "whatsapp"),
        "tones": ("高情商话术", "卑微乙方", "狗头军师会撩"),
    },
    "work": {
        "name": "工作·邮件类",
        "apps": ("wechat", "qq", "whatsapp", "mail"),
        "tones": ("高情商话术", "稳如老狗", "拒绝加班"),
    },
}
DEFAULT_KEY = "im"


def _initial_key() -> str:
    """启动时的场景：env 的 JEV_SCENE 优先（合法值才认，否则回默认）。"""
    try:
        import userconfig
        key = (userconfig.get("JEV_SCENE") or "").strip().lower()
    except Exception:                                    # noqa: BLE001
        return DEFAULT_KEY
    return key if key in MODES else DEFAULT_KEY


_active = _initial_key()


def active_key() -> str:
    return _active


def active() -> dict:
    return MODES[_active]


def set_active(key: str) -> dict:
    """切换场景；未知 key 抛 ValueError（由调用方决定怎么提示）。"""
    global _active
    if key not in MODES:
        raise ValueError(f"未知场景: {key}")
    _active = key
    return MODES[key]


def allows(app_key: str) -> bool:
    """该渠道在当前场景的白名单内吗。"""
    return app_key in active()["apps"]


def tones() -> tuple[str, ...]:
    return tuple(active()["tones"])
