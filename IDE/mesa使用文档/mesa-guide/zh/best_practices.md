<!-- 译文：MESA 26.4.1 官方文档 using_mesa/best_practices.html 的中文翻译 -->
<!-- 原文：en/best_practices.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/best_practices.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->

# 最佳实践

## 项目进行期间

当你开始一个新项目时，通常应当使用最新的
MESA 发行版。除非你遇到会对工作造成负面影响的
bug，否则请在整个项目中一直使用该版本。如果你是从一套
为较旧版本设计的输入文件开始，我们
建议你花些时间把它们移植到最新版本，因为一旦你
遇到任何问题，这样会让社区更
容易帮助你。

在修改主 MESA 目录中的任何源代码之前，请先检查
这些改动是否无法在你的 work 文件夹中利用 MESA 提供的
[
钩子（hooks）
](extending_mesa.html#extending-mesa) 在本地实现。如果你有某个
无法用所提供的这组钩子完成的用例，你可以
随时联系我们，请求新增一个钩子。

MESA 测试套件（``star/test_suite`` 和 ``binary/test_suite``）是
宝贵的示例来源，也是在用 MESA 建立新
问题时很好的第一站。查看测试套件的 inlist 是快速
熟悉与你问题相关的那组选项的方法。
更多信息见[
如何把一个测试套件用例用作你自己 work 目录的起点
](../test_suite.html#test-suite)。

你始终应当进行某种收敛性研究，以确保
你的结果不敏感于模型的时间分辨率或质量分辨率。
请注意，这一点非常重要：MESA 的默认值
通常不会对你的特定科学问题而言是最优的，甚至可能是不可接受的。
确保所选的 MESA 选项和 controls 适合
你想要研究的物理，是用户自己的责任。
这通常需要对所得模型进行适当的测试和批判性分析。

在整个项目过程中，寻求社区帮助和
意见的最佳方式是给 ``mesa-users@lists.mesastar.org`` 邮件列表发消息。

## 一个示例

我们将使用测试套件用例[
semiconvection
](../test_suite/semiconvection.html#semiconvection)。
先进入你进行 MESA 工作的目录。

```
cp -r $MESA_DIR/star/test_suite/semiconvection .
```

在旧的 MESA 修订版中，test_suite 里有硬编码的引用，用于设置变量 ``MESA_DIR` `=` `../../../..``  。
这种做法在当前修订版中已被移除。如果你正用旧版 MESA 运行本教程，请把那一行在
makefile、``rn`` 脚本、``ck`` 脚本以及 ``inlist_semiconvection_header`` 中注释掉或删除。如果你使用的是 r23.05.1 之后的任何 MESA 修订版，请忽略这条说明并继续阅读。

现在清理该目录，

```
./clean
```

构建可执行文件，

```
./mk
```

然后运行可执行文件

```
./rn
```

几分钟后运行会终止，你应当看到

```
stop because have dropped below central lower limit for h1
    0.3994694345E+00    0.4000000000E+00

        322   7.308040   6658.804   0.741142   0.741142   1.500000   1.500000   0.399469   0.007663   0.280000  -2.316624   1653      0
   6.698970   7.308040   0.246241 -37.781812  -0.571349 -99.000000   0.000000   0.580264   0.004769   0.020000   0.076565      5
 1.2920E+09   2.005522   0.740760  -5.854865 -41.276481  -7.412372   0.000000   0.000042   0.002098   0.020266  0.000E+00        max_dt
                               rel_E_err    1.0067953870393901D-12
                       log_rel_run_E_err      -10.0905601615909450

save LOGS/profile8.data for model 322
save photos/x322 for model 322
 saved to final.mod
termination code: xa_central_lower_limit

                 runtime (minutes), retries, steps        4.92         0       322

                              mixing type at 0.125 Msun    1.0000000000000000D+00    1.0000000000000000D+00    1.0000000000000000D+00
                              mixing type at 0.135 Msun    3.0000000000000000D+00    3.0000000000000000D+00    3.0000000000000000D+00
                              mixing type at 0.145 Msun    0.0000000000000000D+00    0.0000000000000000D+00    0.0000000000000000D+00
                                                   logT    7.2062697504202102D+00    7.1500000000000004D+00    7.3099999999999996D+00
                                                 logRho    1.7886843044807488D+00    1.7500000000000000D+00    1.8000000000000000D+00

all values are within tolerances
```

让我们添加一些 pgstar 绘图，以便可视化正在发生的情况。
有三个文件需要编辑。
首先，把默认的 ``history_columns.list`` 复制到你的 work 目录

```
cp $MESA_DIR/star/defaults/history_columns.list .
```

然后修改你本地的 ``history_columns.list``

-
添加

```
mixing_regions 20
burning_regions 20
```

-
修改

```
!log_center_T ! temperature
!log_center_Rho ! density
```

改为

```
log_center_T ! temperature
log_center_Rho ! density
```

并保存文件修改。

其次，修改 ``inlist_semiconvection_header``：

-
修改

```
!read_extra_pgstar_inlist(1) = .true.
!extra_pgstar_inlist_name(1)= 'inlist_semiconvection'
```

改为

```
read_extra_pgstar_inlist(1) = .true.
extra_pgstar_inlist_name(1)= 'inlist_semiconvection'
```

并保存文件修改。

第三，修改 ``inlist_semiconvection``，把 pgstar namelist 改为

-
在 ``star_job`` namelist 中添加：

```
pgstar_flag = .true.
save_pgstar_files_when_terminate = .true.
```

-
并且，为了让停止条件更精确，在 ``controls`` namelist 中添加：

```
when_to_stop_rtol = 1e-4
when_to_stop_atol = 1e-4
```

-
最后，把 ``pgstar`` namelist 替换为

```
&pgstar

    pgstar_interval = 1

    Grid4_win_flag = .true.
    Grid4_win_width = 8
    Kipp_mass_max = 0.2 ! (Msun units) negative means use default
    Kipp_show_mixing = .true.
    Kipp_show_burn = .false.
    Kipp_show_luminosities = .true.
    Kipp_show_mass_boundaries = .false.

    Grid4_file_flag = .true.
    Grid4_file_dir = 'pgstar_out'
    Grid4_file_prefix = 'grid4_'
    Grid4_file_interval = 10
    Grid4_file_width = -1
    Grid4_file_aspect_ratio = -1

/ ! end of pgstar namelist
```

并保存文件修改。

现在再次运行可执行文件

```
./rn
```

你应当会看到屏幕上出现一个 pgstar 窗口：

[![../_images/grid4_000322.svg]
](../_images/grid4_000322.svg)

## 探索物理变化

对你的 ``inlist_semiconvection`` 做以下修改：

-
修改

```
max_model_number = 1000
```

改为

```
max_model_number = 40000
```

-
并把

```
history_interval = 10
```

改为

```
history_interval = 1
```

### 试验反应网络

改变核反应网络
``new_net_name`` = ``pp_and_cno_extras.net``（本测试套件用例）、``basic.net``（默认）、``approx21.net`` 和 ``mesa_49.net``。

-
在一次运行结束时，所有报告的值是否仍在各自的容差范围内？

-
对流核心质量增长、HR 图（赫罗图）和最终氢丰度剖面的结果是否相同？

-
为什么结果相同或不同？

注意

对于 2021 年 MESA 暑期学校，每张桌子都应完成全部 4 个反应网络。机器最快的参与者应当做更大的网络。

检查 history 和 profile 中的物理量通常是有用的。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_network_name'``，其中 NN 是你的桌号，network_name 是上面的选项之一，
例如 ``log_directory` `=` `'Table08_approx21'``。

运行结束后，每张桌子都应把他们的 ``log_directory``
上传到我们共享的 Dropbox 目录 timmes/Experiment01。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把所选的反应网络改回测试用例的值 ``pp_and_cno_extras.net``。

### 试验对流混合长度

改变对流的混合长度
``mixing_length_alpha`` = 1.0 到 3.0，步长 0.1，其中会包含 2.0（默认）和 1.8（本测试套件用例）。
重复回答上面的问题。

注意

对于 2021 年 MESA 暑期学校，每位 TA 会分到一组 4 个值，对应他们桌的每位参与者。
然后由 TA 把这些值分配给团队。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_NpN'``，其中 NN 是你的桌号，NpN 是你的取值，
例如 ``log_directory` `=` `'Table03_1p8'``。

一次运行完成后，每位参与者都应把一个 ``log_directory`` 上传到我们共享的 Dropbox 目录 timmes/Experiment02。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把 ``mixing_length_alpha`` 改回测试用例的值 1.8。

### 试验半对流混合长度

改变半对流混合的尺度
``alpha_semiconvection`` = 0.0 到 0.5，步长 0.02，其中会包含 0.0（默认）和 0.1（本测试套件用例）。
重复回答上面的问题。

注意

对于 2021 年 MESA 暑期学校，每位 TA 会分到一组 4 个值，对应他们桌的每位参与者。
然后由 TA 把这些值分配给团队。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_NpNN'``，其中 NN 是你的桌号，NpNN 是你的取值，
例如 ``log_directory` `=` `'Table11_1p80'``。

一次运行完成后，每位参与者都应把一个 ``log_directory`` 上传到我们共享的 Dropbox 目录 timmes/Experiment03。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把 ``alpha_semiconvection`` 改回测试用例的值 0.1。

## 探索数值收敛性

### 试验质量分辨率 I

改变质量分辨率设置
``max_dq`` = ``5.0e-2``、``2.0e-2``、``1.0e-2``（默认）、``5.0e-3``、``2.0e-3`` 和 ``1.0e-3``。
重复回答上面的问题。

注意

对于 2021 年 MESA 暑期学校，每位 TA 会分到一组 4 个值，对应他们桌的每位参与者。
然后由 TA 把这些值分配给团队。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_NpNNN'``，其中 NN 是你的桌号，NpNNN 是你的取值，
例如 ``log_directory` `=` `'Table05_0p002'``。

一次运行完成后，每位参与者都应把一个 ``log_directory`` 上传到我们共享的 Dropbox 目录 timmes/Experiment04。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把 ``max_dq`` 改回其默认值。

### 试验质量分辨率 II

改变质量分辨率设置
``mesh_delta_coeff`` = 0.2 到 2.0，步长 0.2，其中会包含默认值 1.0。
重复回答上面的问题。

注意

对于 2021 年 MESA 暑期学校，每位 TA 会分到一组 4 个值，对应他们桌的每位参与者。
然后由 TA 把这些值分配给团队。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_NpNNN'``，其中 NN 是你的桌号，NpN 是你的取值，
例如 ``log_directory` `=` `'Table08_1p2'``。

一次运行完成后，每位参与者都应把一个 ``log_directory`` 上传到我们共享的 Dropbox 目录 timmes/Experiment05。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把 ``mesh_delta_coeff`` 改回其默认值 1.0。

### 试验时间分辨率

改变时间分辨率设置
``max_years_for_timestep`` = ``1.0e8``、``5.0e7``、``2.0e7``、``1.0e7``、``5.0e6``、``2.0e6`` 和 ``1.0e6``。
重复回答上面的问题。

注意

对于 2021 年 MESA 暑期学校，每位 TA 会分到一组 4 个值，对应他们桌的每位参与者。
然后由 TA 把这些值分配给团队。

把默认的 control namelist 参数 ``log_directory` `=` `'LOGS'`` 改为更具描述性的
``log_directory` `=` `'TableNN_NeN'``，其中 NN 是你的桌号，NeN 是你的取值，
例如 ``log_directory` `=` `'Table01_2e7'``。

一次运行完成后，每位参与者都应把一个 ``log_directory`` 上传到我们共享的 Dropbox 目录 timmes/Experiment06。

TA 们将绘制我们众筹得来的对流核心质量增长、HR 图和最终氢丰度剖面。

完成后，把 ``max_years_for_timestep`` 改回其默认值 0.0。

## 撰写发表文章

汇总你的科学工作，并把它写成可用于发表的文章。

注意

对于 2021 年 MESA 暑期学校，每张桌子应团队协作撰写一篇不超过 250 词的研究笔记（Research Notes）摘要，
然后上传他们的摘要，文件名为 ``TableNN_abstract.txt``，其中 NN 是你的桌号，例如
``Table10_abstract.txt``，上传到我们共享的 Dropbox 目录 timmes/Abstracts。

## 在文章中

你应当明确说明计算中使用的是哪个版本的 MESA。
我们还建议注明用来编译 MESA 的
MESA SDK 是哪个版本。

### 引用 MESA

你应当引用所使用 MESA 版本发布时所有可获得的 MESA 仪器（instrument）论文，
因为 MESA 是这些工作的总和。目前，
这些论文是：

```
Modules for Experiments in Stellar Astrophysics
\citep[MESA][]{Paxton2011, Paxton2013, Paxton2015, Paxton2018, Paxton2019, Jermyn2023}.
```

MESA 关键性地依赖于许多研究者的辛勤工作，他们
生成了支撑 ``eos``、
``kap``、``net`` 和 ``neu`` 模块的输入微物理数据。因此我们鼓励用户
简要总结这些内容，并附上适当的引用。

```
The MESA EOS is a blend of the OPAL \citep{Rogers2002}, SCVH
\citep{Saumon1995}, FreeEOS \citep{Irwin2004}, HELM \citep{Timmes2000},
PC \citep{Potekhin2010}, and Skye \citep{Jermyn2021} EOSes.

Radiative opacities are primarily from OPAL \citep{Iglesias1993,
Iglesias1996}, with low-temperature data from \citet{Ferguson2005}
and the high-temperature, Compton-scattering dominated regime by
\citet{Poutanen2017}.  Electron conduction opacities are from
\citet{Cassisi2007} and \citet{Blouin2020}.

Nuclear reaction rates are from JINA REACLIB \citep{Cyburt2010}, NACRE \citep{Angulo1999} and
additional tabulated weak reaction rates \citet{Fuller1985, Oda1994,
Langanke2000}.  Screening is included via the prescription of \citet{Chugunov2007}.
Thermal neutrino loss rates are from \citet{Itoh1996}.
```

请注意，这只是总结了当前发布版 MESA 的“默认”能力。
如果你使用了其他
微物理选项、采用了诸如星风质量损失率
之类的方案，或者使用的是较旧版本的 MESA，请查阅文档
以获取合适的参考文献。

在 MESA 双星（binary）模块中，默认情况下：

```
Roche lobe radii in binary systems are computed using the fit of
\citet{Eggleton1983}.  Mass transfer rates in Roche lobe
overflowing binary systems are determined following the
prescription of \citet{Ritter1988}.
```

我们提供了一份包含这些参考文献的 [``BibTex` `file``](../_downloads/1a2f108b826ef7b11518c5b7e4989790/CITATIONS.bib)。

### 引用随附的工具

如果你使用了 MESA 中提供的某个仪器（例如
ADIPLS、GYRE、RSP 或 STELLA），请务必包含对
描述它们的论文的引用。

-
ADIPLS ``\citep{ChristensenDalsgaard2008}``

-
GYRE ``\citep{Townsend2013,` `Townsend2018}``

-
RSP ``\citep{Smolec2008}``

-
STELLA ``\citep{Blinnikov2004,` `Baklanov2005,` `Blinnikov2006}``

### 引用 MESASDK

MESASDK 可以通过它的 Zenodo 链接引用：[
MacOS 版](http://doi.org/10.5281/zenodo.2669543)以及[
Linux 版](http://doi.org/10.5281/zenodo.2669541)。引用还应当
包含所使用的 MESASDK 版本，每个 MESASDK 版本都有
各自的 Zenodo DOI。

我们提供了一份包含这些参考文献的 [``BibTex` `file``](../_downloads/4f329feb31489144fa259248e2a2344e/tools.bib)。

### 引用 MESA Zenodo 社区贡献

如果你使用了由 [MESA
Zenodo 社区](https://zenodo.org/communities/mesa)分享的材料，请
务必引用你所利用的 Zenodo 仓库，
以及描述该功能的科学论文。

## 项目结束时

你应当把他人重现你的 MESA 结果所需的全部信息
公开。这包括你的 inlist 和
run_star_extras/run_binary_extras、MESA 版本和 MESA SDK
版本（非 SDK 构建则为编译器版本），以及你
对 MESA 所做的任何修改。

为此我们推荐使用 [Zenodo](http://about.zenodo.org/)。
Zenodo 会为每个条目分配数字对象标识符（DOI），
从而提供一种不可变的方式来在出版物中
引用某次上传。该服务还由 CERN 数据基础设施提供支持，
确保数据的安全及其长期可用性。由于 Zenodo
允许最大 50GB 的上传，这不仅让你可以
共享输入文件，还可以共享你的模拟数据产品。

警告

请注意，一旦某个条目在 Zenodo 上发布，它就无法
被删除，但如果需要修订，可以加入
新版本。在 Zenodo 中准备上传或测试该服务时，
你可以先使用[“sandbox”](https://sandbox.zenodo.org/)
试试。“sandbox”让你在把真正的内容提交到
主服务之前，看到最终条目会是什么样子。

我们创建了一个 [Zenodo
社区](https://zenodo.org/communities/mesa/)，你可以把
你的 Zenodo 上传与之关联。关于你的 Zenodo 上传应包含哪些内容的指南，
可以在 MESA 社区的
[curation policy](https://zenodo.org/communities/mesa/curation-policy) 中找到。
[MESA Marketplace](http://mesastar.org) 将继续作为聚合
门户使用，我们请用户把新的上传告知我们，以便它们
也能在那里得到展示。
