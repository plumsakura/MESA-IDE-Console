"""core.jobs 单元测试：受管子进程（P9/P14 修复的底座）。

用真实的短命令（bash -c）验证捕获、回调、取消与错误路径，
不依赖任何 UI 与第三方库。
"""

from __future__ import annotations

import time
import unittest

from core.jobs import TERMINAL_STATUSES, Job, JobRunner, JobStatus, run

BASH = "/bin/bash"


def bash(script: str) -> list[str]:
    return [BASH, "-c", script]


class JobLifecycle(unittest.TestCase):
    def test_captures_stdout_and_stderr_separately(self) -> None:
        result = Job(bash("echo out; echo err >&2")).start().wait(timeout=10)

        self.assertTrue(result.ok)
        self.assertIs(result.status, JobStatus.SUCCEEDED)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertGreaterEqual(result.duration, 0.0)
        self.assertEqual(result.argv, tuple(bash("echo out; echo err >&2")))

    def test_nonzero_exit_is_failed(self) -> None:
        result = Job(bash("exit 3")).start().wait(timeout=10)
        self.assertIs(result.status, JobStatus.FAILED)
        self.assertEqual(result.returncode, 3)
        self.assertFalse(result.ok)
        self.assertIn("退出码 3", result.summary())

    def test_on_output_receives_lines_with_stream_names(self) -> None:
        seen: list[tuple[str, str]] = []
        Job(bash("echo a; echo b >&2"), on_output=lambda line, stream: seen.append((line, stream))) \
            .start().wait(timeout=10)

        self.assertIn(("a", "stdout"), seen)
        self.assertIn(("b", "stderr"), seen)

    def test_on_finish_receives_result(self) -> None:
        finished = []
        Job(bash("exit 0"), on_finish=finished.append).start().wait(timeout=10)
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0].ok)

    def test_callback_exception_does_not_break_job(self) -> None:
        def boom(_line: str, _stream: str) -> None:
            raise RuntimeError("回调炸了")

        with self.assertLogs("core.jobs", level="ERROR"):
            result = Job(bash("echo hi"), on_output=boom).start().wait(timeout=10)
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_cancel_running_job(self) -> None:
        job = Job(bash("sleep 30")).start()
        started = time.monotonic()

        self.assertTrue(job.cancel())
        self.assertLess(time.monotonic() - started, 10, "取消必须及时返回")
        self.assertIs(job.status, JobStatus.CANCELLED)
        self.assertFalse(job.result().ok)
        self.assertIn("已取消", job.result().summary())

    def test_cancel_after_finish_returns_false(self) -> None:
        job = Job(bash("exit 0")).start()
        job.wait(timeout=10)
        self.assertFalse(job.cancel())

    def test_missing_executable_fails_without_raising(self) -> None:
        job = Job(["/definitely/not/a/binary"]).start()
        self.assertIs(job.status, JobStatus.FAILED)
        self.assertIn("/definitely/not/a/binary", job.stderr)
        self.assertIsNone(job.returncode)

    def test_argv_is_never_shell_interpreted(self) -> None:
        """整串 ``echo hi`` 作为可执行名 → 应失败，而不是被 shell 拆成命令+参数。"""
        job = Job(["echo hi"]).start()
        self.assertIs(job.status, JobStatus.FAILED)
        self.assertTrue(job.stderr)

    def test_empty_argv_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Job([])

    def test_start_is_idempotent(self) -> None:
        job = Job(bash("echo once")).start()
        job.start()
        job.wait(timeout=10)
        self.assertEqual(job.stdout.strip(), "once")

    def test_poll_transitions_from_running_to_terminal(self) -> None:
        job = Job(bash("sleep 0.4")).start()
        self.assertIs(job.poll(), JobStatus.RUNNING)
        job.wait(timeout=10)
        self.assertIs(job.poll(), JobStatus.SUCCEEDED)
        self.assertIn(job.status, TERMINAL_STATUSES)

    def test_detached_uncaptured_job(self) -> None:
        job = Job(bash("exit 0"), capture=False, detached=True).start()
        self.assertTrue(job.wait(timeout=10).ok)
        self.assertEqual(job.output_lines("stdout"), [])

    def test_custom_name_defaults_to_executable(self) -> None:
        self.assertEqual(Job(bash("true")).name, "bash")
        self.assertEqual(Job(bash("true"), name="ffmpeg").name, "ffmpeg")


class RunHelper(unittest.TestCase):
    def test_run_returns_completed_result(self) -> None:
        result = run(bash("echo hi"), timeout=10)
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_run_timeout_cancels(self) -> None:
        result = run(bash("sleep 30"), timeout=0.3)
        self.assertIs(result.status, JobStatus.CANCELLED)

    def test_run_missing_binary(self) -> None:
        result = run(["/definitely/not/a/binary"])
        self.assertIs(result.status, JobStatus.FAILED)


class JobRunnerTests(unittest.TestCase):
    def test_start_and_harvest_finished_jobs(self) -> None:
        runner = JobRunner()
        job = runner.start(bash("echo one"), name="one")
        self.assertIn(job, runner.active)

        job.wait(timeout=10)
        results = runner.poll_all()

        self.assertEqual([r.name for r in results], ["one"])
        self.assertEqual(runner.jobs, ())
        self.assertEqual(runner.active, ())

    def test_poll_all_keeps_running_jobs(self) -> None:
        runner = JobRunner()
        runner.start(bash("sleep 0.5"), name="slow")
        self.assertEqual(runner.poll_all(), [])
        self.assertEqual(len(runner.active), 1)
        runner.cancel_all()

    def test_cancel_all(self) -> None:
        runner = JobRunner()
        runner.start(bash("sleep 30"))
        runner.start(bash("sleep 30"))
        self.assertEqual(runner.cancel_all(), 2)
        self.assertEqual(runner.active, ())

    def test_runner_level_callbacks_are_forwarded(self) -> None:
        lines: list[str] = []
        finished: list[str] = []
        runner = JobRunner(
            on_output=lambda line, stream: lines.append(f"{stream}:{line}"),
            on_finish=lambda result: finished.append(result.name),
        )
        runner.start(bash("echo hi"), name="echo")
        runner.wait_all(timeout=10)

        self.assertIn("stdout:hi", lines)
        self.assertEqual(finished, ["echo"])


if __name__ == "__main__":
    unittest.main()
