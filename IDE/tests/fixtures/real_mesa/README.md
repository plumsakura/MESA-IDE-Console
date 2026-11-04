# 真实 MESA 输出样本（回归夹具）

本目录是从**真实 MESA 运行**里截取的原样文件，用于锁定"真实格式"，防止再次出现
"夹具是合成近似、真实数据解析失败"的问题。

## 来源

- 生成环境：MESA **r24.08.1** + MESA SDK **x86_64-linux-24.7.1**（gfortran 13.3.0），
  在 WSL2 上编译（`./install` 全绿）。
- 项目：`star/work` 模板复制而来，`initial_mass = 1.0`、`max_model_number = 20`、
  `photo_interval = 5`，pgstar 以 `file_device='png'` 输出。
- 取文件：`LOGS/history.data`（11 行，**完整原样**）、`LOGS/profiles.index`（**完整原样**）、
  `LOGS/profile2.data`（**仅保留前 11 行**：6 行表头/列名 + 5 行真实数据；
  原文 706 行，格式逐字保留）。

## 真实格式要点（与早期合成夹具不同！）

```
history.data / profile<N>.data
  第 1 行  序号行（表头项数 N）
  第 2 行  表头名字行        version_number compiler build MESA_SDK_version ...
  第 3 行  表头值行          "r24.08.1" "gfortran" "13.3.0" ...
  第 4 行  （空行）
  第 5 行  序号行（数据列数 M）
  第 6 行  数据列名行        model_number num_zones star_age ...
  第 7 行起 数据行
```

- MESA 在 `history.f90` 里虽然写三帧表头，但 pass 3 会以 `status='replace'`
  **重开文件**，所以最终文件里只有**一帧**表头 + 一段序号/列名；
- 表头值里既有字符串（带双引号，如 `"r24.08.1"`）也有 E 指数浮点
  （如 `5.0000000000000000E+001`）；`profile*.data` 的数据列里还可能含
  **字符串列**（如 `version_number`）；
- `profiles.index` 第 1 行是说明文字
  （`2 models.  lines hold model number, priority, and profile number.`），
  其后每行是 `模型号 优先级 剖面号`。

## 为什么不能只留合成夹具

`mesa_reader` 0.4.0 用 pandas `read_csv` 且把行号写死（`header_names_line=2`、
`bulk_names_line=6`），它只对**真实**布局成立；而本项目早期的合成夹具是"三帧表头"，
两者互不兼容 —— 这正是真实测试暴露出的问题（详见《重构进度》5.9）。
