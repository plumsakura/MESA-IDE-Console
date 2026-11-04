"""core.jobs 边界与竞态用例（在 test_core_jobs.py 之外补充）。

重点覆盖"时间相关/并发"的路径，这些是最容易回归的部分：

- ``wait(timeout)`` 超时后必须取消并返回 CANCELLED，而不是永久阻塞；
- 取消/结束只发生一次：重复 cancel、结束后再 poll 都不得重复触发回调；
- ``_finalize`` 的幂等性（取消与自然结束竞争时状态不得被覆盖）；
- 读取线程与结束回调的交接：大批输出不丢失、回调抛异常不影响收尾；
- ``JobRunner`` 的收割与批量等待在超时下不会挂住。
"""

from __future__ import annotations

import subprocess
import threading
import time
import unittest
from unittest import mock

from core.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobResult,
    JobRunner,
    JobStatus,
    run,
)

BASH = "/bin/bash"


def bash(script: str) -> list[str]:
    return [BASH, "-c", script]


class _FakeProcess:
    """模拟 ``Popen``：可控的 ``poll/terminate/wait/kill`` 与输出流。"""

    def __init__(self, stdout_lines=(), stderr_lines=(), returncode=None,
                 terminate_stops=True):
        self.stdout = iter(f"{line}\n" for line in stdout_lines)
        self.stderr = iter(f"{line}\n" for line in stderr_lines)
        self._returncode = returncode
        self.terminate_stops = terminate_stops
        self.terminate_calls = 0
        self.kill_calls = 0
        self.waited_with: list[float | None] = []
        self._terminated = threading.Event()

    def poll(self):
        if self.terminate_stops and self._terminated.is_set():
            return -15
        return self._returncode

    def terminate(self):
        self.terminate_calls += 1
        self._terminated.set()
        if self.terminate_stops:
            self._returncode = -15

    def kill(self):
        self.kill_calls += 1
        self._terminated.set()
        self._returncode = -9

    def wait(self, timeout=None):
        self.waited_with.append(timeout)
        if self.terminate_stops or self._returncode is not None:
            return self._returncode
        if timeout is not None:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return 0

    def send_signal(self, _sig):  # pragma: no cover - 仅兼容接口
        pass


class WaitTimeoutAndCancellation(unittest.TestCase):
    def test_wait_timeout_cancels_and_reports_cancelled(self) -> None:
        job = Job(bash("sleep 30")).start()
        started = time.monotonic()

        result = job.wait(timeout=0.2)

        self.assertLess(time.monotonic() - started, 5.0, "超时必须及时返回")
        self.assertIs(result.status, JobStatus.CANCELLED)
        self.assertIs(job.status, JobStatus.CANCELLED)

    def test_wait_timeout_is_idempotent_on_repeat_calls(self) -> None:
        job = Job(bash("sleep 30")).start()
        first = job.wait(timeout=0.2)
        second = job.wait(timeout=0.2)

        self.assertIs(first.status, JobStatus.CANCELLED)
        self.assertIs(second.status, JobStatus.CANCELLED)
        self.assertFalse(job.cancel(), "已取消的任务再取消应返回 False")

    def test_repeated_cancel_only_finalizes_once(self) -> None:
        finished: list[JobResult] = []
        job = Job(bash("sleep 30"), on_finish=finished.append).start()

        self.assertTrue(job.cancel())
        self.assertFalse(job.cancel())
        self.assertFalse(job.cancel())

        self.assertEqual(len(finished), 1, "on_finish 只能触发一次")
        self.assertEqual(job.stdout, "")

    def test_cancel_without_start_returns_false(self) -> None:
        job = Job(bash("true"))
        self.assertFalse(job.cancel(), "PENDING 且未启动的任务无法取消")
        self.assertIs(job.status, JobStatus.PENDING)

    def test_poll_after_terminal_does_not_rerun_callbacks(self) -> None:
        finished: list[JobResult] = []
        job = Job(bash("true"), on_finish=finished.append).start()
        job.wait(timeout=10)

        for _ in range(5):
            self.assertIs(job.poll(), JobStatus.SUCCEEDED)

        self.assertEqual(len(finished), 1)

    def test_cancel_after_natural_finish_keeps_success_status(self) -> None:
        job = Job(bash("echo done")).start()
        result = job.wait(timeout=10)
        self.assertTrue(result.ok)

        self.assertFalse(job.cancel())
        self.assertIs(job.status, JobStatus.SUCCEEDED, "结束状态不得被取消覆盖")
        self.assertEqual(job.returncode, 0)


