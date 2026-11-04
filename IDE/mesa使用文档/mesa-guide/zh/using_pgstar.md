<!-- 译文：MESA 26.4.1 官方文档 using_mesa/using_pgstar.html 的中文翻译 -->
<!-- 原文：en/using_pgstar.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/using_pgstar.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 使用 PGSTAR

在终端窗口里看着大量数字飞速掠过，能让你对一次运行的情况有些
概念，但如果能有随每一步变化的绘图窗口，那就好得多（也有趣得多）。
PGstar 建立在 PGPLOT 之上，用于创建绘图：
用 Xwindows 作屏幕上的绘图，用 PNG 生成电影帧，
以便把这些绘图制作成动画。

花大量时间观看模型的演化吧。这是一种有趣的学习方式！

如果你使用的是 MESA SDK，那么使用 PGSTAR 所需的一切你就都已经具备。
否则，你需要安装 PGPLOT、Xwindows，以及它们所需要的少数几个库。
详情请参见 ``$MESA_DIR/utils`` 中的 ``makefile_header_non_mesasdk``。
如果需要安装 PGPLOT，你可以在 ``$MESA_DIR/scripts`` 里找到
pgplot.tar.bz2（感谢加州理工学院的 Tim Pearson 创建了 PGPLOT，
并允许我们将其随 MESA
一起分发）。

## PGSTAR 概述

PGSTAR 拥有数量庞大的功能和控件。下面是一个简要
概述。

### 剖面图（profile plot）与历史图（history plot）

剖面图（profile plot）显示当前模型的信息。你可以显示任何能够
包含在 profile_columns.list 中的内容。你并不
局限于当前 profile_columns.list 中的条目。

历史图（history plot）显示由你当前 history_columns.list 指定的信息。
如果某个量在你的 history_columns.list 中，你就能
在历史图中显示它。历史条目的名称必须与
你当前 LOGS/history.data 中的某个列标题相同——这些列标题
与 history_columns.list 中的条目相同，只不过其中的任何
空格都被替换成了 ``_``。例如，
history_columns.list 中的 ``center` `h1`` 在
LOGS/history.data 中作为列标题会变成 ``center_h1``，因此
你应该在图中使用 ``center_h1`` 作为名称。

### 单面板图、多面板图与网格图

单面板图（single panel plot）包含一幅图，可选地带有第二条 Y 轴。
多面板图（multiple panel plot）使用相同的 X 轴，把若干幅图
层叠在一起。网格图（grid plot）按用户指定的网格布局
把若干其他图组合起来。

### 通用控件

你可以通过编辑 ``pgstar_controls`` inlist 文件来更改任何绘图的宽度、
宽高比、边距、文字缩放比例、标题和坐标轴范围。该
文件会在每个时间步被重新读取，因此你可以在演化
运行过程中进行修改。对于用户自定义的绘图，你还可以
随时更改任何设置，包括各坐标轴绘制的内容以及
面板数量或网格布局。你可以在运行中把 ``win_flag`` 从
``.false.`` 改为 ``.true.`` 来创建新窗口。把
win_flag 从 ``.true.`` 改为 ``.false.`` 会移除该窗口，但由于
pgplot 和/或 Xwindows 的古怪行为，它会暂停下来并要求你按一次
回车。

你可以通过设置 ``pause` `=` `.true.`` 让代码在每一步都暂停。它
会在你设置 ``pause_interval` `=` `n`` 时每第 n 步暂停一次。

你可以通过把 ``pgstar_sleep`` 设置为绘图更新之间所允许的
最小秒数来放慢它的速度。

如果你设置 ``pgstar_interval` `=` `n``，它就会每第 n 步更新一次窗口。

要把绘图保存为 png 文件，请把该窗口的 ``file_flag`` 设为
``.true.`` 你可以为这些文件指定目录和前缀，还可以
指定写入频率（每第 n 步）以及文件中绘图的
大小。你甚至可以让文件在恒星于 HR 图上移动了给定
距离时写出！

要从黑色背景切换到白色背景，请更改 ``white_on_black_flag``。
窗口和文件各有独立的标志。

## 绘图清单

### 单面板剖面图

-
``TRho_Profile`` - T-Rho 平面中的当前模型

-
``Summary_Profile`` - 各种剖面属性

-
``Summary_Burn`` - 当前模型的 T、rho、eps 燃烧率和 eps 中微子率

-
``Abundance`` - 当前模型的丰度剖面

