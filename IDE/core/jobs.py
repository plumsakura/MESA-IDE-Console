"""后台任务封装（core 层，仅标准库）。

修复 P9/P14：给"会跑几秒到几十分钟"的外部命令提供受管任务对象，
而不是同步 ``subprocess.run`` 阻塞 UI 线程：

- 持有 ``Popen`` 句柄：``poll()`` / ``wait()`` / ``cancel()``；
- ``stdout``/``stderr`` 由读取线程逐行收集，可经 ``on_output`` 实时回调；
- 结束时可经 ``on_finish`` 回调收到 :class:`JobResult`；
- **禁止 shell**：一律 argv 列表（never ``shell=True``）；
- ``capture=False``（丢弃输出）+ ``detached=True``（新会话）用于 clean 这类
  故意脱离终端的场景。

本层不依赖任何 UI：回调在读取线程中触发，UI 侧若需回到主线程，
请用 ``root.after`` 轮询或自行转发（见 ``ide_ui/app.py``）。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
)

#: ``on_output(line, stream_name)``，stream_name ∈ {"stdout", "stderr"}
OutputCallback = Callable[[str, str], None]
#: ``on_finish(JobResult)``
FinishCallback = Callable[["JobResult"], None]


@dataclass(frozen=True)
class JobResult:
    """一个任务的最终结果（不可变，可安全跨线程传递）。"""

    name: str
    status: JobStatus
    returncode: int | None
    stdout: str
    stderr: str
    duration: float
    argv: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is JobStatus.SUCCEEDED

    def summary(self) -> str:
        if self.ok:
            return f"{self.name}: 成功（{self.duration:.2f}s）"
        if self.status is JobStatus.CANCELLED:
            return f"{self.name}: 已取消"
        detail = (self.stderr or self.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {self.returncode}"
        return f"{self.name}: 失败（{tail}）"


class Job:
    """一个受管子进程（argv 列表，绝不经过 shell）。"""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        name: str | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        capture: bool = True,
        detached: bool = False,
        on_output: OutputCallback | None = None,
        on_finish: FinishCallback | None = None,
        popen: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self.argv: tuple[str, ...] = tuple(str(part) for part in argv)
        if not self.argv:
            raise ValueError("argv 不能为空")
        self.name = name or Path(self.argv[0]).name
        self.cwd = cwd
        self.env = dict(env) if env is not None else None
        self.capture = capture
        self.detached = detached
        self._on_output = on_output
        self._on_finish = on_finish
        self._popen = popen

        self._proc: object | None = None
        self._status = JobStatus.PENDING
        self._returncode: int | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._stdout_lines: list[str] = []
        self._stderr_lines: list[str] = []
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    # ---------------- 生命周期 ----------------

    def start(self) -> "Job":
        """启动子进程。**不会抛异常**：启动失败会置为 FAILED 并记录原因。"""
        with self._lock:
            if self._status is not JobStatus.PENDING:
                return self

        kwargs: dict[str, object] = {
            "cwd": self.cwd,
            "stdout": subprocess.PIPE if self.capture else subprocess.DEVNULL,
            "stderr": subprocess.PIPE if self.capture else subprocess.DEVNULL,
        }
        if self.env is not None:
            kwargs["env"] = self.env
        if self.capture:
            kwargs.update(text=True, bufsize=1)
        if self.detached:
            kwargs["start_new_session"] = True

        try:
            self._proc = self._popen(list(self.argv), **kwargs)
        except OSError as exc:
            logger.error("任务启动失败 %s: %s", self.argv, exc)
            with self._lock:
                self._status = JobStatus.FAILED
                self._stderr_lines.append(str(exc))
                self._started_at = self._finished_at = time.monotonic()
            return self

        with self._lock:
            self._status = JobStatus.RUNNING
            self._started_at = time.monotonic()

        if self.capture:
            for stream, sink, stream_name in (
                (getattr(self._proc, "stdout", None), self._stdout_lines, "stdout"),
                (getattr(self._proc, "stderr", None), self._stderr_lines, "stderr"),
            ):
                if stream is None:
                    continue
                thread = threading.Thread(
                    target=self._read_stream,
                    args=(stream, sink, stream_name),
                    daemon=True,
                    name=f"job-{self.name}-{stream_name}",
                )
                thread.start()
                self._threads.append(thread)
        return self

    def _read_stream(self, stream, sink: list[str], stream_name: str) -> None:
        try:
            for raw in stream:
                line = raw.rstrip("\n") if isinstance(raw, str) else str(raw)
                sink.append(line)
                if self._on_output is not None:
                    try:
                        self._on_output(line, stream_name)
                    except Exception:  # noqa: BLE001 - 回调异常不得影响读取
                        logger.exception("on_output 回调异常")
        except Exception:  # noqa: BLE001 - 管道被关闭等
            logger.debug("读取 %s 流中断", stream_name)

    def poll(self) -> JobStatus:
        """非阻塞检查状态；已完成则做收尾（join 读取线程、触发回调）。"""
        with self._lock:
            if self._status in TERMINAL_STATUSES:
                return self._status
            proc = self._proc
            if proc is None:
                return self._status
        code = proc.poll()  # type: ignore[union-attr]
        if code is None:
            return JobStatus.RUNNING
        self._finalize(int(code), cancelled=False)
        return self._status

    def wait(self, timeout: float | None = None) -> JobResult:
        """等待结束（可选超时；超时会取消任务）。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = self.poll()
            if status in TERMINAL_STATUSES:
                return self.result()
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("任务等待超时，取消: %s", self.argv)
                self.cancel()
                return self.result()
            time.sleep(0.02)

    def cancel(self, timeout: float = 5.0) -> bool:
        """请求终止（terminate → 必要时 kill）。返回是否真的取消了。"""
        with self._lock:
            if self._status in TERMINAL_STATUSES:
                return False
            proc = self._proc
        if proc is None:
            return False

        try:
            proc.terminate()  # type: ignore[union-attr]
            try:
                code = proc.wait(timeout=timeout)  # type: ignore[union-attr]
            except subprocess.TimeoutExpired:
                logger.warning("任务未响应 terminate，改用 kill: %s", self.argv)
                proc.kill()  # type: ignore[union-attr]
                code = proc.wait()  # type: ignore[union-attr]
        except OSError as exc:  # pragma: no cover - 进程已消失
            logger.warning("取消任务时出错 %s: %s", self.argv, exc)
            code = None

        self._finalize(None if code is None else int(code), cancelled=True)
        return True

    def _finalize(self, returncode: int | None, *, cancelled: bool) -> None:
        for thread in self._threads:
            thread.join(timeout=1.0)

        if cancelled:
            status = JobStatus.CANCELLED
        elif returncode == 0:
            status = JobStatus.SUCCEEDED
        else:
            status = JobStatus.FAILED

        with self._lock:
            if self._status in TERMINAL_STATUSES:
                return
            self._status = status
            self._returncode = returncode
            self._finished_at = time.monotonic()
            result = self.result()

        logger.debug("任务结束: %s", result.summary())
        if self._on_finish is not None:
            try:
                self._on_finish(result)
            except Exception:  # noqa: BLE001 - 回调异常不得影响任务收尾
                logger.exception("on_finish 回调异常")

    # ---------------- 查询 ----------------

    @property
    def status(self) -> JobStatus:
        return self._status

    @property
    def returncode(self) -> int | None:
        return self._returncode

    @property
    def stdout(self) -> str:
        return "\n".join(self._stdout_lines)

    @property
    def stderr(self) -> str:
        return "\n".join(self._stderr_lines)

    def output_lines(self, stream: str = "stdout") -> list[str]:
        return list(self._stdout_lines if stream == "stdout" else self._stderr_lines)

    @property
    def duration(self) -> float:
        if self._started_at is None:
            return 0.0
        end = self._finished_at if self._finished_at is not None else time.monotonic()
        return end - self._started_at

    def result(self) -> JobResult:
        return JobResult(
            name=self.name,
            status=self._status,
            returncode=self._returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            duration=self.duration,
            argv=self.argv,
        )


