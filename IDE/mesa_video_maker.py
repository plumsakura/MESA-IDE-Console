"""兼容层（薄代理）：视频合成。

实现已迁移到 :mod:`core.video`（**非阻塞状态机**，修复 P9）。
本文件保留旧导入路径与旧签名 ``create_mesa_video(project, prefix) -> (bool, str)``，
其内部改为同步等待 core 的任务；需要不阻塞 UI 的新代码请直接用
:class:`core.video.MesaVideoTask`（见 ``ide_ui/app.py``）。

阶段 6 起 ``core.video`` 还提供（本文件一并转发）：启动前的帧序列校验
（``core.mesa.frames``）、参数校验 ``validate_output_name`` / ``validate_fps``、
失败建议 ``explain_ffmpeg_failure``、帧序告警 ``MesaVideoTask.warning``。
"""

from __future__ import annotations

from core.video import (
    CANCELLED,
    DEFAULT_FPS,
    DEFAULT_OUTPUT_NAME,
    FAILED,
    MESSAGE_FIXED,
    MESSAGE_NO_FFMPEG,
    MESSAGE_NO_FRAMES,
    MESSAGE_NO_PNG_DIR,
    MESSAGE_SUCCESS,
    PAD_FILTER,
    PENDING,
    RETRYING,
    RUNNING,
    SUCCEEDED,
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

__all__ = [
    "MesaVideoTask",
    "create_mesa_video",
    "find_ffmpeg",
    "build_video_argv",
    "build_input_pattern",
    "build_output_path",
    "resolve_png_dir",
    "explain_ffmpeg_failure",
    "validate_output_name",
    "validate_fps",
    "DEFAULT_FPS",
    "DEFAULT_OUTPUT_NAME",
    "PAD_FILTER",
    "PENDING",
    "RUNNING",
    "RETRYING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "MESSAGE_NO_PNG_DIR",
    "MESSAGE_NO_FRAMES",
    "MESSAGE_NO_FFMPEG",
    "MESSAGE_SUCCESS",
    "MESSAGE_FIXED",
]
