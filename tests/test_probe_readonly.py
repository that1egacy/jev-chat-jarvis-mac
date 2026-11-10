"""探测工具必须保持纯只读：不得对目标应用写 AX 属性、不得执行动作。

项目硬约束是「唯一写动作是用户点击填入」；探测工具只做读取/统计。这条测试守的是
防止将来有人为了探测 Electron 应用再把 AXManualAccessibility 写回去。
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_WRITE_APIS = (
    'AXUIElementSetAttributeValue',
    'AXUIElementPerformAction',
    'AXUIElementSetAttributeValue',
)


class ProbeReadOnlyTests(unittest.TestCase):
    def test_channel_probe_never_writes_to_the_target_app(self):
        source = (ROOT / 'probe' / 'channel_probe.py').read_text(encoding='utf-8')
        for api in FORBIDDEN_WRITE_APIS:
            self.assertNotIn(api, source, f'{api} 是写操作，探测工具必须只读')

    def test_channel_probe_does_not_enable_manual_accessibility(self):
        source = (ROOT / 'probe' / 'channel_probe.py').read_text(encoding='utf-8')
        code = '\n'.join(line for line in source.splitlines()
                         if not line.strip().startswith('#'))
        self.assertNotIn('AXManualAccessibility', code,
                         '不得在探测时给目标应用打开辅助功能树')


if __name__ == '__main__':
    unittest.main()
