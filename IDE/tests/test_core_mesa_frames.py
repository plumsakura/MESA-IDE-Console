"""core.mesa.frames 单元测试：pgstar 帧序列的发现规则。

阶段 6 的规格：视频合成前必须知道"目录里到底有哪些帧"。这里的断言就是
规格本身——筛选规则与 ffmpeg ``-pattern_type glob`` 逐条一致
（见 :class:`GlobParity`），因此"本模块数出几帧"就是"ffmpeg 会读到几帧"。
"""

from __future__ import annotations

import glob
import os
import tempfile
import unittest
from pathlib import Path

from core.mesa.frames import (
    DEFAULT_SUFFIX,
    FrameSet,
    frame_number,
    frame_pattern,
    scan_frames,
)


class FramePatterns(unittest.TestCase):
    def test_pattern_matches_pgstar_naming(self) -> None:
        self.assertEqual(frame_pattern("hr"), "hr_*.png")
        self.assertEqual(frame_pattern("trho_profile"), "trho_profile_*.png")
        self.assertEqual(frame_pattern("hr", ".ps"), "hr_*.ps")

    def test_pattern_without_suffix_matches_any_extension(self) -> None:
        self.assertEqual(frame_pattern("hr", None), "hr_*")
        self.assertEqual(frame_pattern("hr", ""), "hr_*")


class FrameNumbers(unittest.TestCase):
    def test_reads_model_number(self) -> None:
        self.assertEqual(frame_number("hr_000001.png", "hr"), 1)
        self.assertEqual(frame_number("trho_profile_000019.png", "trho_profile"), 19)
        self.assertEqual(frame_number("hr_9.png", "hr"), 9)

    def test_rejects_other_prefix_or_suffix(self) -> None:
        self.assertIsNone(frame_number("trho_profile_000001.png", "hr"))
        self.assertIsNone(frame_number("hr_000001.png", "hr", ".ps"))
        self.assertIsNone(frame_number("hr_000001.png", "hr", None))

    def test_rejects_names_without_number(self) -> None:
        self.assertIsNone(frame_number("hr_extra.png", "hr"))
        self.assertIsNone(frame_number("hr_000001_old.png", "hr"))
        self.assertIsNone(frame_number("hr.png", "hr"))
        self.assertIsNone(frame_number("", "hr"))


class FrameSetDescription(unittest.TestCase):
    def test_describes_count_and_model_range(self) -> None:
        frames = FrameSet("/p", "hr", DEFAULT_SUFFIX, ("hr_000001.png", "hr_000019.png"))
        self.assertEqual(frames.count, 2)
        self.assertEqual(frames.numbers, (1, 19))
        self.assertEqual(frames.pattern, "hr_*.png")
        self.assertEqual(frames.describe(), "2 帧（hr_*.png，模型号 1→19）")

    def test_empty_set_is_described_as_not_found(self) -> None:
        self.assertEqual(
            FrameSet("/p", "hr").describe(), "未找到匹配 'hr_*.png' 的图片"
        )

    def test_unnumbered_files_are_counted_but_not_ranged(self) -> None:
        frames = FrameSet("/p", "hr", DEFAULT_SUFFIX, ("hr_extra.png",))
        self.assertEqual(frames.count, 1)
        self.assertEqual(frames.numbers, ())
        self.assertEqual(frames.describe(), "1 帧（hr_*.png）")

    def test_order_matches_numbers_detects_scrambled_digits(self) -> None:
        ordered = FrameSet("/p", "hr", DEFAULT_SUFFIX, ("hr_0001.png", "hr_0002.png"))
        scrambled = FrameSet("/p", "hr", DEFAULT_SUFFIX, ("hr_1000.png", "hr_999.png"))

        self.assertTrue(ordered.order_matches_numbers)
        self.assertFalse(scrambled.order_matches_numbers, "字典序 ≠ 模型号顺序必须能被发现")


class ScanFrames(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def touch(self, *names: str) -> None:
        for name in names:
            (self.base / name).write_bytes(b"x")

    def test_missing_directory_returns_empty_set(self) -> None:
        frames = scan_frames(str(self.base / "nope"), "hr")
        self.assertEqual(frames.count, 0)
        self.assertEqual(frames.files, ())

    def test_listdir_failure_is_swallowed(self) -> None:
        def boom(path: str):
            raise PermissionError("denied")

        self.assertEqual(scan_frames("/p", "hr", listdir=boom).count, 0)

    def test_selects_only_prefix_and_suffix(self) -> None:
        self.touch(
            "hr_000002.png",
            "hr_000001.png",
            "trho_profile_000001.png",
            "hr_000003.jpg",
            "notes.txt",
        )
        frames = scan_frames(str(self.base), "hr")

        self.assertEqual(frames.files, ("hr_000001.png", "hr_000002.png"))
        self.assertEqual(frames.numbers, (1, 2))

    def test_suffix_none_matches_every_extension(self) -> None:
        self.touch("hr_000001.png", "hr_000001.ps", "other_000001.ps")
        frames = scan_frames(str(self.base), "hr", None)

        self.assertEqual(frames.files, ("hr_000001.png", "hr_000001.ps"))
        self.assertEqual(scan_frames(str(self.base), "hr", ".ps").files, ("hr_000001.ps",))

    def test_empty_prefix_matches_leading_underscore_only(self) -> None:
        self.touch("hr_000001.png", "_hidden_000001.png")
        self.assertEqual(scan_frames(str(self.base), "").files, ("_hidden_000001.png",))


class GlobParity(unittest.TestCase):
    """筛选规则必须与 ffmpeg 的 ``-pattern_type glob`` 一致（POSIX glob 语义）。"""

    NAMES = (
        "hr_000001.png",
        "hr_000002.png",
        "hr_extra.png",
        "hr_.png",
        "hr_000003.PNG",
        "hr_000004.jpg",
        "xhr_000005.png",
        ".hr_000006.png",
        "trho_profile_000001.png",
    )

    def test_matches_python_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in self.NAMES:
                Path(tmp, name).write_bytes(b"x")
            expected = tuple(
                sorted(os.path.basename(p) for p in glob.glob(os.path.join(tmp, "hr_*.png")))
            )

            frames = scan_frames(tmp, "hr")

        self.assertEqual(frames.files, expected)
        self.assertEqual(
            frames.count, 4, "隐藏文件/大小写/其它扩展名都不算，hr_extra.png 与 hr_.png 算"
        )

    def test_matches_glob_for_other_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in self.NAMES:
                Path(tmp, name).write_bytes(b"x")
            expected = tuple(
                sorted(
                    os.path.basename(p)
                    for p in glob.glob(os.path.join(tmp, "trho_profile_*.png"))
                )
            )

            frames = scan_frames(tmp, "trho_profile")

        self.assertEqual(frames.files, expected)


if __name__ == "__main__":
    unittest.main()