def run(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    name: str | None = None,
    popen: Callable[..., object] = subprocess.Popen,
) -> JobResult:
    """同步便捷封装（替代 ``subprocess.run(capture_output=True)``）。

    超时会取消任务，返回状态为 ``CANCELLED``。
    """
    job = Job(argv, name=name, cwd=cwd, env=env, popen=popen).start()
    return job.wait(timeout=timeout)


class JobRunner:
    """管理多个后台任务（供 UI 定时 ``poll_all()`` 收割结果）。"""

    def __init__(
        self,
        *,
        popen: Callable[..., object] = subprocess.Popen,
        on_output: OutputCallback | None = None,
        on_finish: FinishCallback | None = None,
    ) -> None:
        self._popen = popen
        self._on_output = on_output
        self._on_finish = on_finish
        self._jobs: list[Job] = []

    def start(self, argv: Sequence[str], **kwargs) -> Job:
        kwargs.setdefault("popen", self._popen)
        kwargs.setdefault("on_output", self._on_output)
        kwargs.setdefault("on_finish", self._on_finish)
        job = Job(argv, **kwargs).start()
        self._jobs.append(job)
        return job

    @property
    def active(self) -> tuple[Job, ...]:
        return tuple(job for job in self._jobs if job.status not in TERMINAL_STATUSES)

    @property
    def jobs(self) -> tuple[Job, ...]:
        return tuple(self._jobs)

    def poll_all(self) -> list[JobResult]:
        """收割已完成任务（从活跃列表移除），返回它们的结果。"""
        finished: list[JobResult] = []
        remaining: list[Job] = []
        for job in self._jobs:
            if job.poll() in TERMINAL_STATUSES:
                finished.append(job.result())
            else:
                remaining.append(job)
        self._jobs = remaining
        return finished

    def cancel_all(self, timeout: float = 5.0) -> int:
        cancelled = sum(1 for job in list(self._jobs) if job.cancel(timeout=timeout))
        return cancelled

    def wait_all(self, timeout: float | None = None) -> list[JobResult]:
        return [job.wait(timeout=timeout) for job in list(self._jobs)]
