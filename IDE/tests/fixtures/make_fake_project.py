"""生成"假 MESA 项目"测试夹具（仅标准库，确定性输出）。

用途：给 :mod:`tests.test_integration_fake_mesa` 提供一份**可重复生成**的
MESA 工作目录，使协议层（``./mk``/``./rn``/``./re``/``./clean``）与
``LOGS/`` 数据抽取可以在**没有真实 MESA** 的机器上端到端验证。

**格式依据（真实源码，非猜测）**：MESA 24.08.1 源码包内
``star/private/history.f90``、``star/private/profile.f90``、
``star/defaults/controls.defaults``、``star/work/{mk,rn,re,clean,inlist}``。
关键事实：

1. ``LOGS/history.data`` / ``profile<N>.data`` 的表头是**三帧**，
   每帧三行 ``序号行 / 名字行 / 值行`` + 一个空行；帧后紧跟"列名行"，
   再是数据行。因此 ``history.data`` 的列名行落在第 13 行。
2. ``star_history_dbl_format = '(1pes40.16e3, 1x)'``
   → 浮点是**右对齐、宽 40、16 位小数、三位指数的 Fortran D 指数**
   （``1.2345678901234567D+06``）；整数是 ``(i40, 1x)``；字符串是
   ``(a40, 1x)`` 且值带双引号。
3. ``./mk`` = ``cd make; make``；``./rn`` = ``rm -f restart_photo; ./star``；
   ``./re [photo]`` 从 ``photos/`` 取快照（无参数=最近一个）复制成
   ``restart_photo`` 后跑 ``./star``；``./clean`` = ``cd make; make clean``。

本夹具的桩脚本**保留上述语义**（含 ``photos/`` 与 ``make/``），但不做任何
编译；数值是**合成的**（非真实恒星模型），结构与量级与真实输出一致。

重新生成（非必需，仅用于审计/复现）::

    cd IDE && venv/bin/python tests/fixtures/make_fake_project.py
"""

from __future__ import annotations

import math
import shutil
import os
import pathlib
from typing import Sequence

FIXTURE_NAME = "fake_mesa_project"

HISTORY_MODELS = 40
PROFILE_ZONES = 61

HISTORY_COLUMNS: tuple[str, ...] = (
    "model_number",
    "star_age",
    "log_Teff",
    "log_L",
    "log_R",
    "log_center_T",
    "log_center_Rho",
)

#: 剖面数据列（MESA 的 ``profile_columns.list`` 决定；本层只支持数值列 ——
#: 若用户把 version_number 这类**字符串列**加进 profile_columns.list，
#: ``core.mesa.reader`` 会明确报错而不是静默产出错数据）
PROFILE_COLUMNS: tuple[str, ...] = (
    "zone",
    "mass",
    "logR",
    "logT",
    "logRho",
    "logP",
    "x_mass_fraction_H",
    "y_mass_fraction_He",
)

#: 与 controls.defaults 的 star_history_int_format / profile_int_format 一致
INT_WIDTH = 40
#: 与 star_history_dbl_format / profile_dbl_format = '(1pes40.16e3, 1x)' 一致
DBL_WIDTH = 40
DBL_PRECISION = 16
#: 与 *_txt_format = '(a40, 1x)' 一致
TXT_WIDTH = 40


# ---------------------------------------------------------------------------
# 合成物理量（确定性；只求"结构合理、单调、量级正确"）
# ---------------------------------------------------------------------------

def _history_rows(models: int = HISTORY_MODELS) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    age = 0.0
    for index in range(models):
        model = (index + 1) * 10
        if index:
            age += 1.0e6 * (1.0 + 0.12 * index) ** 1.7
        # 主序缓慢冷却 → 亚巨星/红巨星加速冷却
        log_teff = 3.76 - 0.0016 * index - 0.00012 * index * index
        # 主序缓慢增亮 → 巨星阶段暴涨
        log_l = 0.02 * index + 0.0012 * index * index
        log_r = 0.5 * (log_l - 4.0 * (log_teff - 3.76))
        rows.append(
            {
                "model_number": float(model),
                "star_age": age,
                "log_Teff": log_teff,
                "log_L": log_l,
                "log_R": log_r,
                "log_center_T": 7.05 + 0.004 * index,
                "log_center_Rho": 1.95 + 0.02 * index,
            }
        )
    return rows


