"""pgstar 图片 → 视频（ffmpeg）任务（core 层，仅标准库）。

============================================================================
冻结行为（FROZEN）—— 与原 ``mesa_video_maker.py`` 逐字一致
============================================================================
1. 输入：``<图片目录>/<prefix>_*.png``（``-pattern_type glob``）；
2. 输出：``<图片目录>/<output_name>``（默认 ``evolution_movie.mp4``）；
3. 基础参数：

   ``ffmpeg -y -framerate <fps> -pattern_type glob -i <pattern> -c:v libx264
   -pix_fmt yuv420p <output>``

4. 自动修复：首次失败且 stderr 含 ``not divisible by 2`` 时，插入
   ``-vf pad=ceil(iw/2)*2:ceil(ih/2)*2`` 重试一次。

   **已获实测确认的行为变更（阶段 5，Q1）**：pad 滤镜放在 ``-i`` **之后**
   （输出选项）。基线把它放在 ``-i`` 之前，真实 ffmpeg 会报
   ``Option vf ... cannot be applied to input url ... Move this option before
   the file it belongs to`` 并拒绝执行（实测 ffmpeg 8.0.1 退出码 234），
   于是"奇数尺寸自动重试"永远失败——这是修 bug，不是风格调整。
5. 失败文案与原实现一致（``错误：png 目录不存在: …`` / ``错误：未找到 ffmpeg…`` /
   ``FFmpeg error: …`` / ``成功生成视频: …`` / ``自动修复成功，已生成视频: …``）。

============================================================================
阶段 6 重构（对照 MESA 26.4.1《Using PGSTAR》；行为变更逐条声明）
============================================================================
① **启动前校验帧序列**（:mod:`core.mesa.frames`）：一帧都匹配不到时直接报
   :data:`MESSAGE_NO_FRAMES` 且**不启动** ffmpeg；目录里只有别的扩展名
   （``file_device = 'vcps'`` 写出 ``.ps``）时追加说明。旧行为是让 ffmpeg
   自己失败，用户只看到 ``FFmpeg error: … No such file or directory``。
② **参数校验**：``output_name`` 不得为空/含路径分隔符/``..``（否则会把视频
   写到图片目录之外）；``fps`` 必须是正整数。
③ **失败分类**：已知 ffmpeg 报错追加一行可执行建议
   （:func:`explain_ffmpeg_failure`）；识别不了的报错文案与旧行为逐字一致。
④ **取消竞态修复**：进程已结束但尚未被 ``poll`` 收走时，:meth:`MesaVideoTask.cancel`
   不再把它报成"已取消"，而是收尾并给出真实结果——旧行为会把**已经生成好的
   视频**报成"已取消视频生成"。
⑤ **帧序告警**（不改命令）：字典序与模型号顺序不一致（``file_digits`` 太小）
   时给出 :attr:`MesaVideoTask.warning`，提示可能合成错序视频。

：class:`MesaVideoTask` 仍是非阻塞状态机（P9）：``start()`` 立即返回，
UI 侧定时 ``poll()`` 推进状态即可。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from core.jobs import TERMINAL_STATUSES, Job, JobResult, JobRunner, JobStatus
from core.mesa.frames import DEFAULT_SUFFIX, FrameSet, frame_pattern, scan_frames

logger = logging.getLogger(__name__)

DEFAULT_FPS = 10
DEFAULT_OUTPUT_NAME = "evolution_movie.mp4"
PNG_DIRNAME = "png"
PNG_SUFFIX = DEFAULT_SUFFIX
PAD_FILTER = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
PAD_TRIGGER = "not divisible by 2"

MESSAGE_NO_PNG_DIR = "错误：png 目录不存在: {png_dir}"
MESSAGE_NO_FFMPEG = "错误：未找到 ffmpeg，请确保安装了 ffmpeg。"
MESSAGE_SUCCESS = "成功生成视频: {output_name}"
MESSAGE_FIXED = "自动修复成功，已生成视频: {output_name}"
MESSAGE_ERROR_PREFIX = "FFmpeg error: "
MESSAGE_NO_FRAMES = (
    "错误：在 {png_dir} 未找到匹配 '{pattern}' 的图片帧。\n"
    "pgstar 默认只画窗口、不落盘：请在 inlist_pgstar 里设置 "
    "HR_file_flag = .true.（并按需设置 HR_file_dir / HR_file_prefix），"
    "同时确认 file_device = 'png'。"
)
MESSAGE_OTHER_DEVICE = (
    "另：该目录里有 {count} 个 {suffixes} 文件——file_device = 'vcps' 写出的是 "
    "PostScript，ffmpeg 无法直接合成，请改用 file_device = 'png'。"
)
MESSAGE_BAD_OUTPUT = "错误：输出文件名不合法: {output_name}（不得为空、不得含路径分隔符或 '..'）"
MESSAGE_BAD_FPS = "错误：帧率必须是正整数，收到: {fps}"
MESSAGE_FRAME_ORDER = (
    "注意：图片帧的字典序与模型号顺序不一致（模型号范围 {first}–{last}）："
    "ffmpeg 的 glob 按字典序读取，视频可能错序；"
    "请在 inlist_pgstar 里把 file_digits 调到足够大（默认 5）后重新出图。"
)

#: ffmpeg 常见报错 → 可执行建议（按顺序匹配，命中即止）
FAILURE_HINTS: tuple[tuple[str, str], ...] = (
    (
        "no such file or directory",
        "未读到图片帧：请确认 inlist_pgstar 的 *_file_flag = .true.，"
        "且 HR_file_dir / HR_file_prefix 与本次输入的目录、前缀一致。",
    ),
    ("permission denied", "没有读写权限：请检查图片目录与输出文件的权限。"),
    ("not divisible by 2", "自动补齐像素（pad）后仍失败：请检查这些 png 帧是否损坏。"),
    (
        "unknown encoder 'libx264'",
        "当前 ffmpeg 未编译 libx264：请换用带 H.264 的 ffmpeg（MESA SDK 自带一个）。",
    ),
    (
        "encoder (codec h264) not found",
        "当前 ffmpeg 缺少 H.264 编码器：请换用带 H.264 的 ffmpeg（MESA SDK 自带一个）。",
    ),
)

#: 状态机状态
PENDING = "pending"
RUNNING = "running"
RETRYING = "retrying"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"


def find_ffmpeg(
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
) -> str | None:
    """先找 PATH 上的 ffmpeg，再回退 ``$MESA_DIR/bin/ffmpeg``（与原实现一致）。"""
    found = which("ffmpeg")
    if found:
        return found
    source = os.environ if env is None else env
    mesa_dir = (source.get("MESA_DIR") or "").strip()
    if not mesa_dir:
        return None
    candidate = os.path.join(mesa_dir, "bin", "ffmpeg")
    return candidate if exists(candidate) else None


def explain_ffmpeg_failure(stderr: str) -> str | None:
    """把 ffmpeg 的英文报错映射成可执行的中文建议（识别不了返回 ``None``）。"""
    text = (stderr or "").lower()
    for needle, hint in FAILURE_HINTS:
        if needle in text:
            return hint
    return None


def validate_output_name(output_name: str) -> str | None:
    """输出名必须是纯文件名，否则视频会写到图片目录之外；合法时返回 ``None``。"""
    if not output_name or output_name in {".", ".."} or any(sep in output_name for sep in "/\\"):
        return MESSAGE_BAD_OUTPUT.format(output_name=output_name)
    return None


def validate_fps(fps: int) -> str | None:
    """帧率必须是正整数（ffmpeg 的 ``-framerate`` 不接受 0/负数）；合法返回 ``None``。"""
    try:
        value = int(fps)
    except (TypeError, ValueError):
        return MESSAGE_BAD_FPS.format(fps=fps)
    return None if value > 0 else MESSAGE_BAD_FPS.format(fps=fps)


def resolve_png_dir(project_path: str, override: str | None = None) -> str:
    """图片目录：优先用调用方给的覆盖值，否则按手册的 ``HR_file_dir`` 解析。

    解析失败一律退回手册默认值 ``<项目>/png``（绝不抛异常）。
    """
    if override:
        return override
    try:
        from core.mesa.outputs import resolve_outputs

        return resolve_outputs(project_path).png_dir
    except Exception:  # noqa: BLE001 - 解析失败退回旧行为
        logger.debug("解析项目输出目录失败，退回默认 png/", exc_info=True)
        return os.path.join(project_path, PNG_DIRNAME)


def _other_device_note(png_dir: str, prefix: str) -> str | None:
    """目录里有同前缀、非 PNG 的帧（如 vcps 的 ``.ps``）时给出说明。"""
    others = [
        name for name in scan_frames(png_dir, prefix, None).files if not name.endswith(PNG_SUFFIX)
    ]
    if not others:
        return None
    suffixes = ", ".join(sorted({os.path.splitext(name)[1] or "(无扩展名)" for name in others}))
    return MESSAGE_OTHER_DEVICE.format(count=len(others), suffixes=suffixes)


def build_input_pattern(png_dir: str, prefix: str) -> str:
    return os.path.join(png_dir, f"{prefix}_*.png")


def build_output_path(png_dir: str, output_name: str = DEFAULT_OUTPUT_NAME) -> str:
    return os.path.join(png_dir, output_name)


def build_video_argv(
    ffmpeg: str,
    png_dir: str,
    prefix: str,
    *,
    fps: int = DEFAULT_FPS,
    output_name: str = DEFAULT_OUTPUT_NAME,
    pad_fix: bool = False,
) -> list[str]:
    """构造 ffmpeg argv（冻结顺序，见模块 docstring）。"""
    head = [ffmpeg, "-y", "-framerate", str(fps), "-pattern_type", "glob"]
    body = ["-i", build_input_pattern(png_dir, prefix)]
    if pad_fix:
        # 必须作为**输出**选项出现在 -i 之后；放前面会被 ffmpeg 拒绝（Q1 实测）
        body += ["-vf", PAD_FILTER]
    tail = [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        build_output_path(png_dir, output_name),
    ]
    return head + body + tail


@dataclass(frozen=True)
class VideoRequest:
    """一次视频合成请求（不可变，便于测试与跨语言移植）。"""

    project_path: str
    prefix: str
    fps: int = DEFAULT_FPS
    output_name: str = DEFAULT_OUTPUT_NAME
    #: 图片目录覆盖（来自 MESA 手册的 ``HR_file_dir``）；None 表示 ``<项目>/png``
    override_png_dir: str | None = None

    @property
    def png_dir(self) -> str:
        return self.override_png_dir or os.path.join(self.project_path, PNG_DIRNAME)

    def validate(self) -> str | None:
        """请求自身的合法性（不看磁盘）；返回第一条错误文案或 ``None``。"""
        return validate_output_name(self.output_name) or validate_fps(self.fps)


class MesaVideoTask:
    """非阻塞的"图片 → 视频"任务（前置校验 + 奇数尺寸自动重试）。"""

    def __init__(
        self,
        project_path: str,
        prefix: str,
        *,
        fps: int = DEFAULT_FPS,
        output_name: str = DEFAULT_OUTPUT_NAME,
        runner: JobRunner | None = None,
        ffmpeg: str | None = None,
        finder: Callable[[Mapping[str, str] | None], str | None] = find_ffmpeg,
        exists: Callable[[str], bool] = os.path.exists,
        png_dir: str | None = None,
    ) -> None:
        # 图片目录按 MESA 手册的 ``HR_file_dir`` 解析（默认 ``png``），
        # 而不是把 ``<项目>/png`` 写死
        self._project_path = project_path
        self.request = VideoRequest(
            project_path,
            prefix,
            fps,
            output_name,
            override_png_dir=resolve_png_dir(project_path, png_dir),
        )
        self._exists = exists
        self._ffmpeg = ffmpeg
        self._finder = finder
        self._runner = runner or JobRunner()
        self._job: Job | None = None
        self._state = PENDING
        self._message = ""
        self._warning: str | None = None
        self._frames = FrameSet(self.request.png_dir, prefix)
        self._attempt = 0
        self._started_at = 0.0
        self._env: Mapping[str, str] | None = None

    # ---------------- 查询 ----------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def message(self) -> str:
        return self._message

    @property
    def warning(self) -> str | None:
        """启动后可能出现的告警（如帧序可疑）；没有则为 ``None``。"""
        return self._warning

    @property
    def job(self) -> Job | None:
        return self._job

    @property
    def frames(self) -> FrameSet:
        """本次要合成的帧序列（``start()`` 之前为空集）。"""
        return self._frames

    @property
    def frame_count(self) -> int:
        return self._frames.count

    @property
    def output_path(self) -> str:
        return build_output_path(self.request.png_dir, self.request.output_name)

    @property
    def finished(self) -> bool:
        return self._state in (SUCCEEDED, FAILED, CANCELLED)

    @property
    def succeeded(self) -> bool:
        return self._state == SUCCEEDED

    @property
    def duration(self) -> float:
        return 0.0 if not self._started_at else time.monotonic() - self._started_at

    # ---------------- 控制 ----------------

    def start(self, env: Mapping[str, str] | None = None) -> bool:
        """校验前置条件并启动第一条 ffmpeg 任务。返回是否成功启动。"""
        if self._job is not None and not self.finished:
            logger.warning("视频任务已在运行，忽略重复 start()")
            return False
        self._env = env
        if not self._exists(self.request.png_dir):
            return self._fail(
                MESSAGE_NO_PNG_DIR.format(png_dir=self.request.png_dir), error=False
            )

        problem = self.request.validate()
        if problem:
            return self._fail(problem, error=False)

        if self._ffmpeg is None:
            self._ffmpeg = self._finder(env)
        if not self._ffmpeg:
            return self._fail(MESSAGE_NO_FFMPEG, error=True)

        # 手册要求"目录里真的得有图"：帧数为 0 时不要启动 ffmpeg，
        # 否则用户只会看到 ffmpeg 的 No such file or directory。
        self._frames = scan_frames(self.request.png_dir, self.request.prefix)
        if self._frames.count == 0:
            return self._fail(self._no_frames_message(), error=False)
        self._warn_if_scrambled()
        logger.info("视频合成输入: %s（fps=%s）", self._frames.describe(), self.request.fps)

        self._started_at = time.monotonic()
        self._start_attempt(pad_fix=False)
        return True

    def _no_frames_message(self) -> str:
        message = MESSAGE_NO_FRAMES.format(
            png_dir=self.request.png_dir,
            pattern=frame_pattern(self.request.prefix),
        )
        note = _other_device_note(self.request.png_dir, self.request.prefix)
        return f"{message}\n{note}" if note else message

    def _warn_if_scrambled(self) -> None:
        """字典序与模型号顺序不一致时告警（ffmpeg glob 按字典序读，会错序）。"""
        if self._frames.order_matches_numbers:
            return
        numbers = self._frames.numbers
        self._warning = MESSAGE_FRAME_ORDER.format(first=min(numbers), last=max(numbers))
        logger.warning(self._warning)

    def _fail(self, message: str, *, error: bool) -> bool:
        self._state = FAILED
        self._message = message
        if error:
            logger.error(message)
        else:
            logger.warning(message)
        return False

    def _start_attempt(self, *, pad_fix: bool) -> None:
        self._attempt += 1
        argv = build_video_argv(
            self._ffmpeg or "ffmpeg",
            self.request.png_dir,
            self.request.prefix,
            fps=self.request.fps,
            output_name=self.request.output_name,
            pad_fix=pad_fix,
        )
        if pad_fix:
            logger.info("检测到尺寸非偶数，正在尝试自动修复（补齐像素）...")
            self._state = RETRYING
        else:
            self._state = RUNNING
        self._job = self._runner.start(argv, name="ffmpeg", env=self._env)

    def poll(self) -> str:
        """推进状态机（UI 定时调用）；返回当前状态。"""
        if self.finished:
            return self._state
        job = self._job
        if job is None:
            return self._state

        status = job.poll()
        if status not in TERMINAL_STATUSES:
            return self._state

        result: JobResult = job.result()
        if result.ok:
            self._state = SUCCEEDED
            self._message = (
                MESSAGE_FIXED.format(output_name=self.request.output_name)
                if self._attempt > 1
                else MESSAGE_SUCCESS.format(output_name=self.request.output_name)
            )
            logger.info(self._message)
            return self._state

        if status is JobStatus.CANCELLED:
            self._state = CANCELLED
            self._message = "已取消视频生成。"
            return self._state

        if self._attempt == 1 and PAD_TRIGGER in (result.stderr or ""):
            self._start_attempt(pad_fix=True)
            return self._state

        detail = (result.stderr or "").strip()
        hint = explain_ffmpeg_failure(detail)
        self._state = FAILED
        self._message = f"{MESSAGE_ERROR_PREFIX}{detail}"
        if hint:
            self._message += f"\n提示：{hint}"
        logger.error("视频生成失败: %s", detail)
        return self._state

    def cancel(self) -> bool:
        if self._job is None or self.finished:
            return False
        if self._job.poll() in TERMINAL_STATUSES:
            # 进程其实已经结束、只是还没被 poll 收走：交给 poll() 给出真实结局，
            # 否则会把已经生成好的视频报成"已取消视频生成"。
            self.poll()
            return False
        cancelled = self._job.cancel()
        if cancelled:
            self._state = CANCELLED
            self._message = "已取消视频生成。"
        return cancelled

    def wait(self, timeout: float | None = None) -> str:
        """同步等待到终态（供 CLI/测试使用）。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.finished:
            self.poll()
            if deadline is not None and time.monotonic() >= deadline:
                self.cancel()
                break
            time.sleep(0.02)
        return self._state


def create_mesa_video(
    project_path: str,
    prefix: str,
    fps: int = DEFAULT_FPS,
    output_name: str = DEFAULT_OUTPUT_NAME,
    *,
    runner: JobRunner | None = None,
    ffmpeg: str | None = None,
    finder: Callable[[Mapping[str, str] | None], str | None] = find_ffmpeg,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """同步兼容接口（原签名/返回值不变）：``(成功?, 消息)``。"""
    task = MesaVideoTask(
        project_path,
        prefix,
        fps=fps,
        output_name=output_name,
        runner=runner,
        ffmpeg=ffmpeg,
        finder=finder,
    )
    if not task.start(env):
        return False, task.message
    task.wait()
    return task.succeeded, task.message