-
``Power`` - 当前模型的核产能率剖面

-
``Mixing`` - 当前模型的混合扩散系数

-
``Dynamo`` - 当前模型的发电机磁场信息

-
``Mode_Prop`` - 星震学模式传播图

### 单面板历史图

-
``Kipp`` - 混合、燃烧等的“Kippenhann”历史

-
``Summary_History`` - 各种历史属性

-
``TRho`` - 中心温度与密度的历史

-
``HR`` - log_L 与 log_Teff 的历史

-
``logg_Teff`` - logg 与 Teff 的历史

-
``logg_logT`` - logg 与 log_Teff 的历史

-
``dPg_dnu`` - delta_Pg 与 delta_nu（用于星震学）

请记住，如果某个量不在你当前的历史列表中，那么它
就无法在 PGSTAR 历史图中绘制。例如，如果
你的 Kipp 图没有显示燃烧区和混合区，那就把它们添加
到 history_columns.list 中——例如，添加以下内容：

```
mixing_regions 40
burning_regions 80
```

### 剖面面板图：``Profile_Panels1`` 到 ``Profile_Panels9``

你可以从 profile_columns.list 中允许的任何量里选择坐标轴。
此外，一个面板还可以是以下任何预定义绘图：Abundance、
Power、Mixing、Dynamo、Mode_prop 或 Summary_Profile。

-
``Profile_Panels1`` - 默认 X = mass，面板 = (logT,entropy) 和
(logRho,logP)。

-
``Profile_Panels2`` - 默认 X = logP，面板 = Abundance 和 Power。

-
``Profile_Panels3`` - 默认 X = logP，面板 = Abundance、Power
和 Mixing。

-
``Profile_Panels4`` - 默认 X = logP，面板 = Abundance、Power、
Mixing 和 Dynamo。

-
``Profile_Panels5`` - 默认 X = logP，面板 = Summary_Profile、
Mode_prop 和 Mixing。

### 历史轨迹图：``History_Track1`` 到 ``History_Track9``

与 TRho、HR 及其他历史图类似，但你可以从当前
history_columns.list 中的条目里选择坐标轴。

-
``History_Track1`` - 默认显示 log_L 与 log_center_T

### 历史面板图：``History_Panels1`` 到 ``History_Panels9``

你可以从当前 LOGS/history.data 的列标题中选择 Y 轴。

-
``History_Panels1`` - 默认显示 logT、logRho、log_L、log_Teff、mass、
mdot

### 文本摘要图：``Text_Summary1`` 到 ``Text_Summary9``

-
``Text_Summary1`` - 默认给出与标准终端
输出类似的信息

### 网格图：``Grid1`` 到 ``Grid9``

-
``Grid1`` - 默认 TRho_Profile、HR、TRho、Text_Summary1

-
``Grid2`` - 默认 TRho_Profile、Kipp

-
``Grid3`` - 默认 TRho_Profile、Summary_Profile、Kipp

-
``Grid4`` - 默认 TRho_Profile、Summary_Profile、HR、TRho、Kipp、
Text_Summary1

-
``Grid5`` - 默认 TRho_Profile、Summary_Profile、HR、TRho、Kipp

-
``Grid6`` - 默认 Summary_Burn、Abundance、HR、TRho、Text_Summary1

-
``Grid7`` - 默认 Abundance、TRho、Text_Summary1

-
``Grid8`` - 默认 Summary_Burn、Abundance、HR、TRho、TRho_Profile、
Text_Summary1

-
``Grid9`` - 默认 Abundance、HR、TRho、TRho_Profile、Text_Summary1

## 动手教程

在 ``$MESA_DIR/star`` 正在运行且 ``pgstar_flag`` 被设为
``.true.`` 时做这个教程，这样你就能在编辑并保存
inlist 的过程中观察绘图如何变化。

我建议使用测试用例 1M_pre_ms_to_wd。进入目录
$MESA_DIR/star/test_suite/1M_pre_ms_to_wd，并在文本编辑器中打开“inlist_1.0”。
在 ``&star_job`` 段中，设置 ``pgstar_flag` `=` `.true.``，并
检查 ``&pgstar`` 段确认它一开始是空的。然后照常执行
``./mk`` 和 ``./rn`` 来启动该测试用例。

首先，打开一些绘图窗口，看看有哪些可用的东西。只需
编辑你的 pgstar inlist，为绘图设置“win_flag”；保存文件后，
改动会在下一步生效；你不需要
停止并重新启动运行就能更改绘图。