class FinalizeIdempotencyWithStubProcess(unittest.TestCase):
    """用替身进程精确控制 poll/terminate/wait，验证收尾只发生一次。"""

    def test_finalize_is_idempotent_between_cancel_and_natural_exit(self) -> None:
        process = _FakeProcess(stdout_lines=["partial"], returncode=None)
        finished: list[JobResult] = []
        job = Job(bash("x"), on_finish=finished.append, popen=lambda *a, **k: process)
        job.start()

        job.poll()  # 仍在运行
        job.cancel()  # 第一次收尾：CANCELLED
        job._finalize(0, cancelled=False)  # 模拟自然结束竞争

        self.assertIs(job.status, JobStatus.CANCELLED)
        self.assertEqual(len(finished), 1)
        self.assertEqual(job.stdout, "partial")

    def test_terminate_timeout_falls_back_to_kill(self) -> None:
        process = _FakeProcess(terminate_stops=False, returncode=None)

        def wait(timeout=None):
            process.waited_with.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            process._returncode = -9
            return -9

        process.wait = wait  # type: ignore[method-assign]
        job = Job(bash("x"), popen=lambda *a, **k: process).start()

        self.assertTrue(job.cancel(timeout=0.1))

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1, "terminate 超时后必须 kill")
        self.assertIs(job.status, JobStatus.CANCELLED)

    def test_popen_oserror_marks_failed_without_callbacks_on_finish(self) -> None:
        def boom(*_args, **_kwargs):
            raise OSError("fork 失败")

        job = Job(bash("x"), on_finish=lambda result: None, popen=boom)
        job.start()

        self.assertIs(job.status, JobStatus.FAILED)
        self.assertIn("fork 失败", job.stderr)
        self.assertIsNone(job.returncode)


