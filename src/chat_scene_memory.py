"""按会话记住上次选的话术场景（#153 场景预设的会话级记忆）。

隐私边界：**标题不落原文**。索引键是 `sha256(salt:app_key:title)` 的前 16 位——
salt 每台机器随机生成一次、与索引存在同一个文件里。这避免了明文泄露，但**不能抵御
拿到文件后的字典猜测**（常见联系人群名可以被枚举），64 位截断也有极低碰撞概率；
这个文件只用于「同一个聊天切回同一个场景」，威胁模型不要求更强保护。

存储格式（`~/Library/Application Support/jev-jarvis/chat_scenes.json`，权限 600）：

    {"salt": "…", "scenes": {"<hash>": "im" | "work", …}}

写入是原子替换；超过 `MAX_ENTRIES` 丢最旧的一条（dict 保序，重新 `remember`
会把它移到末尾，所以顺序近似 LRU）。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

MAX_ENTRIES = 200
FILE_NAME = "chat_scenes.json"


def default_path() -> Path:
    """与会话历史同一个目录，便于一起备份/清理。"""
    return Path.home() / "Library/Application Support/jev-jarvis" / FILE_NAME


class ChatSceneMemory:
    """会话 → 场景的记忆。任何 IO/格式错误都降级为「没有记忆」，不抛给调用方。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_path()
        self._salt = ""
        self._scenes: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ storage
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            salt = data.get("salt")
            scenes = data.get("scenes")
            if isinstance(salt, str) and salt:
                self._salt = salt
            if isinstance(scenes, dict):
                self._scenes = {str(k): str(v) for k, v in scenes.items()
                                if isinstance(v, str)}
        if not self._salt:
            # 首次使用（或文件损坏）：生成一次并立刻落盘，否则重启后旧索引全失效。
            self._salt = secrets.token_hex(16)
            self._save()

    def _save(self) -> bool:
        payload = {"salt": self._salt, "scenes": self._scenes}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ lookup
    def key_for(self, app_key: str, title: str) -> str:
        raw = f"{self._salt}:{app_key or ''}:{title or ''}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def recall(self, app_key: str, title: str) -> str | None:
        if not title:
            return None
        return self._scenes.get(self.key_for(app_key, title))

    def remember(self, app_key: str, title: str, scene_key: str) -> bool:
        """记住该会话的场景；标题为空或场景名为空时不记。"""
        if not title or not scene_key:
            return False
        key = self.key_for(app_key, title)
        self._scenes.pop(key, None)      # 重新插入到末尾，近似 LRU
        self._scenes[key] = scene_key
        while len(self._scenes) > MAX_ENTRIES:
            self._scenes.pop(next(iter(self._scenes)))
        # 写失败要如实返回：磁盘满/目录只读时，不能让界面以为「已记住」。
        return self._save()

    def forget(self, app_key: str, title: str) -> bool:
        if not title:
            return False
        removed = self._scenes.pop(self.key_for(app_key, title), None) is not None
        if removed:
            self._save()
        return removed

    def __len__(self) -> int:
        return len(self._scenes)
