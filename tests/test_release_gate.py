"""发布门禁等待 main CI 单元测试（不访问外网，纯注入时钟与假数据）。"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "actions", "release-gate"))
import wait_ci  # noqa: E402


def run_item(name, status="completed", conclusion="success", run_id=1):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion}


class WaitCiTest(unittest.TestCase):
    def simulate(self, snapshots, required=(), **kwargs):
        now = [0.0]
        sleeps = []
        seq = iter(snapshots)
        last = [[]]

        def fetch_runs():
            last[0] = next(seq, last[0])
            return last[0]

        def sleep(dt):
            sleeps.append(dt)
            now[0] += dt

        buf = io.StringIO()
        code = wait_ci.wait_for_ci(
            "76b37c300000",
            fetch_runs,
            lambda: list(required),
            clock=lambda: now[0],
            sleep=sleep,
            out=buf,
            **kwargs,
        )
        return code, sleeps, buf.getvalue()

    def test_waits_while_in_progress_then_passes(self):
        snaps = [
            [run_item("check / 密钥扫描"), run_item("check / 测试", status="in_progress", conclusion=None)],
            [run_item("check / 密钥扫描"), run_item("check / 测试", status="in_progress", conclusion=None)],
            [run_item("check / 密钥扫描"), run_item("check / 测试", status="completed", conclusion="success")],
        ]
        code, sleeps, out = self.simulate(snaps, wait_seconds=300, poll_seconds=10)
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [10, 10])
        self.assertIn("CI 进行中", out)
        self.assertIn("全部通过", out)

    def test_fails_fast_when_any_required_check_already_failed(self):
        snaps = [
            [
                run_item("check / 测试", status="completed", conclusion="failure"),
                run_item("check / 镜像构建", status="in_progress", conclusion=None),
            ],
        ]
        code, sleeps, out = self.simulate(snaps, wait_seconds=300, poll_seconds=10)
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [])
        self.assertIn("main 的 CI 没通过", out)

    def test_waits_within_appear_grace_period_after_merge(self):
        snaps = [
            [],
            [run_item("check / 测试", status="queued", conclusion=None)],
            [run_item("check / 测试", status="completed", conclusion="success")],
        ]
        code, sleeps, out = self.simulate(snaps, required=["check / 测试"], wait_seconds=300, poll_seconds=10, appear_seconds=60)
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [10, 10])
        self.assertIn("等待 CI 启动", out)

    def test_missing_checks_fail_after_appear_grace_period(self):
        code, sleeps, out = self.simulate([[]], required=["check / 测试"], wait_seconds=300, poll_seconds=20, appear_seconds=60)
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [20, 20, 20])
        self.assertIn("缺少必过检查：check / 测试", out)

    def test_timeout_when_ci_never_completes(self):
        snaps = [[run_item("check / 测试", status="in_progress", conclusion=None)]]
        code, sleeps, out = self.simulate(snaps, wait_seconds=30, poll_seconds=10)
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [10, 10, 10])
        self.assertIn("等待 main 的 CI 超时", out)

    def test_rerun_uses_latest_check_run_by_id(self):
        snaps = [[
            run_item("check / 测试", status="completed", conclusion="failure", run_id=10),
            run_item("check / 测试", status="completed", conclusion="success", run_id=25),
        ]]
        code, sleeps, _ = self.simulate(snaps)
        self.assertEqual((code, sleeps), (0, []))

    def test_optional_check_failure_does_not_block_release(self):
        snaps = [[
            run_item("check / 测试", status="completed", conclusion="success"),
            run_item("check / 额外检查", status="completed", conclusion="failure"),
        ]]
        code, sleeps, out = self.simulate(snaps, required=["check / 测试"])
        self.assertEqual((code, sleeps), (0, []))
        self.assertIn("非必过检查未通过：check / 额外检查", out)


if __name__ == "__main__":
    unittest.main()
