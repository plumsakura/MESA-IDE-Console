"""按 MESA 手册解析项目的输出约定（``core.mesa.outputs``）。

依据（源码内官方手册 + ``star/defaults``）：

- ``log_directory = 'LOGS'``、``star_history_name = 'history.data'``（controls）
- ``photo_directory = 'photos'``、``photo_interval``（controls）
- ``profile_interval``、``max_num_profile_models``（controls）
- pgstar：``file_device``、``HR_file_flag``/``HR_file_interval``/``HR_file_prefix``/
  ``HR_file_dir``（pgstar）

这些**都是用户可以改的**；IDE 原先全写死 ``LOGS``/``photos``/``hr_``，
用户一改就静默失效。本模块只做"解析 + 给默认值"，纯标准库、可注入。
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from core.mesa.outputs import (
    DEFAULT_HISTORY_NAME,
    DEFAULT_LOG_DIR,
    DEFAULT_PHOTO_DIR,
    DEFAULT_PNG_DIR,
    MesaOutputs,
    parse_namelist_values,
    resolve_outputs,
)

REAL_PROJECT = pathlib.Path.home() / "MESA_program" / "pgstar_test"


class ParseNamelistValues(unittest.TestCase):
    def test_simple_assignments_and_comments(self) -> None:
        text = (
            "&controls\n"
            "   max_model_number = 20 ! 短跑\n"
            "   log_directory = 'myLOGS'\n"
            "   ! 注释行\n"
            "   history_interval = 5\n"
            "/\n"
        )
        values = parse_namelist_values(text)
        self.assertEqual(values["max_model_number"], "20")
        self.assertEqual(values["log_directory"], "myLOGS")
        self.assertEqual(values["history_interval"], "5")

    def test_quotes_and_case_are_normalised(self) -> None:
        values = parse_namelist_values('&controls\n  LOG_DIRECTORY = "logs2"\n/\n')
        self.assertEqual(values["log_directory"], "logs2")

    def test_array_parameters_keep_index(self) -> None:
        values = parse_namelist_values(
            "&controls\n  xa_central_lower_limit(1) = 1d-3\n/\n"
        )
        self.assertEqual(values["xa_central_lower_limit(1)"], "1d-3")

    def test_extra_inlist_names_are_reported(self) -> None:
        values = parse_namelist_values(
            "&star_job\n"
            "  read_extra_star_job_inlist(1) = .true.\n"
            "  extra_star_job_inlist_name(1) = 'inlist_project'\n"
            "  read_extra_star_job_inlist(2) = .true.\n"
            "  extra_star_job_inlist_name(2) = 'inlist_extra'\n"
            "/\n"
        )
        self.assertEqual(
            values["extra_star_job_inlist_name(1)"], "inlist_project"
        )
        self.assertEqual(values["extra_star_job_inlist_name(2)"], "inlist_extra")

    def test_blank_and_comment_only_input(self) -> None:
        self.assertEqual(parse_namelist_values(""), {})
        self.assertEqual(parse_namelist_values("! 只有注释\n\n"), {})

    def test_does_not_crash_on_garbage(self) -> None:
        values = parse_namelist_values("这不是 namelist\n= =\n&controls\n/\n")
        self.assertEqual(values, {})


class ResolveOutputsDefaults(unittest.TestCase):
    def test_defaults_match_mesa_manual(self) -> None:
        outputs = resolve_outputs("/proj", values={})

        self.assertEqual(outputs.log_dir, "/proj/LOGS")
        self.assertEqual(outputs.history_path, "/proj/LOGS/history.data")
        self.assertEqual(outputs.index_path, "/proj/LOGS/profiles.index")
        self.assertEqual(outputs.photo_dir, "/proj/photos")
        self.assertEqual(outputs.png_dir, "/proj/png")
        self.assertEqual(outputs.pgstar_prefix, "hr")
        self.assertEqual(outputs.profile_prefix, "profile")

    def test_constants_match_mesa_defaults(self) -> None:
        self.assertEqual(DEFAULT_LOG_DIR, "LOGS")
        self.assertEqual(DEFAULT_HISTORY_NAME, "history.data")
        self.assertEqual(DEFAULT_PHOTO_DIR, "photos")
        self.assertEqual(DEFAULT_PNG_DIR, "png")


class ResolveOutputsOverrides(unittest.TestCase):
    def test_custom_log_directory_and_history_name(self) -> None:
        outputs = resolve_outputs(
            "/proj",
            values={"log_directory": "myLOGS", "star_history_name": "hist.data"},
        )

        self.assertEqual(outputs.log_dir, "/proj/myLOGS")
        self.assertEqual(outputs.history_path, "/proj/myLOGS/hist.data")
        self.assertEqual(outputs.index_path, "/proj/myLOGS/profiles.index")

    def test_absolute_log_directory_is_honoured(self) -> None:
        outputs = resolve_outputs("/proj", values={"log_directory": "/data/logs"})
        self.assertEqual(outputs.log_dir, "/data/logs")

    def test_custom_photo_directory(self) -> None:
        outputs = resolve_outputs("/proj", values={"photo_directory": "snapshots"})
        self.assertEqual(outputs.photo_dir, "/proj/snapshots")

    def test_pgstar_file_settings(self) -> None:
        outputs = resolve_outputs(
            "/proj",
            values={
                "HR_file_dir": "plots",
                "HR_file_prefix": "hr_",
                "HR_file_flag": ".true.",
                "HR_file_interval": "1",
                "file_device": "png",
            },
        )

        self.assertEqual(outputs.png_dir, "/proj/plots")
        self.assertEqual(outputs.pgstar_prefix, "hr_".rstrip("_") or "hr")
        self.assertTrue(outputs.pgstar_files_enabled)
        self.assertEqual(outputs.pgstar_file_interval, 1)

    def test_pgstar_files_disabled_by_default(self) -> None:
        outputs = resolve_outputs("/proj", values={})
        self.assertFalse(outputs.pgstar_files_enabled)

    def test_invalid_numbers_fall_back(self) -> None:
        outputs = resolve_outputs(
            "/proj", values={"HR_file_interval": "abc", "photo_interval": "-3"}
        )
        self.assertIsNone(outputs.pgstar_file_interval)
        self.assertIsNone(outputs.photo_interval)

    def test_values_are_stripped_and_quoted(self) -> None:
        outputs = resolve_outputs(
            "/proj", values={"log_directory": "'LOGS2'", "star_history_name": '"h.data"'}
        )
        self.assertEqual(outputs.log_dir, "/proj/LOGS2")
        self.assertEqual(outputs.history_path, "/proj/LOGS2/h.data")


class ResolveFromProjectFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-out-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = pathlib.Path(self.tmp) / "proj"
        self.project.mkdir()

    def _write(self, name: str, text: str) -> None:
        (self.project / name).write_text(text, encoding="utf-8")

    def test_reads_inlist_chain(self) -> None:
        self._write(
            "inlist",
            "&star_job\n"
            "  read_extra_star_job_inlist(1) = .true.\n"
            "  extra_star_job_inlist_name(1) = 'inlist_project'\n"
            "/\n"
            "&controls\n"
            "  read_extra_controls_inlist(1) = .true.\n"
            "  extra_controls_inlist_name(1) = 'inlist_extra'\n"
            "/\n"
            "&pgstar\n"
            "  read_extra_pgstar_inlist(1) = .true.\n"
            "  extra_pgstar_inlist_name(1) = 'inlist_pgstar'\n"
            "/\n",
        )
        self._write("inlist_extra", "&controls\n  log_directory = 'OUT'\n/\n")
        self._write("inlist_pgstar", "&pgstar\n  HR_file_flag = .true.\n  HR_file_interval = 2\n/\n")

        outputs = resolve_outputs(str(self.project))

        self.assertEqual(outputs.log_dir, str(self.project / "OUT"))
        self.assertTrue(outputs.pgstar_files_enabled)
        self.assertEqual(outputs.pgstar_file_interval, 2)

    def test_missing_project_directory_is_tolerated(self) -> None:
        outputs = resolve_outputs(str(self.project / "does_not_exist"))
        self.assertEqual(outputs.log_dir, str(self.project / "does_not_exist" / "LOGS"))

    def test_project_without_inlists_uses_defaults(self) -> None:
        outputs = resolve_outputs(str(self.project))
        self.assertEqual(outputs.history_path, str(self.project / "LOGS" / "history.data"))

    def test_broken_inlist_is_tolerated(self) -> None:
        self._write("inlist", "&controls\n  log_directory =\n/\n\x00\x01")
        outputs = resolve_outputs(str(self.project))
        self.assertTrue(outputs.log_dir.endswith("LOGS"))


class RealProjectConventions(unittest.TestCase):
    """用真实 MESA 项目目录核对（目录不存在时跳过）。"""

    def setUp(self) -> None:
        if not (REAL_PROJECT / "inlist").is_file():
            self.skipTest("缺少真实 MESA 项目（~/MESA_program/pgstar_test）")

    def test_real_project_resolves_to_logs_and_photos(self) -> None:
        outputs = resolve_outputs(str(REAL_PROJECT))

        self.assertEqual(outputs.log_dir, str(REAL_PROJECT / "LOGS"))
        self.assertTrue(pathlib.Path(outputs.history_path).is_file())
        self.assertEqual(outputs.photo_dir, str(REAL_PROJECT / "photos"))
        self.assertTrue(pathlib.Path(outputs.photo_dir).is_dir())

    def test_real_project_pgstar_prefix_matches_mesa_default(self) -> None:
        outputs = resolve_outputs(str(REAL_PROJECT))
        self.assertEqual(outputs.pgstar_prefix, "hr")


class RealCustomDirProject(unittest.TestCase):
    """真实项目把三个目录都改名后的核对（手工构造的项目，存在才跑）。"""

    PROJECT = pathlib.Path.home() / "MESA_program" / "custom_dirs"

    def setUp(self) -> None:
        if not (self.PROJECT / "MYLOGS" / "history.data").is_file():
            self.skipTest("缺少 custom_dirs 真实项目（MYLOGS/SNAPS/PLOTS）")

    def test_custom_directories_are_resolved(self) -> None:
        outputs = resolve_outputs(str(self.PROJECT))

        self.assertEqual(outputs.log_dir, str(self.PROJECT / "MYLOGS"))
        self.assertEqual(outputs.photo_dir, str(self.PROJECT / "SNAPS"))
        self.assertEqual(outputs.png_dir, str(self.PROJECT / "PLOTS"))

    def test_pgstar_file_output_settings_are_detected(self) -> None:
        outputs = resolve_outputs(str(self.PROJECT))
        self.assertTrue(outputs.pgstar_files_enabled)
        self.assertEqual(outputs.pgstar_file_interval, 1)
        self.assertEqual(outputs.pgstar_prefix, "hr")

    def test_existing_photos_from_custom_dir(self) -> None:
        outputs = resolve_outputs(str(self.PROJECT))
        self.assertTrue(outputs.existing_photos(), "SNAPS/ 里应有真实快照")


class MesaOutputsValueObject(unittest.TestCase):
    def test_is_frozen(self) -> None:
        outputs = MesaOutputs(log_dir="/a", history_path="/a/h", index_path="/a/i",
                              photo_dir="/p", png_dir="/g", pgstar_prefix="hr",
                              profile_prefix="profile", pgstar_files_enabled=False,
                              pgstar_file_interval=None, photo_interval=None)
        with self.assertRaises(Exception):
            outputs.log_dir = "/b"  # type: ignore[misc]

    def test_existing_photos_lists_snapshots_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photos = pathlib.Path(tmp) / "photos"
            photos.mkdir()
            for name in ("x208", "x10", "x100"):
                (photos / name).write_bytes(b"x")
            outputs = MesaOutputs(
                log_dir=str(pathlib.Path(tmp) / "LOGS"),
                history_path="", index_path="", photo_dir=str(photos),
                png_dir="", pgstar_prefix="hr", profile_prefix="profile",
                pgstar_files_enabled=False, pgstar_file_interval=None,
                photo_interval=None,
            )
            self.assertEqual(outputs.existing_photos(), ["x10", "x100", "x208"])

    def test_existing_photos_missing_dir_is_empty(self) -> None:
        outputs = MesaOutputs(log_dir="/nope", history_path="", index_path="",
                              photo_dir="/definitely/not/here", png_dir="",
                              pgstar_prefix="hr", profile_prefix="profile",
                              pgstar_files_enabled=False,
                              pgstar_file_interval=None, photo_interval=None)
        self.assertEqual(outputs.existing_photos(), [])


if __name__ == "__main__":
    unittest.main()