先打开预定义的剖面图。把以下各行复制粘贴
到你的 inlist 中，然后保存。快速浏览每一个，
以熟悉这些选项。

```
TRho_Profile_win_flag = .true.
Summary_Profile_win_flag = .true.
Abundance_win_flag = .true.
Power_win_flag = .true.
Mixing_win_flag = .true.
Dynamo_win_flag = .true.
Mode_Prop_win_flag = .true.
```

接下来，用打开一些历史图的行替换掉那些行。
复制粘贴这些行以替换之前的行。然后保存。
PGPLOT 会要求你按回车，以关闭之前
打开的那些窗口。

```
Kipp_win_flag = .true.
TRho_win_flag = .true.
HR_win_flag = .true.
Summary_History_win_flag = .true.
```

看过这些之后，再来看看几个多面板图的
默认设置。和之前一样，剪切粘贴这些行并替换掉
之前那些行。

```
Profile_Panels1_win_flag = .true.
Profile_Panels2_win_flag = .true.
History_Track1_win_flag = .true.
History_Panels1_win_flag = .true.
Grid1_win_flag = .true.
Grid2_win_flag = .true.
```

当你欣赏完这些美景之后，从你的 inlist 中删除那些“``win_flag``”
行，然后我们就来看看你可以如何修改
绘图。

我们先来更改一些 Abundance 绘图的控件；请一次
只改一处，这样你就能看到每一次改动。并确保在你保存时
该绘图是可见的！

```
Abundance_win_flag = .true.
Abundance_win_width = 6
Abundance_win_aspect_ratio = 1.2
Abundance_log_mass_frac_min = -4
Abundance_xaxis_name = 'logP'
Abundance_xmin = 12
```

你可以更改 Summary_Profile 图上显示的线条集合。有一个
控制线条数量的控件，以及每条线的名称字符串和图例字符串。
每个值都可以按缩放或不缩放的方式显示。缩放是把最大值映射到
1.0、最小值映射到 0.0。通常只有质量分数是不
缩放显示的。下面是默认设置中的一些例子。请注意
“omega”所用的 PGPLOT 符号。

```
Summary_Profile_win_flag = .true.
Summary_Profile_num_lines = 11 ! <= 16

Summary_Profile_name(1) = 'x' ! hydrogen mass fraction
Summary_Profile_legend(1) = 'X'
Summary_Profile_scaled_value(1) =.false.

Summary_Profile_name(2) = 'y' ! helium mass fraction
Summary_Profile_legend(2) = 'Y'
Summary_Profile_scaled_value(2) = .false.

Summary_Profile_name(3) = 'log_j_rot' ! specific angular momentum
Summary_Profile_legend(3) = 'log j rel'

Summary_Profile_name(4) = 'log_omega' ! angular velocity
Summary_Profile_legend(4) = 'log (0650) rel'
```

打开 Summary_Profile 窗口，然后做一些更改。请注意，你
只需把名称设为 ``''`` 就能删除一条线；你不必
重新给其他线编号。

```
Summary_Profile_num_lines = 12 ! <= 16
Summary_Profile_name(12) = 'zone'
Summary_Profile_name(3) = ''
Summary_Profile_name(4) = ''
```

你可以更改 Summary_History 图上显示的线条集合。有一个
控制线条数量的控件，以及每条线的名称字符串和图例字符串。
每个值都可以按缩放或不缩放的方式显示。缩放是把最大值映射到
1.0、最小值映射到 0.0。通常只有质量分数是不
缩放显示的。下面是默认设置中的一些例子。请注意
用于中心值下标“c”的 PGPLOT 文本控制符。

```
Summary_History_num_lines = 7 ! <= 16

Summary_History_name(1) = 'log_center_T'
Summary_History_legend(1) = 'log T\dc\u rel'

Summary_History_name(2) = 'log_center_Rho'
Summary_History_legend(2) = 'log Rho\dc\u rel'
```

打开 Summary_History 窗口，然后做一些更改。请注意，
你只需把名称设为 ``''`` 就能删除一条线；你不必
重新给其他线编号。

```
Summary_History_win_flag = .true.
Summary_History_num_lines = 9
Summary_History_name(8) = 'star_mass'
Summary_History_name(9) = 'log_abs_mdot'
Summary_History_name(6) = ''
Summary_History_name(7) = ''
```

