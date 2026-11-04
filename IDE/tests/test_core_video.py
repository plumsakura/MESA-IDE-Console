"""core.video 单元测试：ffmpeg argv 冻结 + 非阻塞状态机。

用假 runner 驱动状态机，**不需要真实 ffmpeg**，因此可在任何环境确定性地
验证：成功、奇数尺寸自动重试、其他失败、取消、png 目录缺失、ffmpeg 缺失。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from core.jobs import JobResult, JobStatus
from core.video import (
    DEFAULT_OUTPUT_NAME,
    MESSAGE_BAD_FPS,
    MESSAGE_BAD_OUTPUT,
    MESSAGE_FRAME_ORDER,
    MESSAGE_FIXED,
    MESSAGE_NO_FFMPEG,
    MESSAGE_NO_FRAMES,
    MESSAGE_NO_PNG_DIR,
    MESSAGE_SUCCESS,
    PAD_FILTER,
    MesaVideoTask,
    build_input_pattern,
    build_output_path,
    build_video_argv,
    create_mesa_video,
    explain_ffmpeg_failure,
    find_ffmpeg,
    resolve_png_dir,
    validate_fps,
    validate_output_name,
)

FFMPEG = "/usr/bin/ffmpeg"
PROJECT = "/tmp/proj"
PNG_DIR = os.path.join(PROJECT, "png")


def write_frames(
    directory,
    prefix: str,
    *,
    count: int = 3,
    digits: int = 6,
    start: int = 1,
    step: int = 1,
    suffix: str = ".png",
) -> tuple[str, ...]:
    """写出一组占位帧，文件名与 pgstar 落盘约定一致（``<prefix>_<模型号>.png``）。"""
    base = Path(directory)
    names = []
    for index in range(count):
        name = f"{prefix}_{start + index * step:0{digits}d}{suffix}"
        (base / name).write_bytes(b"x")
        names.append(name)
    return tuple(names)


class VideoArgvFrozen(unittest.TestCase):
    """ffmpeg 参数顺序属冻结行为（与原 mesa_video_maker.py 逐字一致）。"""

    def test_plain_argv_matches_baseline(self) -> None:
        self.assertEqual(
            build_video_argv(FFMPEG, PNG_DIR, "hr"),
            [
                FFMPEG, "-y", "-framerate", "10", "-pattern_type", "glob",
                "-i", f"{PNG_DIR}/hr_*.png",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                f"{PNG_DIR}/{DEFAULT_OUTPUT_NAME}",
            ],
        )

    def test_pad_filter_is_placed_after_input(self) -> None:
        """**行为变更（阶段 5，Q1 修复）**：pad 滤镜必须在 ``-i`` **之后**。

        基线把它插在 ``-i`` 之前，真实 ffmpeg 会直接拒绝：
        ``Option vf ... cannot be applied to input url ... Move this option
        before the file it belongs to``（实测 ffmpeg 8.0.1 退出码 234），
        导致"奇数尺寸自动重试"这条路径**永远失败**。
        """
        argv = build_video_argv(FFMPEG, PNG_DIR, "hr", pad_fix=True)
        input_index = argv.index("-i")
        filter_index = argv.index("-vf")

        self.assertGreater(filter_index, input_index, "-vf 必须出现在 -i 之后")
        self.assertEqual(argv[filter_index + 1], PAD_FILTER)
        self.assertLess(filter_index, argv.index("-c:v"), "-vf 属于输出选项")
        self.assertEqual(argv.count("-vf"), 1)
        # 输入部分保持冻结顺序
        self.assertEqual(
            argv[: input_index + 2],
            [FFMPEG, "-y", "-framerate", "10", "-pattern_type", "glob",
             "-i", f"{PNG_DIR}/hr_*.png"],
        )

    def test_pad_retry_argv_still_targets_same_output(self) -> None:
        argv = build_video_argv(FFMPEG, PNG_DIR, "hr", pad_fix=True)
        self.assertEqual(argv[-1], f"{PNG_DIR}/{DEFAULT_OUTPUT_NAME}")

    def test_custom_fps_and_output_name(self) -> None:
        argv = build_video_argv(FFMPEG, PNG_DIR, "rho", fps=24, output_name="movie.mp4")
        self.assertIn("24", argv)
        self.assertEqual(argv[-1], f"{PNG_DIR}/movie.mp4")
        self.assertIn(f"{PNG_DIR}/rho_*.png", argv)

    def test_path_helpers(self) -> None:
        self.assertEqual(build_input_pattern(PNG_DIR, "hr"), f"{PNG_DIR}/hr_*.png")
        self.assertEqual(build_output_path(PNG_DIR), f"{PNG_DIR}/{DEFAULT_OUTPUT_NAME}")


class FindFfmpeg(unittest.TestCase):
    def test_prefers_path(self) -> None:
        self.assertEqual(
            find_ffmpeg({}, which=lambda name: "/usr/bin/ffmpeg", exists=lambda p: False),
            "/usr/bin/ffmpeg",
        )

    def test_falls_back_to_mesa_dir(self) -> None:
        env = {"MESA_DIR": "/opt/mesa"}
        found = find_ffmpeg(
            env,
            which=lambda name: None,
            exists=lambda path: path == "/opt/mesa/bin/ffmpeg",
        )
        self.assertEqual(found, "/opt/mesa/bin/ffmpeg")

    def test_returns_none_when_nothing_found(self) -> None:
        self.assertIsNone(find_ffmpeg({}, which=lambda name: None, exists=lambda p: False))
        self.assertIsNone(find_ffmpeg({"MESA_DIR": ""}, which=lambda n: None, exists=lambda p: True))


class FakeJob:
    """可控的假 Job（只实现状态机用到的接口）。"""

    def __init__(self, argv, *, status=JobStatus.RUNNING, returncode=None, stdout="", stderr=""):
        self.argv = list(argv)
        self._status = status
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.cancelled = False

    def finish(self, status, returncode=0, stderr="") -> None:
        self._status = status
        self._returncode = returncode
        self._stderr = stderr

    def poll(self):
        return self._status

    def result(self) -> JobResult:
        return JobResult(
            name="ffmpeg",
            status=self._status,
            returncode=self._returncode,
            stdout=self._stdout,
            stderr=self._stderr,
            duration=0.01,
            argv=tuple(self.argv),
        )

    def cancel(self) -> bool:
        self.cancelled = True
        self._status = JobStatus.CANCELLED
        return True


class FakeRunner:
    def __init__(self) -> None:
        self.started: list[FakeJob] = []

    def start(self, argv, **kwargs) -> FakeJob:
        job = FakeJob(argv)
        self.started.append(job)
        return job


class MesaVideoTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = self._tmp.name
        self.png_dir = Path(self.project) / "png"
        self.png_dir.mkdir()
        # 前置校验要求目录里真的有帧（阶段 6 行为变更①）
        self.frames = write_frames(self.png_dir, "hr", count=3, digits=6)
        self.runner = FakeRunner()

    def make_task(self, **kwargs) -> MesaVideoTask:
        params = dict(runner=self.runner, ffmpeg=FFMPEG)
        params.update(kwargs)
        return MesaVideoTask(self.project, "hr", **params)

    # ---------------- 前置校验 ----------------

    def test_missing_png_dir_fails_without_starting(self) -> None:
        empty_project = tempfile.mkdtemp(dir=self._tmp.name)
        task = MesaVideoTask(empty_project, "hr", runner=self.runner, ffmpeg=FFMPEG)

        self.assertFalse(task.start())
        self.assertEqual(task.state, "failed")
        self.assertEqual(
            task.message,
            MESSAGE_NO_PNG_DIR.format(png_dir=os.path.join(empty_project, "png")),
        )
        self.assertEqual(self.runner.started, [])

    def test_missing_ffmpeg_fails_without_starting(self) -> None:
        task = self.make_task(finder=lambda env: None)
        task._ffmpeg = None  # 强制走查找路径

        self.assertFalse(task.start())
        self.assertEqual(task.message, MESSAGE_NO_FFMPEG)
        self.assertEqual(self.runner.started, [])

    # ---------------- 正常路径 ----------------

    def test_success_first_attempt(self) -> None:
        task = self.make_task()
        self.assertTrue(task.start())
        self.assertEqual(task.state, "running")
        self.assertEqual(len(self.runner.started), 1)

        self.runner.started[0].finish(JobStatus.SUCCEEDED, 0)
        self.assertEqual(task.poll(), "succeeded")
        self.assertEqual(
            task.message, MESSAGE_SUCCESS.format(output_name=DEFAULT_OUTPUT_NAME)
        )
        self.assertTrue(task.succeeded)
        self.assertEqual(task.output_path, str(self.png_dir / DEFAULT_OUTPUT_NAME))

    def test_pad_retry_on_odd_dimensions(self) -> None:
        task = self.make_task()
        task.start()

        self.runner.started[0].finish(
            JobStatus.FAILED, 1, stderr="height not divisible by 2 (641x361)"
        )
        self.assertEqual(task.poll(), "retrying")
        self.assertEqual(len(self.runner.started), 2, "必须自动重试一次")
        self.assertIn(PAD_FILTER, self.runner.started[1].argv)

        self.runner.started[1].finish(JobStatus.SUCCEEDED, 0)
        self.assertEqual(task.poll(), "succeeded")
        self.assertEqual(
            task.message, MESSAGE_FIXED.format(output_name=DEFAULT_OUTPUT_NAME)
        )
        self.assertEqual(len(self.runner.started), 2)

    def test_second_failure_is_final(self) -> None:
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(
            JobStatus.FAILED, 1, stderr="height not divisible by 2"
        )
        task.poll()
        self.runner.started[1].finish(JobStatus.FAILED, 1, stderr="height not divisible by 2")

        self.assertEqual(task.poll(), "failed")
        self.assertEqual(len(self.runner.started), 2, "不得无限重试")
        self.assertIn("FFmpeg error:", task.message)

    def test_failure_without_pad_hint_is_final_immediately(self) -> None:
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(JobStatus.FAILED, 1, stderr="boom")

        self.assertEqual(task.poll(), "failed")
        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual(
            task.message,
            "FFmpeg error: boom",
            "识别不了的报错必须与旧行为逐字一致（不追加建议）",
        )

    def test_known_failure_appends_actionable_hint(self) -> None:
        """**行为变更③**：已知报错追加一行可执行建议，前缀仍是 ``FFmpeg error:``。"""
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(
            JobStatus.FAILED, 1, stderr="hr_000001.png: No such file or directory"
        )

        self.assertEqual(task.poll(), "failed")
        self.assertTrue(task.message.startswith("FFmpeg error: hr_000001.png"), task.message)
        self.assertIn("提示：", task.message)
        self.assertIn("inlist_pgstar", task.message)

    def test_poll_before_finish_keeps_running(self) -> None:
        task = self.make_task()
        task.start()
        self.assertEqual(task.poll(), "running")
        self.assertEqual(task.poll(), "running")

    def test_second_start_is_ignored_while_running(self) -> None:
        """重复 start() 不得启动第二个 ffmpeg（否则前一个变成孤儿进程）。"""
        task = self.make_task()
        self.assertTrue(task.start())

        self.assertFalse(task.start(), "运行中重复启动必须被拒绝")
        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual(task.state, "running")

    def test_cancel(self) -> None:
        task = self.make_task()
        task.start()
        self.assertTrue(task.cancel())
        self.assertEqual(task.state, "cancelled")
        self.assertTrue(self.runner.started[0].cancelled)
        self.assertFalse(task.cancel(), "终态后取消应返回 False")

    def test_cancel_after_job_finished_reports_real_result(self) -> None:
        """**行为变更④**：进程已结束但未 poll 时，取消不得把成片报成"已取消"。"""
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(JobStatus.SUCCEEDED, 0)  # 结束了，但还没 poll

        self.assertFalse(task.cancel(), "已结束的任务不该被当成取消成功")
        self.assertEqual(task.state, "succeeded", "必须收尾给出真实结局")
        self.assertFalse(self.runner.started[0].cancelled)
        self.assertEqual(
            task.message, MESSAGE_SUCCESS.format(output_name=DEFAULT_OUTPUT_NAME)
        )

    def test_cancel_after_real_failure_reports_failure(self) -> None:
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(JobStatus.FAILED, 1, stderr="boom")

        self.assertFalse(task.cancel())
        self.assertEqual(task.state, "failed")
        self.assertEqual(task.message, "FFmpeg error: boom")

    def test_wait_reaches_terminal_state(self) -> None:
        task = self.make_task()
        task.start()
        self.runner.started[0].finish(JobStatus.SUCCEEDED, 0)
        self.assertEqual(task.wait(timeout=2), "succeeded")

    def test_retry_keeps_environment(self) -> None:
        task = self.make_task()
        env = {"MESA_DIR": "/opt/mesa"}
        task.start(env=env)
        self.runner.started[0].finish(JobStatus.FAILED, 1, stderr="not divisible by 2")
        task.poll()
        self.assertEqual(len(self.runner.started), 2)


class CreateMesaVideoCompat(unittest.TestCase):
    """同步兼容接口（原签名与文案）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = self._tmp.name
        (Path(self.project) / "png").mkdir()
        write_frames(Path(self.project) / "png", "hr")
        self.runner = FakeRunner()

    def test_success(self) -> None:
        class AutoFinishRunner(FakeRunner):
            def start(self, argv, **kwargs):
                job = FakeJob(argv, status=JobStatus.SUCCEEDED, returncode=0)
                self.started.append(job)
                return job

        ok, message = create_mesa_video(
            self.project, "hr", runner=AutoFinishRunner(), ffmpeg=FFMPEG
        )
        self.assertTrue(ok)
        self.assertEqual(message, f"成功生成视频: {DEFAULT_OUTPUT_NAME}")

    def test_missing_png_dir_reports_original_message(self) -> None:
        empty = tempfile.mkdtemp(dir=self._tmp.name)
        ok, message = create_mesa_video(empty, "hr", runner=self.runner, ffmpeg=FFMPEG)
        self.assertFalse(ok)
        self.assertEqual(message, f"错误：png 目录不存在: {os.path.join(empty, 'png')}")

    def test_failure_message_matches_baseline(self) -> None:
        class FailingRunner(FakeRunner):
            def start(self, argv, **kwargs):
                job = FakeJob(argv, status=JobStatus.FAILED, returncode=1, stderr="boom")
                self.started.append(job)
                return job

        ok, message = create_mesa_video(
            self.project, "hr", runner=FailingRunner(), ffmpeg=FFMPEG
        )
        self.assertFalse(ok)
        self.assertEqual(message, "FFmpeg error: boom")


