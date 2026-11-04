# 依赖下载：MESA 与 MESA SDK

> **本仓库不包含 MESA 源码，也不包含 MESA SDK。** 它们体积大（MESA 约 2 GB），
> 且应始终从官方渠道获取以保证完整性与许可合规。

MESA IDE 本身可以在没有 MESA 的机器上启动、浏览项目、编辑 inlist；只有**编译与
运行** MESA 项目时才需要下面两个归档，编译一次即可长期使用。

## 1. MESA 源码

| 项目 | 说明 |
|---|---|
| 官方发布页 | <https://doi.org/10.5281/zenodo.2602941>（Zenodo 上的 MESA releases，含历史版本） |
| 官方文档 | <https://docs.mesastar.org/> |
| 本项目验证版本 | **MESA 24.08.1**，归档名 `mesa-24.08.1.zip` |
| 大小 / 解压后 | 约 2.1 GB / 解压并编译后建议预留 20 GB 以上 |
| 校验（24.08.1） | `bd4a18c6f166c33de093f123960cc9805caf3ac23878cebfaba8baedda6818d6` |

在发布页选择 **24.08.1** 对应的 zip 下载；其他版本（如 26.x）理论可用，但参数库
`mesa_data.db` 与部分默认值按 24.08.1 校对过。

## 2. MESA SDK

| 项目 | 说明 |
|---|---|
| 官方页面 | <https://user.astro.wisc.edu/~townsend/static.php?ref=mesasdk> |
| 本项目验证版本 | **MESA SDK 24.7.1**，归档名 `mesasdk-x86_64-linux-24.7.1.tar.gz` |
| 校验（24.7.1, linux x86_64） | `a3705f208ec6a481a4168465662f5571d96c90a0762e07219afa92b2028fd5a0` |

SDK 自带 `gfortran`、`pgplot`、`ffmpeg` 等 MESA 需要的工具链。按你的发行版选择
对应的 `x86_64-linux` 包（macOS 另有 `x86_64-macos` / `arm64-macos`）。

## 3. 放置方式

安装器会在以下位置自动查找归档（不区分顺序，找到即用）：

```
~/mesa/                     ← 推荐：把两个归档都放这里
~/Downloads/
~/
任意目录（用 --archives /path/to/dir 指定）
```

例如：

```bash
mkdir -p ~/mesa
cp /mnt/d/downloads/mesa-24.08.1.zip              ~/mesa/
cp /mnt/d/downloads/mesasdk-x86_64-linux-24.7.1.tar.gz ~/mesa/

cd ~/MESA-IDE-Console
bash install.sh --yes            # 会自动解压 SDK、解压源码、执行 ./install
```

安装完成后会生成 `IDE/mesa_env.sh`（含 `MESA_DIR`、`MESASDK_ROOT`、`PATH`），
并在 `~/.bashrc` 写入一个标记块；`./IDE/run_mesa.sh` 会加载它。

## 4. 手动安装（不使用安装器）

```bash
tar -xzf mesasdk-x86_64-linux-24.7.1.tar.gz -C ~/        # → ~/mesasdk
unzip -q mesa-24.08.1.zip -d ~/mesa                      # → ~/mesa/mesa-24.08.1

export MESASDK_ROOT=~/mesasdk
source $MESASDK_ROOT/bin/mesasdk_init.sh
export MESA_DIR=~/mesa/mesa-24.08.1
export OMP_NUM_THREADS=2

cd $MESA_DIR && ./install        # 约 15–40 分钟
```

MESA 官方安装文档：<https://docs.mesastar.org/en/latest/installation.html>

## 5. 常见问题

| 现象 | 处理 |
|---|---|
| 提示 `~/mesa` 不可写 | 归档曾被 `sudo` 复制进来，属主成了 root：`sudo chown -R "$(id -un):$(id -gn)" ~/mesa` |
| MESA 编译失败 | 看 `IDE/mesa_install.log` 与 `$MESA_DIR/build.log`；常见原因是磁盘不足或缺系统包 |
| `pip` 下载慢 | `MESA_IDE_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash install.sh --yes` |
| 校验归档完整性 | `sha256sum mesa-24.08.1.zip mesasdk-x86_64-linux-24.7.1.tar.gz` |

## 6. 许可提醒

MESA 与其 SDK 有各自的许可条款，使用与再分发请遵守官方说明。本仓库仅提供
安装与集成代码，不重新分发这些归档。