def _profile_rows(zones: int, center_logt: float, center_logrho: float,
                  surface_logt: float, surface_logrho: float) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for zone in range(1, zones + 1):
        x = (zone - 1) / (zones - 1)  # 0 = 中心, 1 = 表面
        log_t = surface_logt + (center_logt - surface_logt) * math.exp(-4.5 * x)
        log_rho = surface_logrho + (center_logrho - surface_logrho) * math.exp(-9.0 * x)
        rows.append(
            {
                "zone": float(zone),
                "mass": 1.0 - (x ** 3),
                "logR": math.log10(0.02 + 0.98 * (x ** 2.5)),
                "logRho": log_rho,
                "logT": log_t,
                "logP": log_rho + log_t - 10.0,
                "x_mass_fraction_H": 0.70 + 0.02 * x,
                "y_mass_fraction_He": 0.28 - 0.02 * x,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# MESA 文本格式写出（与 Fortran 格式串逐字对应）
# ---------------------------------------------------------------------------

def _write_int(value: float | int) -> str:
    return f"{int(round(value)):>{INT_WIDTH}d} "


def _write_dbl(value: float) -> str:
    """复刻 ``'(1pes40.16e3, 1x)'``：右对齐 40 宽、16 位小数、三位指数。

    真实 MESA 输出用 **E** 指数（``1.0000000000000001E-005``）。
    """
    mantissa, exponent = f"{value:>{DBL_WIDTH - 11}.{DBL_PRECISION}e}".split("e")
    return f"{mantissa}E{int(exponent):+03d} "


def _write_txt(value: str) -> str:
    return f"{value:>{TXT_WIDTH}s} "


def _is_int_column(column: str) -> bool:
    return column in {"model_number", "zone", "num_zones"}


def _write_row(columns: Sequence[str], row: dict[str, float]) -> str:
    """按列类型写一行数据（整数列 ``i40``，其余 ``es40.16e3``）。"""
    cells = []
    for name in columns:
        value = row[name]
        cells.append(_write_int(value) if _is_int_column(name) else _write_dbl(value))
    return "".join(cells)


def _write_value(token: str) -> str:
    """表头值：带引号的字符串用 ``a40``，其余用 ``i40``/``es40.16e3``。"""
    stripped = token.strip()
    if stripped.startswith(("'", '"')):
        return _write_txt(stripped)
    try:
        number = float(stripped.replace("D", "e").replace("d", "e"))
    except ValueError:
        return _write_txt(stripped)
    if stripped.lstrip("+-").isdigit():
        return _write_int(number)
    return _write_dbl(number)


def _write_mesa_file(
    header_names: Sequence[str],
    header_values: Sequence[str],
    columns: Sequence[str],
    rows: Sequence[dict[str, float]],
) -> str:
    """按**真实 MESA 布局**写数据文件。

    ::

        序号行(表头项) / 表头名字行 / 表头值行 / 空行
        序号行(数据列) / 数据列名行 / 数据行...

    ``history.f90`` 虽然写三帧表头，但 pass 3 会以 ``status='replace'`` 重开文件，
    最终只有一帧（见 ``tests/fixtures/real_mesa/README.md``）。
    """
    parts = [
        " ".join(_write_int(position) for position in range(1, len(header_names) + 1)),
        " ".join(_write_txt(name) for name in header_names),
        " ".join(_write_value(value) for value in header_values).rstrip(),
        "",
        " ".join(_write_int(position) for position in range(1, len(columns) + 1)),
        " ".join(_write_txt(name) for name in columns),
    ]
    parts.extend(_write_row(columns, row).rstrip() for row in rows)
    return "\n".join(parts) + "\n"


INLIST = """! This is the first inlist file that MESA reads when it starts.

&star_job
    read_extra_star_job_inlist(1) = .true.
    extra_star_job_inlist_name(1) = 'inlist_project'
/ ! end of star_job namelist

&eos
    read_extra_eos_inlist(1) = .true.
    extra_eos_inlist_name(1) = 'inlist_project'
/ ! end of eos namelist

&kap
    read_extra_kap_inlist(1) = .true.
    extra_kap_inlist_name(1) = 'inlist_project'
/ ! end of kap namelist

&controls
    read_extra_controls_inlist(1) = .true.
    extra_controls_inlist_name(1) = 'inlist_project'
/ ! end of controls namelist

&pgstar
    read_extra_pgstar_inlist(1) = .true.
    extra_pgstar_inlist_name(1) = 'inlist_pgstar'
/ ! end of pgstar namelist
"""

INLIST_PROJECT = """&star_job
    pgstar_flag = .true.
/

&controls
    initial_mass = 1.0d0
    initial_z = 0.02d0
    max_age = 1.0d10
/
"""

INLIST_PGSTAR = """&pgstar
    file_device = 'png'
    pgstar_interval = 100
    HR_win_flag = .true.
/

&pgstar_HR
    HR_logT_min = 3.4d0
    HR_logT_max = 3.9d0
/
"""

MAKEFILE = """# 假 MESA 桩 makefile：只生成 ./star（真实 MESA 在这里编译）
all: star

star:
	@printf '#!/bin/bash\\necho "fake-star: ran (cwd=$(pwd))"\\n' > ../star
	@chmod +x ../star

clean:
	@rm -f ../star
	@echo "fake-make: cleaned"
"""

MK_SCRIPT = """#!/bin/bash
# 假 MESA 桩脚本，语义与真实 star/work/mk 相同：cd make; make
# 额外记录调用并可制造失败（MESA_STUB_FAIL=mk）。绝不接触真实 MESA。
set -u
here="$(cd "$(dirname "$0")" && pwd)"
artifacts="${MESA_STUB_ARTIFACTS:-$(dirname "$here")/fake_mesa_build}"
mkdir -p "$artifacts"
{
  printf 'mk'
  for arg in "$@"; do printf ' %s' "$arg"; done
  printf '\\n'
} >> "$artifacts/invocations.log"
if [ "${MESA_STUB_FAIL:-}" = "mk" ]; then
  echo "mk: 桩脚本按 MESA_STUB_FAIL 失败" >&2
  exit 7
fi
cd "$here/make" || exit 1
make
"""

RN_SCRIPT = """#!/bin/bash
# 假 MESA 桩脚本，语义与真实 star/work/rn 相同：
#   1) rm -f restart_photo  2) 跑 ./star（此处改为追加模型数据的桩）
set -u
here="$(cd "$(dirname "$0")" && pwd)"
artifacts="${MESA_STUB_ARTIFACTS:-$(dirname "$here")/fake_mesa_build}"
mkdir -p "$artifacts"
{
  printf 'rn'
  for arg in "$@"; do printf ' %s' "$arg"; done
  printf '\\n'
} >> "$artifacts/invocations.log"
rm -f "$here/restart_photo"
if [ "${MESA_STUB_FAIL:-}" = "rn" ]; then
  echo "rn: 桩脚本按 MESA_STUB_FAIL 失败" >&2
  exit 3
fi
if [ ! -x "$here/star" ]; then
  echo "rn: ./star 不存在，请先运行 ./mk 编译" >&2
  exit 4
fi
"$here/star"
export FAKE_PROJECT_DIR="$here"
exec "${FAKE_PYTHON:-python3}" "$here/append_model.py"
"""

RE_SCRIPT = """#!/bin/bash
# 假 MESA 桩脚本，语义与真实 star/work/re 相同：
#   快照名是**位置参数**（无参数=photos/ 里最近的一个），复制成 restart_photo。
set -u
here="$(cd "$(dirname "$0")" && pwd)"
artifacts="${MESA_STUB_ARTIFACTS:-$(dirname "$here")/fake_mesa_build}"
mkdir -p "$artifacts"
{
  printf 're'
  for arg in "$@"; do printf ' %s' "$arg"; done
  printf '\\n'
} >> "$artifacts/invocations.log"

photo_directory="$here/photos"
if [ "$#" -eq 0 ]; then
  photo="$(ls -tp "$photo_directory" 2>/dev/null | grep -v / | head -1)"
else
  photo="$1"
fi
if [ -z "$photo" ] || [ ! -f "$photo_directory/$photo" ]; then
  echo "specified photo ($photo) does not exist" >&2
  exit 1
fi
echo "restart from $photo"
cp "$photo_directory/$photo" "$here/restart_photo" || exit 1
"""

CLEAN_SCRIPT = """#!/bin/bash
# 假 MESA 桩脚本，语义与真实 star/work/clean 相同：cd make; make clean
set -u
here="$(cd "$(dirname "$0")" && pwd)"
artifacts="${MESA_STUB_ARTIFACTS:-$(dirname "$here")/fake_mesa_build}"
mkdir -p "$artifacts"
printf 'clean\\n' >> "$artifacts/invocations.log"
cd "$here/make" || exit 1
make clean
"""

APPEND_MODEL = '''"""被桩脚本 ``rn`` 调用：模拟 MESA 的 ``./star`` 追加一个模型与一份剖面。

复用夹具生成器的写出函数，保证"运行产生的新数据"与初始数据格式完全一致
（真实布局：单帧表头 + 数据列序号行）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_fake_project import (  # noqa: E402
    HISTORY_COLUMNS,
    PROFILE_COLUMNS,
    PROFILE_ZONES,
    _profile_rows,
    _write_mesa_file,
    profile_header_names,
    profile_header_values,
)

project = os.environ["FAKE_PROJECT_DIR"]
logs = os.path.join(project, "LOGS")
history_path = os.path.join(logs, "history.data")

with open(history_path, encoding="utf-8") as handle:
    lines = handle.readlines()

header_names = lines[1].split()
header_values = lines[2].split()
columns_line = next(
    index for index, line in enumerate(lines) if line.split() == list(HISTORY_COLUMNS)
)
rows = []
for line in lines[columns_line + 1:]:
    tokens = line.split()
    if len(tokens) != len(HISTORY_COLUMNS):
        continue
    rows.append(
        {
            name: float(token.replace("E", "e"))
            for name, token in zip(HISTORY_COLUMNS, tokens)
        }
    )

last = rows[-1]
new_model = int(last["model_number"]) + 10
new_teff = last["log_Teff"] - 0.02
new_l = 0.02 * (new_model / 10.0)
rows.append(
    {
        "model_number": float(new_model),
        "star_age": last["star_age"] + 7.0e7,
        "log_Teff": new_teff,
        "log_L": new_l,
        "log_R": 0.5 * (new_l - 4.0 * (new_teff - 3.76)),
        "log_center_T": 7.25,
        "log_center_Rho": 2.75,
    }
)
with open(history_path, "w", encoding="utf-8") as handle:
    handle.write(_write_mesa_file(header_names, header_values, HISTORY_COLUMNS, rows))

with open(os.path.join(logs, "profiles.index"), encoding="utf-8") as handle:
    index_lines = [line for line in handle if line.strip()]
profile_number = len(index_lines)  # 首行是说明文字
with open(os.path.join(logs, "profiles.index"), "a", encoding="utf-8") as handle:
    handle.write(f"{new_model:8d} {0:8d} {profile_number:8d}\\n")

with open(
    os.path.join(logs, f"profile{profile_number}.data"), "w", encoding="utf-8"
) as handle:
    handle.write(
        _write_mesa_file(
            profile_header_names(),
            profile_header_values(new_model),
            PROFILE_COLUMNS,
            _profile_rows(PROFILE_ZONES, 7.28, 2.75, 3.55, -7.5),
        )
    )

print(f"fake-star: appended model {new_model} (profile {profile_number})")
'''

HISTORY_HEADER_NAMES: tuple[str, ...] = (
    "version_number",
    "compiler",
    "build",
    "MESA_SDK_version",
    "math_backend",
    "date",
    "burn_min1",
    "burn_min2",
    "msun",
    "rsun",
    "lsun",
)

HISTORY_HEADER_VALUES: tuple[str, ...] = (
    "''",
    "'gfortran'",
    "'fake_mesa_24.08.1'",
    "'x86_64-linux-24.7.1'",
    "'openblas'",
    "'2026-01-01'",
    "5.0000000000000000D+01",
    "1.0000000000000000D+07",
    "1.9884098706980512D+33",
    "6.9570000000000000D+10",
    "3.8280000000000000D+33",
)

#: 剖面表头项（与 ``profile_columns.list`` 的 ``zone`` + ``profile.f90`` 写出的
#: 头项对齐；末项 ``version_number`` 是字符串，用于覆盖字符串表头值的解析）
PROFILE_HEADER_NAMES: tuple[str, ...] = (
    "zone",
    "model_number",
    "num_zones",
    "initial_mass",
    "initial_z",
    "star_age",
    "version_number",
)

#: (剖面号, 模型号, 中心 logT, 中心 logRho, 表面 logT, 表面 logRho)
PROFILE_SPECS: tuple[tuple[int, int, float, float, float, float], ...] = (
    (1, 10, 7.05, 1.95, 3.62, -7.0),
    (2, 20, 6.98, 1.05, 3.57, -7.2),
    (3, 30, 7.10, 2.35, 3.55, -7.6),
)

#: ``LOGS/profiles.index`` 每行 ``模型号 优先级 剖面号``
INDEX_ROWS: tuple[tuple[int, int], ...] = ((10, 1), (20, 2), (30, 3))


def profile_header_names(columns: Sequence[str] = PROFILE_COLUMNS) -> tuple[str, ...]:
    """剖面表头项：``profile.f90`` 的固定头项 + 可选的 ``zone`` 列头项。

    真实 MESA 里 ``zone`` 同时是 ``profile_columns.list`` 的列与表头项，
    因此表头项数 == 数据列数；本函数保证同样的不变式。
    """
    names = tuple(name for name in PROFILE_HEADER_NAMES if name != "zone")
    if "zone" in columns:
        names = ("zone",) + names
    return names


#: 表头项 → 值（剖面）
def profile_header_values(model: int) -> tuple[str, ...]:
    table = {
        "zone": str(PROFILE_ZONES),
        "model_number": str(model),
        "num_zones": str(PROFILE_ZONES),
        "initial_mass": "1.0000000000000000D+00",
        "initial_z": "2.0000000000000000D-02",
        "star_age": "1.0000000000000000D+07",
        "version_number": "''",
    }
    return tuple(table[name] for name in profile_header_names())


def _history_text() -> str:
    return _write_mesa_file(
        HISTORY_HEADER_NAMES, HISTORY_HEADER_VALUES, HISTORY_COLUMNS, _history_rows()
    )


def _profile_text(number: int, model: int, c_t: float, c_rho: float,
                  s_t: float, s_rho: float) -> str:
    return _write_mesa_file(
        profile_header_names(),
        profile_header_values(model),
        PROFILE_COLUMNS,
        _profile_rows(PROFILE_ZONES, c_t, c_rho, s_t, s_rho),
    )


def write_fake_project(root: str | os.PathLike[str]) -> pathlib.Path:
    """把完整夹具写入 ``root`` 并返回该目录（已存在的内容会被覆盖）。"""
    base = pathlib.Path(root)
    logs = base / "LOGS"
    logs.mkdir(parents=True, exist_ok=True)
    (base / "png").mkdir(parents=True, exist_ok=True)
    (base / "make").mkdir(parents=True, exist_ok=True)
    (base / "photos").mkdir(parents=True, exist_ok=True)

    for name, text in (
        ("inlist", INLIST),
        ("inlist_pgstar", INLIST_PGSTAR),
        ("inlist_project", INLIST_PROJECT),
        ("mk", MK_SCRIPT),
        ("rn", RN_SCRIPT),
        ("re", RE_SCRIPT),
        ("clean", CLEAN_SCRIPT),
        ("append_model.py", APPEND_MODEL),
        (os.path.join("make", "makefile"), MAKEFILE),
    ):
        (base / name).write_text(text, encoding="utf-8")

    for name in ("mk", "rn", "re", "clean"):
        os.chmod(base / name, 0o755)

    # 让夹具自包含（桩脚本 rn 会调用 append_model.py → 复用本生成器的写出函数）
    shutil.copy2(pathlib.Path(__file__), base / pathlib.Path(__file__).name)

    # 一份可被 ./re 使用的快照
    (base / "photos" / "photo1").write_text("fake photo\n", encoding="utf-8")

    (logs / "history.data").write_text(_history_text(), encoding="utf-8")
    for number, model, c_t, c_rho, s_t, s_rho in PROFILE_SPECS:
        (logs / f"profile{number}.data").write_text(
            _profile_text(number, model, c_t, c_rho, s_t, s_rho), encoding="utf-8"
        )
    (logs / "profiles.index").write_text(
        f"{len(INDEX_ROWS)} models.  lines hold model number, priority, "
        "and profile number.\n"
        + "".join(f"{model:8d} {0:8d} {profile:8d}\n" for model, profile in INDEX_ROWS),
        encoding="utf-8",
    )
    return base


def main(argv: Sequence[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    target = (
        pathlib.Path(args[0]) if args else pathlib.Path(__file__).parent / FIXTURE_NAME
    )
    write_fake_project(target)
    print(f"已生成假 MESA 项目夹具: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