class RequestValidation(unittest.TestCase):
    """阶段 6 新增的参数校验（纯函数）。"""

    def test_output_name_accepts_plain_filenames(self) -> None:
        for good in ("evolution_movie.mp4", "hr.mp4", "中文名.mp4"):
            self.assertIsNone(validate_output_name(good), good)

    def test_output_name_rejects_paths(self) -> None:
        """输出名带路径会把视频写到图片目录之外，必须拦下。"""
        for bad in ("", "..", "../escape.mp4", "sub/out.mp4", "a\\b.mp4"):
            self.assertEqual(
                validate_output_name(bad),
                MESSAGE_BAD_OUTPUT.format(output_name=bad),
                bad,
            )

    def test_fps_must_be_positive_integer(self) -> None:
        self.assertIsNone(validate_fps(10))
        self.assertIsNone(validate_fps("24"))
        for bad in (0, -3, "fast", None):
            self.assertEqual(validate_fps(bad), MESSAGE_BAD_FPS.format(fps=bad), bad)


class ExplainFailureHints(unittest.TestCase):
    """把 ffmpeg 的英文报错翻成可执行建议；识别不了就保持原样。"""

    def test_known_errors_get_hints(self) -> None:
        self.assertIn(
            "inlist_pgstar", explain_ffmpeg_failure("hr_1.png: No such file or directory")
        )
        self.assertIn("权限", explain_ffmpeg_failure("Permission denied"))
        self.assertIn("libx264", explain_ffmpeg_failure("Unknown encoder 'libx264'"))
        self.assertIn("pad", explain_ffmpeg_failure("height not divisible by 2"))

    def test_unknown_errors_get_none(self) -> None:
        self.assertIsNone(explain_ffmpeg_failure("boom"))
        self.assertIsNone(explain_ffmpeg_failure(""))
        self.assertIsNone(explain_ffmpeg_failure("   "))


