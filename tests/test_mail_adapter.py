"""Apple Mail 适配器（#152 最小读/填实现）的离线回归：AX 树用假节点驱动。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import modes                          # noqa: E402
from apps import mail_app, registry   # noqa: E402


def node(role, text="", kids=(), **attrs):
    base = {"AXRole": role,
            "AXValue": text if text else None,
            "AXChildren": list(kids)}
    base.update(attrs)
    return SimpleNamespace(attrs=base)


def fake_attr(element, name):
    return element.attrs.get(name) if element is not None else None


class MailTreeTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(mail_app._AX, 'attr', side_effect=fake_attr)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_collect_text_keeps_document_order(self):
        root = node("AXGroup", kids=[node("AXStaticText", "第一段"),
                                     node("AXHeading", "标题"),
                                     node("AXStaticText", "第二段")])
        self.assertEqual(mail_app._collect_text(root), ["第一段", "标题", "第二段"])

    def test_body_uses_webarea_with_most_text(self):
        reading = node("AXWebArea", kids=[node("AXStaticText", "邮件正文" * 10)])
        list_area = node("AXWebArea", kids=[node("AXStaticText", "列表摘要")])
        win = node("AXWindow", kids=[list_area, reading])
        lines = mail_app._body_lines(win)
        self.assertEqual(lines, ["邮件正文" * 10])

    def test_body_falls_back_to_non_table_text(self):
        table = node("AXTable", kids=[node("AXStaticText", "列表行")])
        body = node("AXStaticText", "没有 WebArea 的纯文本邮件")
        win = node("AXWindow", kids=[table, body])
        self.assertEqual(mail_app._body_lines(win), ["没有 WebArea 的纯文本邮件"])

    def test_find_window_skips_small_floating_windows(self):
        small = node("AXWindow", kids=[])
        big = node("AXWindow", kids=[])
        self.patch_rect = patch.object(
            mail_app._AX, 'rect',
            side_effect=lambda el: (10, 20, 500, 400) if el is big else (0, 0, 100, 100))
        self.patch_rect.start(); self.addCleanup(self.patch_rect.stop)
        with patch.object(mail_app, '_running', return_value=SimpleNamespace(
                processIdentifier=lambda: 1)), \
             patch.object(mail_app, '_windows', return_value=[small, big]), \
             patch.object(mail_app, '_window_id', return_value=42):
            win = mail_app.find_window()
        self.assertEqual((win.wid, win.w, win.h), (42, 500, 400))


class MailReadTests(unittest.TestCase):
    def test_read_returns_one_them_message(self):
        web = node("AXWebArea", kids=[node("AXStaticText", "您好，附件里的合同请查收。")])
        win = node("AXWindow", kids=[web],
                   AXTitle="Re: 合同", AXPosition=None, AXSize=None)
        with patch.object(mail_app, '_AX') as fake:
            fake.rect.return_value = (10.0, 20.0, 900.0, 600.0)
            fake.text_of.return_value = "Re: 合同"
            with patch.object(mail_app, '_running', return_value=SimpleNamespace(
                    processIdentifier=lambda: 7)), \
                 patch.object(mail_app, '_windows', return_value=[win]), \
                 patch.object(mail_app, '_window_id', return_value=99), \
                 patch.object(mail_app, '_body_lines', return_value=["您好，附件里的合同请查收。"]), \
                 patch.object(mail_app.fill, 'has_accessibility', return_value=True):
                res = mail_app.read_conversation()
        self.assertTrue(res["ok"])
        self.assertEqual(res["window"]["wid"], 99)
        self.assertEqual(len(res["messages"]), 1)
        self.assertEqual(res["messages"][0].side, "them")
        self.assertIn("合同", res["messages"][0].text)


class MailRegistryTests(unittest.TestCase):
    def tearDown(self):
        modes.set_active(modes.DEFAULT_KEY)

    def test_mail_is_matched_only_in_work_scene(self):
        with patch.object(registry, 'APPS', (mail_app.MailApp(),)):
            self.assertIsNone(registry.match('com.apple.mail', 'Mail'))
            modes.set_active('work')
            self.assertIsInstance(registry.match('com.apple.mail', 'Mail'),
                                  mail_app.MailApp)


if __name__ == '__main__':
    unittest.main()