接下来，打开 History_Track1 绘图。然后通过编辑坐标轴
名称和标签来更改它绘制的内容。下面是一个例子。
在那之后，试着绘制一些其他组合；只需从当前 LOGS/history.data
的列标题中挑选坐标轴名称即可。

```
History_Track1_win_flag = .true.

History_Track1_xname = 'log_center_P'
History_Track1_xaxis_label = 'log P\dcenter'
History_Track1_title = 'L vs Center P'
```

打开 ``Profile_Panels1`` 和 ``History_Panels1``；它们已经用面板数量和
坐标轴的默认值设置好了。请更改这些默认值以显示
其他内容——对于剖面图，你可以选择任何能够出现在
profile_columns.list 中的量；对于历史图，你必须从当前
LOGS/history.data 的列标题中选择一个。

```
History_Panels1_win_flag = .true.
History_Panels1_other_yaxis_name(1) = 'log_center_P'

Profile_Panels1_win_flag = .true.
Profile_Panels1_xaxis_name = 'logP'
Profile_Panels1_xaxis_reversed = .true.
```

给剖面图再添加一个面板。

```
Profile_Panels1_num_panels = 3
Profile_Panels1_yaxis_name(3) = 'logtau'
Profile_Panels1_other_yaxis_name(3) = 'log_opacity'
```

增大 y 边距。

```
Profile_Panels1_ymargin(1) = 0.2
Profile_Panels1_other_ymargin(1) = 0.2
Profile_Panels1_ymargin(2) = 0.2
Profile_Panels1_other_ymargin(2) = 0.2
Profile_Panels1_ymargin(3) = 0.2
Profile_Panels1_other_ymargin(3) = 0.2
```

更改宽高比，减小宽度，并固定左右边距。

```
Profile_Panels1_win_aspect_ratio = 1.0 ! aspect_ratio = height/width
Profile_Panels1_win_width = 6
Profile_Panels1_xleft = 0.18
Profile_Panels1_xright = 0.82
```

挑选一些其他坐标轴名称，更改面板中显示的内容。
你可以使用 profile_columns.list 中任何有效的名称；与
历史图的情况不同，你不必把自己限制在
当前列表的内容范围内。

接下来，看一看下面这个 Profile_Panels3 的
默认定义。

```
Profile_Panels3_xaxis_name = 'logP'
Profile_Panels3_xaxis_reversed = .true.
Profile_Panels3_num_panels = 3
Profile_Panels3_yaxis_name(1) = 'Abundance'
Profile_Panels3_yaxis_name(2) = 'Power'
Profile_Panels3_yaxis_name(3) = 'Mixing'
```

打开该绘图窗口，然后更改面板数量和
内容。修改标题并把 x 轴切换为 mass。

```
Profile_Panels3_win_flag = .true.
Profile_Panels3_num_panels = 4
Profile_Panels3_yaxis_name(4) = 'Dynamo'
Profile_Panels3_title = 'Abundance-Power-Mixing-Dynamo'
Profile_Panels3_xaxis_name = 'mass'
Profile_Panels3_xaxis_reversed = .false.
```

现在，编辑 Grid1 绘图的定义。把 TRho_Profile
绘图替换为 Kipp 绘图，并调整边距和文字缩放比例。

```
Grid1_win_flag = .true.
Grid1_plot_name(1) = 'Kipp'
Grid1_plot_pad_left(1) = 0.03 ! fraction of full window width for padding on left
Grid1_plot_pad_right(1) = 0.03 ! fraction of full window width for padding on right
Grid1_plot_pad_bot(1) = 0.12 ! fraction of full window height for padding at bottom
Grid1_txt_scale_factor(1) = 0.6 ! multiply txt_scale for subplot by this
```

把文本摘要上移到紧挨 Kipp 图的下方，并增加
行数，让 HR 和 TRho 图变得更高。这会
暂时把子图之间的间距弄乱，但我们下一步
就会把它修好。

```
Grid1_num_rows = 9 ! divide plotting region into this many equal height rows
Grid1_plot_row(2) = 7 ! number from 1 at top
Grid1_plot_rowspan(2) = 3 ! plot spans this number of rows
Grid1_plot_row(3) = 7 ! number from 1 at top
Grid1_plot_rowspan(3) = 3 ! plot spans this number of rows
Grid1_plot_row(4) = 5 ! number from 1 at top
Grid1_plot_rowspan(4) = 2 ! plot spans this number of rows
```

