"""零网络守卫 — AR_OFFLINE=1 下 monkeypatch socket 使一切外呼即刻爆炸,
然后 import 全部被测模块并跑完整离线套件入口,证明离线套件确实 0 网络调用。
(没有这层守卫,"离线测试"只是口头声明;有了它,任何隐藏外呼都会当场崩溃。)
运行: python3 tests/test_no_network_guard.py
不是买卖指令;研究信号,human executes.
"""
import os
import socket
import sys
import unittest
from datetime import datetime, timezone

os.environ["AR_OFFLINE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "experiments", "execution_tracker"))


class NetworkAttempt(RuntimeError):
    """AR_OFFLINE=1 下出现网络调用 = 零网络铁则违规。"""


def _blocked(*a, **k):
    raise NetworkAttempt("network call attempted under AR_OFFLINE=1")


class _BlockedSocket(socket.socket):
    """保持类身份(ssl 等模块 import 时要继承它),但实例化即爆炸。"""

    def __init__(self, *a, **k):
        raise NetworkAttempt("socket() attempted under AR_OFFLINE=1")


socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

# 守卫自证:canary 外呼必须真的炸(否则守卫是永真式,证明力为零)
try:
    socket.create_connection(("example.com", 80))
    raise SystemExit("FATAL: 零网络守卫未生效 — canary 外呼未被拦截")
except NetworkAttempt:
    print("guard armed: canary 网络调用被正确拦截")

# ── import 全部被测模块(module 级不许发网络)──
import run_nightly            # noqa: E402
import setup_promoter          # noqa: E402
import red_flag_gate           # noqa: E402,F401
import full_battery            # noqa: E402,F401
import attribution_audit       # noqa: E402,F401
import export_contracts        # noqa: E402,F401
import run_post_close_report   # noqa: E402,F401
from experiments.macro_os import contracts as macro_contracts  # noqa: E402
from experiments.macro_os import collectors as macro_collectors  # noqa: E402
from experiments.macro_os import m0b2 as macro_m0b2  # noqa: E402,F401
from experiments.macro_os import storage as macro_storage  # noqa: E402,F401
from experiments.macro_os import m0b3 as macro_m0b3  # noqa: E402,F401
from experiments.macro_os import m1a as macro_m1a  # noqa: E402,F401
from experiments.macro_os import expectation_registry as macro_expectations  # noqa: E402,F401

# ── 在守卫下跑完整离线套件入口(任何隐藏外呼 → NetworkAttempt 崩溃)──
import test_engines_offline as teo        # noqa: E402
for name in sorted(n for n in dir(teo) if n.startswith("test_")):
    getattr(teo, name)()

import test_promoter_qc_offline as tpq    # noqa: E402
for name in sorted(n for n in dir(tpq) if n.startswith("test_")):
    getattr(tpq, name)()

assert run_nightly.selftest(), "run_nightly selftest FAIL"
pf = run_nightly.preflight()
run_nightly._print_preflight(pf)
assert pf["pass"], f"preflight FAIL: {pf['failures']}"
assert setup_promoter.selftest(), "setup_promoter selftest FAIL"
macro_contracts.selftest()
import test_macro_m0b_offline as macro_m0b_tests  # noqa: E402
macro_suite = unittest.defaultTestLoader.loadTestsFromTestCase(
    macro_m0b_tests.MacroM0BTests
)
macro_result = unittest.TextTestRunner(verbosity=0).run(macro_suite)
assert macro_result.wasSuccessful(), "Macro M0-B suite failed under socket guard"
import test_macro_m0b2_offline as macro_m0b2_tests  # noqa: E402
macro_m0b2_suite = unittest.defaultTestLoader.loadTestsFromTestCase(
    macro_m0b2_tests.MacroM0B2Tests
)
macro_m0b2_result = unittest.TextTestRunner(verbosity=0).run(macro_m0b2_suite)
assert macro_m0b2_result.wasSuccessful(), "Macro M0-B2 suite failed under socket guard"
import test_macro_m0b3_offline as macro_m0b3_tests  # noqa: E402
macro_m0b3_result = unittest.TextTestRunner(verbosity=0).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(macro_m0b3_tests.MacroM0B3Tests)
)
assert macro_m0b3_result.wasSuccessful(), "Macro M0-B3 suite failed under socket guard"
import test_macro_m1a_offline as macro_m1a_tests  # noqa: E402
macro_m1a_result = unittest.TextTestRunner(verbosity=0).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(macro_m1a_tests.MacroM1ATests)
)
assert macro_m1a_result.wasSuccessful(), "Macro M1-A suite failed under socket guard"
import test_macro_m1b_offline as macro_m1b_tests  # noqa: E402
macro_m1b_result = unittest.TextTestRunner(verbosity=0).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(macro_m1b_tests.MacroM1BTests)
)
assert macro_m1b_result.wasSuccessful(), "Macro M1-B suite failed under socket guard"
try:
    macro_collectors.UrllibTransport().fetch(
        macro_collectors._cboe_builder(
            datetime.now(timezone.utc), {}
        )
    )
    raise AssertionError("Macro M0-B transport ignored AR_OFFLINE")
except macro_collectors.CollectionError as exc:
    assert exc.code == "AR_OFFLINE", exc

print("NO-NETWORK GUARD PASS: 全模块导入 + 离线套件 + selftest + preflight,0 网络调用")
