"""#147：设置保存后生成层运行时生效（凭据重载 + HUD 重载钩子）。

不读屏、不调 API：凭据用 userconfig 会话覆盖与 mock 验证。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

import generate            # noqa: E402
import userconfig          # noqa: E402


class CredentialReloadTests(unittest.TestCase):
    def test_session_override_is_visible_to_load_credentials(self):
        with patch.object(userconfig, "_session_overrides", {}):
            userconfig.session_override("OPENAI_API_KEY", "sk-test")
            userconfig.session_override("OPENAI_BASE_URL", "https://new.example/v1")
            userconfig.session_override("OPENAI_MODEL", "new-model")
            base, key, model, _src, api = generate.load_credentials()
        self.assertEqual((base, key, model, api),
                         ("https://new.example/v1", "sk-test", "new-model", "openai"))

    def test_field_override_applies_without_changing_the_key(self):
        # 用户只改了地址/模型、密钥不动时，改动也必须立刻生效（#147）
        with patch.object(userconfig, "_session_overrides", {}):
            userconfig.session_override("OPENAI_BASE_URL", "https://only-base.example")
            userconfig.session_override("OPENAI_MODEL", "only-model")
            base, key, model, _src, _api = generate.load_credentials()
        self.assertEqual(base, "https://only-base.example")
        self.assertEqual(model, "only-model")
        self.assertTrue(key)          # 密钥仍从原来源解析

    def test_generator_reload_redrops_cached_credentials(self):
        calls = []

        def fake_load():
            calls.append(1)
            return (f"https://host{len(calls)}.example", "sk", f"model{len(calls)}",
                    "test", "openai")

        with patch.object(generate, "load_credentials", side_effect=fake_load):
            gen = generate.Generator()
            self.assertEqual(gen._creds_or_load()[2], "model1")
            self.assertEqual(gen._creds_or_load()[2], "model1")     # cached
            gen.reload()
            self.assertEqual(gen._creds_or_load()[2], "model2")     # re-read after reload


class HudReloadHookTests(unittest.TestCase):
    def setUp(self):
        import test_hud_reply
        self.fixture = test_hud_reply.HudReplyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h

    def test_reload_hook_resets_generator(self):
        self.h.reload_generation_config()
        self.h.generator.reload.assert_called_once()


if __name__ == '__main__':
    unittest.main()
