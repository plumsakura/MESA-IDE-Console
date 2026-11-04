"""被桩脚本 ``rn`` 调用：模拟 MESA 的 ``./star`` 追加一个模型与一份剖面。

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
    handle.write(f"{new_model:8d} {0:8d} {profile_number:8d}\n")

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