在那之后，修正绘图之间的填充间距，并调整文字大小。

```
Grid1_plot_pad_top(2) = 0.01 ! fraction of full window height for padding at top
Grid1_plot_pad_bot(2) = 0.1 ! fraction of full window height for padding at bottom
Grid1_plot_pad_left(2) = 0.05 ! fraction of full window width for padding on left
Grid1_plot_pad_right(2) = 0.1 ! fraction of full window width for padding on right
Grid1_txt_scale_factor(2) = 0.6 ! multiply txt_scale for subplot by this

Grid1_plot_pad_top(3) = 0.01 ! fraction of full window height for padding at top
Grid1_plot_pad_bot(3) = 0.1 ! fraction of full window height for padding at bottom
Grid1_plot_pad_left(3) = 0.1 ! fraction of full window width for padding on left
Grid1_plot_pad_right(3) = 0.05 ! fraction of full window width for padding on right
Grid1_txt_scale_factor(3) = 0.6 ! multiply txt_scale for subplot by this

Grid1_plot_pad_top(4) = 0.00 ! fraction of full window height for padding at top
Grid1_plot_pad_bot(4) = 0.05 ! fraction of full window height for padding at bottom
```

把文本摘要改为报告 ‘log_L_div_Ledd’ 而不是 ‘log_LH’。

```
Text_Summary1_name(3,4) = 'log_L_div_Ledd'
```

最后，快速浏览一下各种多面板图和网格图的
默认设置（上面已列出）。你并不局限于这些，但它们也许
能给你一些灵感，做出你自己的个性化绘图。下面是我最喜欢的
几个——你也许会觉得它们也很有用。

```
Grid8_win_flag = .true. ! Summary_Burn, Abundance, HR, TRho, TRho_Profile, Text_Summary1
Profile_Panels4_win_flag = .true. ! Abundance, Power, Mixing, and Dynamo
History_Panels1_win_flag = .true. ! logT, logRho, log_L, log_Teff, mass, mdot
```

如果你没有开启旋转，就把 Profile_Panels4 改成
Profile_Panels3，或者编辑 Profile_Panels4 的控件，去掉
最后一个面板。

```
Profile_Panels3_win_flag = .true. ! Abundance, Power, and Mixing
```

或者

```
Profile_Panels4_num_panels = 3
Profile_Panels4_title = 'Abundance-Power-Mixing'
```

PGSTAR 有许多选项可以用来控制它的文件输出（file output）。

默认的输出格式是 PNG

```
file_device = 'png'
```

但你可以通过设置以下内容来使用 PostScript 输出

```
file_device = 'vcps'
```

你可以在黑/白与白/黑之间更改绘图的
前景色/背景色

```
! white_on_black flags -- true means white foreground color on black background
file_white_on_black_flag = .true.
```

并控制文件名中出现的数字位数

```
file_digits = 5 ! number of digits for model_number in filenames
```

此外，每个绘图都有各自文件输出的控件，与下面这些
针对 TRho_Profile 的控件类似：

```
TRho_Profile_file_dir = 'png'
TRho_Profile_file_flag = .false.
TRho_Profile_file_prefix = 'trho_profile_'
TRho_Profile_file_interval = 5 ! output when mod(model_number,TRho_Profile_file_interval)==0
TRho_Profile_file_width = -1 ! (inches) negative means use same value as for window
TRho_Profile_file_aspect_ratio = -1 ! negative means use same value as for window
```

必须以 TRho_Profile_file_dir 的值（在这里就是
默认值“png”）为名的目录必须存在于工作目录中，
文件才能被保存下来。否则 MESA 会继续运行，
但无法写出 png 文件。请务必先创建这样一个目录！
（如果你使用 PostScript 输出，
你大概想要创建一个名为“ps”的目录，
并设置 TRho_Profile_file_dir=’ps’。）

最后，还有一个用于文件输出的 HR 距离触发器。

```
! trigger file output by distance traveled on HR diagram
delta_HR_limit_for_file_output = -1 ! negative means no limit

! HR distance since last file output = sum of dHR
! where per step dHR = same definition as used for timestep limits
! dHR = sqrt((delta_HR_ds_L*dlgL)**2 + (delta_HR_ds_Teff*dlgTeff)**2)
! dlgL = log10(L/L_prev)
! dlgTeff = log10(Teff/Teff_prev)
```

有各种各样的工具可以把 png 文件合成为
电影。