class ResolvePngDir(unittest.TestCase):
    def test_override_wins(self) -> None:
        self.assertEqual(resolve_png_dir("/proj", "/plots"), "/plots")

    def test_reads_hr_file_dir_from_inlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "inlist").write_text(
                "&pgstar\n HR_file_dir = 'PLOTS'\n/\n", encoding="utf-8"
            )
            self.assertEqual(resolve_png_dir(tmp), os.path.join(tmp, "PLOTS"))

    def test_defaults_to_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_png_dir(tmp), os.path.join(tmp, "png"))


class PreflightValidation(unittest.TestCase):
    """阶段 6 行为变更①②：启动 ffmpeg **之前**就把注定失败的情况挡掉。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = self._tmp.name
        self.png_dir = Path(self.project) / "png"
        self.png_dir.mkdir()
        self.runner = FakeRunner()

    def make_task(self, prefix: str = "hr", **kwargs) -> MesaVideoTask:
        params = dict(runner=self.runner, ffmpeg=FFMPEG)
        params.update(kwargs)
        return MesaVideoTask(self.project, prefix, **params)

    def test_no_frames_fails_without_starting_ffmpeg(self) -> None:
        task = self.make_task()

        self.assertFalse(task.start())
        self.assertEqual(task.state, "failed")
        self.assertTrue(
            task.message.startswith(
                MESSAGE_NO_FRAMES.format(png_dir=str(self.png_dir), pattern="hr_*.png")
            ),
            task.message,
        )
        self.assertIn("HR_file_flag", task.message, "必须给出可执行的 inlist 设置")
        self.assertEqual(self.runner.started, [], "没有帧就不该启动 ffmpeg")
        self.assertEqual(task.frame_count, 0)

    def test_non_png_frames_explain_file_device(self) -> None:
        """手册允许 ``file_device = 'vcps'``（PostScript）：要说清为什么合成不了。"""
        write_frames(self.png_dir, "hr", count=2, suffix=".ps")
        task = self.make_task()

        self.assertFalse(task.start())
        self.assertIn(".ps", task.message)
        self.assertIn("vcps", task.message)
        self.assertEqual(self.runner.started, [])

    def test_other_prefix_frames_do_not_count(self) -> None:
        write_frames(self.png_dir, "trho_profile", count=2)
        task = self.make_task("hr")

        self.assertFalse(task.start())
        self.assertIn("未找到匹配 'hr_*.png'", task.message)
        self.assertEqual(self.runner.started, [])

    def test_bad_output_name_is_rejected_before_ffmpeg(self) -> None:
        for bad in ("", "..", "../escape.mp4", "sub/out.mp4", "a\\b.mp4"):
            with self.subTest(output_name=bad):
                task = self.make_task(output_name=bad)
                self.assertFalse(task.start())
                self.assertEqual(task.message, MESSAGE_BAD_OUTPUT.format(output_name=bad))
        self.assertEqual(self.runner.started, [])

    def test_bad_fps_is_rejected_before_ffmpeg(self) -> None:
        for bad in (0, -1, "fast"):
            with self.subTest(fps=bad):
                task = self.make_task(fps=bad)
                self.assertFalse(task.start())
                self.assertEqual(task.message, MESSAGE_BAD_FPS.format(fps=bad))
        self.assertEqual(self.runner.started, [])

    def test_frame_set_is_exposed_after_start(self) -> None:
        write_frames(self.png_dir, "hr", count=10, start=1, step=2, digits=6)
        task = self.make_task()

        self.assertTrue(task.start())
        self.assertEqual(task.frame_count, 10)
        self.assertEqual(task.frames.numbers, tuple(range(1, 20, 2)))
        self.assertIn("10 帧", task.frames.describe())
        self.assertIsNone(task.warning)
        self.assertEqual(len(self.runner.started), 1)

    def test_scrambled_frame_order_warns_but_still_runs(self) -> None:
        """``file_digits`` 太小 → 字典序 ≠ 模型号顺序 → 告警（不改冻结命令）。"""
        write_frames(self.png_dir, "hr", count=1, digits=3, start=999)
        write_frames(self.png_dir, "hr", count=1, digits=4, start=1000)
        task = self.make_task()

        self.assertTrue(task.start(), task.message)
        self.assertEqual(
            task.warning, MESSAGE_FRAME_ORDER.format(first=999, last=1000)
        )
        self.assertEqual(task.state, "running", "只告警，不阻断合成")
        self.assertEqual(len(self.runner.started), 1)

    def test_missing_ffmpeg_is_reported_before_frame_scan(self) -> None:
        """没有 ffmpeg 时先报工具缺失（与旧行为一致的文案）。"""
        task = self.make_task(finder=lambda env: None)
        task._ffmpeg = None

        self.assertFalse(task.start())
        self.assertEqual(task.message, MESSAGE_NO_FFMPEG)


if __name__ == "__main__":
    unittest.main()


class PngDirOverride(unittest.TestCase):
    """按 MESA 手册的 ``HR_file_dir`` 使用自定义图片目录（不再写死 <项目>/png）。"""

    def test_task_uses_provided_png_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plots = Path(tmp) / "PLOTS"
            plots.mkdir()
            (plots / "hr_000001.png").write_bytes(b"x")

            task = MesaVideoTask(str(Path(tmp)), "hr", ffmpeg=FFMPEG, png_dir=str(plots))

            self.assertEqual(Path(task.output_path).parent, plots)
            self.assertEqual(Path(task.request.png_dir), plots)

    def test_default_png_dir_still_used_without_override(self) -> None:
        task = MesaVideoTask("/proj", "hr", ffmpeg=FFMPEG)
        self.assertEqual(task.request.png_dir, os.path.join("/proj", "png"))


class RealFfmpegIntegration(unittest.TestCase):
    """**真实 ffmpeg** 端到端：奇数尺寸 PNG → 自动重试 → 真的产出视频。

    这是 Q1 的回归护栏：基线把 ``-vf pad`` 放在 ``-i`` 之前，真实 ffmpeg 会
    直接拒绝该命令，于是"奇数尺寸自动重试"永远失败（实测退出码 234）。
    """

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("系统没有 ffmpeg")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("没有 Pillow，无法生成测试 PNG")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "proj"
        self.png_dir = self.project / "png"
        self.png_dir.mkdir(parents=True)
        self._write_pngs(size=(11, 11), count=3)  # 奇数尺寸，触发 pad 重试

    def _write_pngs(self, *, size, count) -> None:
        from PIL import Image

        for index in range(1, count + 1):
            Image.new("RGB", size, (index * 20, 30, 40)).save(
                self.png_dir / f"hr_{index:04d}.png"
            )

    def test_pad_argv_is_accepted_by_real_ffmpeg(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        argv = build_video_argv(ffmpeg, str(self.png_dir), "hr", pad_fix=True)

        done = subprocess.run(argv, capture_output=True, text=True)

        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn(PAD_FILTER, argv)
        self.assertTrue((self.png_dir / DEFAULT_OUTPUT_NAME).is_file())

    def test_plain_argv_fails_on_odd_dimensions(self) -> None:
        """证明"为什么需要重试"：libx264+yuv420p 不接受奇数尺寸。"""
        ffmpeg = shutil.which("ffmpeg")
        argv = build_video_argv(ffmpeg, str(self.png_dir), "hr")

        done = subprocess.run(argv, capture_output=True, text=True)

        self.assertNotEqual(done.returncode, 0)

    def test_video_task_retries_and_succeeds_with_real_ffmpeg(self) -> None:
        task = MesaVideoTask(str(self.project), "hr", ffmpeg=shutil.which("ffmpeg"))

        self.assertTrue(task.start(), task.message)
        deadline = time.monotonic() + 120
        while task.poll() not in {"succeeded", "failed", "cancelled"}:
            if time.monotonic() > deadline:
                self.fail(f"视频任务超时，状态={task.state} 消息={task.message}")
            time.sleep(0.05)

        self.assertEqual(task.state, "succeeded", task.message)
        self.assertIn("自动修复成功", task.message, "应走 pad 重试路径")
        self.assertTrue(os.path.getsize(task.output_path) > 0)

    def test_frame_count_matches_video_stream(self) -> None:
        """前置校验数出的帧数 = 视频里真正的帧数（规范与产物一致）。"""
        if shutil.which("ffprobe") is None:
            self.skipTest("系统没有 ffprobe")
        task = MesaVideoTask(str(self.project), "hr", ffmpeg=shutil.which("ffmpeg"))
        self.assertTrue(task.start(), task.message)
        self.assertEqual(task.wait(timeout=120), "succeeded", task.message)

        probe = subprocess.run(
            [
                shutil.which("ffprobe"), "-v", "error", "-count_frames",
                "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                "-of", "csv=p=0", task.output_path,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr[-300:])
        self.assertEqual(int(probe.stdout.strip()), task.frame_count)