class OutputAndCallbackEdges(unittest.TestCase):
    def test_many_lines_are_all_captured(self) -> None:
        lines = 500
        job = Job(bash(f"seq 1 {lines}")).start()
        result = job.wait(timeout=30)

        self.assertTrue(result.ok)
        self.assertEqual(len(job.output_lines("stdout")), lines)
        self.assertEqual(job.output_lines("stdout")[0], "1")
        self.assertEqual(job.output_lines("stdout")[-1], str(lines))

    def test_on_finish_exception_does_not_break_finalization(self) -> None:
        def boom(_result: JobResult) -> None:
            raise RuntimeError("收尾回调炸了")

        with self.assertLogs("core.jobs", level="ERROR"):
            result = Job(bash("echo hi"), on_finish=boom).start().wait(timeout=10)

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_interleaved_streams_are_separated(self) -> None:
        job = Job(
            bash("for i in 1 2 3; do echo out$i; echo err$i >&2; done")
        ).start()
        job.wait(timeout=10)

        self.assertEqual(job.output_lines("stdout"), ["out1", "out2", "out3"])
        self.assertEqual(job.output_lines("stderr"), ["err1", "err2", "err3"])
        self.assertEqual(job.result().status, JobStatus.SUCCEEDED)

    def test_stdout_property_joins_lines(self) -> None:
        job = Job(bash("printf 'a\\nb\\n'")).start()
        job.wait(timeout=10)
        self.assertEqual(job.stdout, "a\nb")

    def test_duration_is_monotonic_before_and_after_finish(self) -> None:
        job = Job(bash("sleep 0.2")).start()
        running = job.duration
        job.wait(timeout=10)

        self.assertGreaterEqual(job.duration, running)
        self.assertGreater(job.result().duration, 0.0)

    def test_uncaptured_job_result_has_empty_output(self) -> None:
        job = Job(bash("echo hidden"), capture=False, detached=True).start()
        result = job.wait(timeout=10)

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_env_mapping_is_copied_and_passed_through(self) -> None:
        env = {"MESA_DIR": "/opt/mesa"}
        job = Job(bash("printf '%s' \"$MESA_DIR\""), env=env).start()
        env["MESA_DIR"] = "CHANGED"

        self.assertEqual(job.wait(timeout=10).stdout, "/opt/mesa")

    def test_cwd_is_honoured(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            job = Job(bash("pwd"), cwd=tmp).start()
            import os

            self.assertEqual(
                os.path.realpath(job.wait(timeout=10).stdout.strip()),
                os.path.realpath(tmp),
            )

    def test_detached_job_requested_kwargs(self) -> None:
        seen_kwargs: dict = {}

        def spy(*_args, **kwargs):
            seen_kwargs.update(kwargs)
            return _FakeProcess(returncode=0)

        job = Job(bash("x"), capture=False, detached=True, popen=spy).start()
        job.wait(timeout=10)

        self.assertTrue(seen_kwargs["start_new_session"])
        self.assertIs(seen_kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(seen_kwargs["stderr"], subprocess.DEVNULL)

    def test_capture_job_requested_kwargs(self) -> None:
        seen_kwargs: dict = {}

        def spy(*_args, **kwargs):
            seen_kwargs.update(kwargs)
            return _FakeProcess(returncode=0)

        Job(bash("x"), popen=spy).start().wait(timeout=10)

        self.assertIs(seen_kwargs["stdout"], subprocess.PIPE)
        self.assertTrue(seen_kwargs["text"])
        self.assertEqual(seen_kwargs["bufsize"], 1)


class JobRunnerEdges(unittest.TestCase):
    def test_wait_all_with_timeout_cancels_all_running_jobs(self) -> None:
        runner = JobRunner()
        runner.start(bash("sleep 30"), name="a")
        runner.start(bash("sleep 30"), name="b")
        started = time.monotonic()

        results = runner.wait_all(timeout=0.2)

        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual({r.status for r in results}, {JobStatus.CANCELLED})
        self.assertEqual(runner.active, ())

    def test_poll_all_harvests_multiple_and_keeps_order(self) -> None:
        runner = JobRunner()
        first = runner.start(bash("echo one"), name="one")
        second = runner.start(bash("echo two"), name="two")
        first.wait(timeout=10)
        second.wait(timeout=10)

        self.assertEqual([r.name for r in runner.poll_all()], ["one", "two"])
        self.assertEqual(runner.poll_all(), [])

    def test_poll_all_mixes_finished_and_running(self) -> None:
        runner = JobRunner()
        fast = runner.start(bash("echo fast"), name="fast")
        runner.start(bash("sleep 30"), name="slow")
        fast.wait(timeout=10)

        finished = runner.poll_all()

        self.assertEqual([r.name for r in finished], ["fast"])
        self.assertEqual([job.name for job in runner.active], ["slow"])
        runner.cancel_all()

    def test_cancel_all_is_idempotent(self) -> None:
        runner = JobRunner()
        runner.start(bash("sleep 30"))
        runner.start(bash("sleep 30"))

        self.assertEqual(runner.cancel_all(), 2)
        self.assertEqual(runner.cancel_all(), 0)
        # jobs 保留历史记录（只有 poll_all 才收割），active 必须清空
        self.assertEqual(len(runner.jobs), 2)
        self.assertEqual(runner.active, ())
        self.assertEqual(len(runner.poll_all()), 2)

    def test_runner_custom_popen_is_default_for_start(self) -> None:
        process = _FakeProcess(returncode=0)
        runner = JobRunner(popen=lambda *a, **k: process)

        job = runner.start(bash("x"))

        job.wait(timeout=10)
        self.assertTrue(job.result().ok)

    def test_runner_kwargs_override_runner_defaults(self) -> None:
        runner_lines: list[str] = []
        job_lines: list[str] = []
        runner = JobRunner(on_output=lambda line, _s: runner_lines.append(line))

        runner.start(
            bash("echo hi"),
            on_output=lambda line, _s: job_lines.append(line),
        ).wait(timeout=10)

        self.assertEqual(job_lines, ["hi"])
        self.assertEqual(runner_lines, [], "显式 kwargs 应覆盖 runner 级默认回调")

    def test_run_returns_result_even_when_cancelled(self) -> None:
        result = run(bash("sleep 30"), timeout=0.2)
        self.assertIsInstance(result, JobResult)
        self.assertIs(result.status, JobStatus.CANCELLED)
        self.assertIn("已取消", result.summary())

    def test_terminal_statuses_membership(self) -> None:
        self.assertIn(JobStatus.SUCCEEDED, TERMINAL_STATUSES)
        self.assertIn(JobStatus.FAILED, TERMINAL_STATUSES)
        self.assertIn(JobStatus.CANCELLED, TERMINAL_STATUSES)
        self.assertNotIn(JobStatus.PENDING, TERMINAL_STATUSES)
        self.assertNotIn(JobStatus.RUNNING, TERMINAL_STATUSES)


class ConcurrencyStress(unittest.TestCase):
    def test_threaded_poll_and_cancel_race_never_double_finishes(self) -> None:
        """多线程同时 poll/cancel：状态必须是终态之一且 on_finish 只触发一次。"""
        for _ in range(10):
            finished: list[JobResult] = []
            job = Job(bash("sleep 30"), on_finish=finished.append).start()
            barrier = threading.Barrier(4)

            def worker(action) -> None:
                barrier.wait()
                action()

            threads = [
                threading.Thread(target=worker, args=(job.poll,)),
                threading.Thread(target=worker, args=(job.poll,)),
                threading.Thread(target=worker, args=(job.cancel,)),
                threading.Thread(target=worker, args=(job.cancel,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertIn(job.status, TERMINAL_STATUSES)
            self.assertEqual(len(finished), 1, "并发下 on_finish 不得重复")
            job.cancel()

    def test_many_concurrent_jobs_are_all_tracked(self) -> None:
        runner = JobRunner()
        jobs = [runner.start(bash("echo job"), name=f"j{i}") for i in range(12)]

        results = runner.wait_all(timeout=30)

        self.assertEqual(len(results), 12)
        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(runner.active, ())
        self.assertEqual(len(runner.poll_all()), 12)
        self.assertEqual(runner.jobs, ())
        self.assertEqual([job.name for job in jobs], [f"j{i}" for i in range(12)])


if __name__ == "__main__":
    unittest.main()
