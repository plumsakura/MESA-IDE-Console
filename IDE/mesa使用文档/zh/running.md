<!-- 译文：MESA 26.4.1 官方文档 using_mesa/running.html 的中文翻译 -->
<!-- 原文：en/running.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/running.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 运行 MESA

本页介绍如何使用 MESA 演化单颗恒星。
它假定你已经安装好 MESA（参见 [
安装 MESA
](../installation.html#installing-mesa)）。

``$MESA_DIR`` 目录下有许多子目录。其中大多数
子目录都是模块（MESA 中的“M”），它们提供某种
特定的功能（例如，“kap”提供计算不透明度的
例程）。最重要的模块是“star”，它包含一个
知道如何把其他所有模块的能力组合起来、
把恒星模型的状态推进一步，
然后为下一步建议一个新的时间增量的模块。基本上，
它所做的就是这些。

你来到这里是为了找一个能使用这些模块来做
多步恒星演化的程序。你很幸运，因为这样的程序
就位于 star/work 目录中，所以我们就从那里开始。

## 复制一份 star/work 目录

你应该把工作开展并保存在主 MESA 目录
之外的某个地方。这样当你在将来某个时候
重新检出（checkout）一个新版本 MESA 时，生活会更简单。因此，
每次你想开始一个新的 MESA 项目时，都应该
新建一份 star/work 目录的副本。让我们为这个教程这样做。

```
cp -r $MESA_DIR/star/work tutorial
```

现在我们有了 work 目录的副本，接下来需要编译
其中的代码。

```
cd tutorial
./mk
```

## 设置配置文件

work 目录中已经包含一组简单的配置文件，
它们会把一颗 15 太阳质量的恒星演化到
零龄主序（核心氢点火）。目前你不需要编辑
任何东西，但你应该看看这些文件中的每一个。

### inlist

这是 MESA 启动时读取的第一个 inlist 文件。
``inlist`` 文件通常用来指示 MESA 读取一个或多个
其他 inlist 文件。

star 的 inlist 文件中有五个区段（严格说是 fortran 的“namelist”）：

-
**star_job** - 演化恒星的程序选项

-
**eos** - MESA eos 模块的选项

-
**kap** - MESA kap 模块的选项

-
**controls** - MESA star 模块的选项

-
**pgstar** - 屏幕绘图（on-screen plotting）的选项

namelist 中的每个定义形式为

```
name = value ! comment
```

取值使用普通的 fortran 语法指定。空行和
注释行可以随意加入列表。在包含名值对的
行开头的空格也没问题，因此你可以（也应该）
对内容做缩进，使它们更易读。

所有控制项在初始化时都给出了合理的默认值，
所以你只需要设置那些你确实想要
更改的项。

```
! This is the first inlist file that MESA reads when it starts.

! This file tells MESA to go look elsewhere for its configuration
! info. This makes changing between different inlists easier, by
! allowing you to easily change the name of the file that gets read.

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
```

### inlist_project

这些就是我们将用来从主序前模型构造一颗 15 太阳质量恒星，
然后在到达零龄主序（ZAMS）后停止演化的
选项。

```
! inlist to evolve a 15 solar mass star

! For the sake of future readers of this file (yourself included),
! ONLY include the controls you are actually using.  DO NOT include
! all of the other controls that simply have their default values.

&star_job

   ! see star/defaults/star_job.defaults

   ! begin with a pre-main sequence model
   create_pre_main_sequence_model = .true.

   ! save a model at the end of the run
   save_model_when_terminate = .false.
   save_model_filename = '15M_at_TAMS.mod'

   ! display on-screen plots
   pgstar_flag = .true.

/ ! end of star_job namelist

&eos

   ! eos options
   ! see eos/defaults/eos.defaults

/ ! end of eos namelist

&kap

   ! kap options
   ! see kap/defaults/kap.defaults
   use_Type2_opacities = .true.
   Zbase = 0.02

/ ! end of kap namelist

&controls

   ! see star/defaults/controls.defaults

   ! starting specifications
   initial_mass = 15 ! in Msun units
   initial_z = 0.02

   ! when to stop

   ! stop when the star nears ZAMS (Lnuc/L > 0.99)
   Lnuc_div_L_zams_limit = 0.99d0
   stop_near_zams = .true.

   ! stop when the center mass fraction of h1 drops below this limit
   xa_central_lower_limit_species(1) = 'h1'
   xa_central_lower_limit(1) = 1d-3

   ! wind

   ! atmosphere

   ! rotation

   ! element diffusion

   ! mlt

   ! mixing

   ! timesteps

   ! mesh

   ! solver
   ! options for energy conservation (see MESA V, Section 3)
   energy_eqn_option = 'dedt'
   use_gold_tolerances = .true.

   ! output

/ ! end of controls namelist
```

### inlist_pgstar

这里存放屏幕绘图的选项。现在你可以随意忽略
这些，但如果想了解更多，请看一看本网站的 [
使用 PGSTAR
](using_pgstar.html#using-pgstar)
一节。

```
&pgstar

   ! see star/defaults/pgstar.defaults

   ! MESA uses PGPLOT for live plotting and gives the user a tremendous
   ! amount of control of the presentation of the information.

   ! show HR diagram
   ! this plots the history of L,Teff over many timesteps
   HR_win_flag = .true.

   ! set static plot bounds
   HR_logT_min = 3.5
   HR_logT_max = 4.6
   HR_logL_min = 2.0
   HR_logL_max = 6.0

   ! set window size (aspect_ratio = height/width)
   HR_win_width = 6
   HR_win_aspect_ratio = 1.0

   ! show temperature/density profile
   ! this plots the internal structure at single timestep
   TRho_Profile_win_flag = .true.

   ! add legend explaining colors
   show_TRho_Profile_legend = .true.

   ! display numerical info about the star
   show_TRho_Profile_text_info = .true.

   ! set window size (aspect_ratio = height/width)
   TRho_Profile_win_width = 8
   TRho_Profile_win_aspect_ratio = 0.75

/ ! end of pgstar namelist
```

## 运行 MESA

现在运行代码就像输入下面这行一样简单

```
./rn
```

MESA 会通过如下所示的终端输出不断向你报告进度：

```
       step    lg_Tmax     Teff     lg_LH      lg_Lnuc     Mass       H_rich     H_cntr     N_cntr     Y_surf   eta_cntr   zones  retry
  lg_dt_yrs    lg_Tcntr    lg_R     lg_L3a     lg_Lneu     lg_Mdot    He_core    He_cntr    O_cntr     Z_surf   gam_cntr   iters
    age_yrs    lg_Dcntr    lg_L     lg_LZ      lg_Lphoto   lg_Dsurf   CO_core    C_cntr     Ne_cntr    Z_cntr   v_div_cs       dt_limit
__________________________________________________________________________________________________________________________________________________

        200   7.468401  2.865E+04   4.240859   4.240859  15.000000  15.000000   0.699697   0.003104   0.280000  -5.917248    864      3
 3.3257E+00   7.468401   0.795655 -32.911837   3.063854 -99.000000   0.000000   0.280004   0.009379   0.020000   0.014657      5
 5.0236E+04   0.611187   4.374553 -99.000000 -99.000000  -9.031542   0.000000   0.001654   0.002085   0.020299  0.000E+00  max increase
```

MESA 还会显示一些 pgstar 图，看起来像：

![赫罗图 (HR Diagram)]

![TRho 剖面 (TRho Profile)]

这应该会运行 207 步（这个数字在不同 MESA 版本之间
可能略有不同），然后停止并输出以下
消息：

```
stop because Lnuc_div_L >= Lnuc_div_L_zams_limit
```

## 恢复 MESA 运行

你并不局限于在整个运行过程中使用同一套参数设置。
你可以停止运行、编辑 inlist 文件，然后用新的
设置重新启动。这种停止—重启机制经过精心构建，
使得如果你从某个中间状态重启而不更改任何
控制项，就会得到完全相同的结果。要做到这一点，
所保存的信息必须是完整的，而这意味着信息量很大。
为了让这种重启运行得快，重启信息以二进制
格式转储。这些二进制转储被称为“photos”，保存在
一个同名的子目录中。

应当强调，photos 并不是为了长期
保存模型而设计的。特别是，当你更新到新版本的
MESA star 时，应当预期你已有的 photo 文件会
变得过时。

如果你回翻这次运行的终端输出，应该能找到
一行看起来像这样的内容（这个数字在不同
MESA 版本之间可能略有不同）：

```
save photos/x207 for model 207
```

这表明在运行终止时，其中一个快照被自动
保存了下来。

在你的编辑器中打开 ``inlist_project``。你可以看到有两个
停止条件，

```
! stop when the star nears ZAMS (Lnuc/L > 0.99)
Lnuc_div_L_zams_limit = 0.99d0
stop_near_zams = .true.

! stop when the center abundance by mass of h1 drops below this limit
xa_central_lower_limit_species(1) = 'h1'
xa_central_lower_limit(1) = 1d-3
```

正如 MESA 在终止消息中指出的那样，我们停止是因为
第一个条件（自然，ZAMS 在氢耗尽之前）。通过编辑你的
inlist 来关闭这个停止条件，使得

```
stop_near_zams = .false.
```

然后保存这个 inlist 文件。

现在我们可以用这个 photo 和我们的新设置来重启。试一下。

```
./re x207
```

这会从模型 207 恢复运行，但这一次运行会在
另一个条件得到满足时停止，即中心氢降到
低于 0.001 时。这将在模型编号 305 时发生。

## 保存模型

记住，photo 文件是机器可读的二进制文件，并不是
为在不同机器之间、甚至在不同 MESA 版本之间
移植而设计的。所以我们需要另一种保存模型的方式，以便日后
使用它，也许是作为后续运行的起始模型，或者发送给
某人，让他们用自己的 MESA 副本使用。例如，如果
你在 MESA 中发现某个 bug，开发者会想看看他们能否
在自己的机器上复现它。你会被要求从
bug 发生之前保存一个模型，并连同你的
inlist 一起用电子邮件发过去。

让我们在运行结束时保存一个模型文件。转到你的 inlist 中
``&star_job`` 区段的下面这几行：

```
! save a model at the end of the run
save_model_when_terminate = .false.
save_model_filename = '15M_at_TAMS.mod'
```

通过编辑你的 inlist、把 ``save_model_when_terminate`` 改为 ``.true.``，
告诉 MESA 你希望在结束时保存一个模型文件。

保存该文件，然后像之前一样从同一点重启 MESA。

```
./re x207
```

这一次当运行终止时，MESA 会保存一个名为
``15M_at_TAMS.mod`` 的模型。去看一看吧。

## 加载模型

现在你可以开始研究恒星的
主序后演化，用你刚刚保存的模型启动一次新的 MESA 运行。为了
做到这一点，你的 inlist 可能看起来像这样：

```
&star_job
  ! see star/defaults/star_job.defaults

  ! start a run from a saved model
  load_saved_model = .true.
  load_model_filename = '15M_at_TAMS.mod'

  ! display on-screen plots
  pgstar_flag = .true.

/ !end of star_job namelist

&eos
  ! eos options
  ! see eos/defaults/eos.defaults

/ ! end of eos namelist

&kap
  ! kap options
  ! see kap/defaults/kap.defaults
  use_Type2_opacities = .true.
  Zbase = 0.02

/ ! end of kap namelist

&controls
  ! see star/defaults/controls.defaults

  ! options for energy conservation (see MESA V, Section 3)
  energy_eqn_option = 'dedt'
  use_gold_tolerances = .true.

  ! configure mass loss on RGB & AGB
  cool_wind_RGB_scheme = 'Dutch'
  cool_wind_AGB_scheme = 'Dutch'
  RGB_to_AGB_wind_switch = 1d-4
  Dutch_scaling_factor = 0.8

/ ! end of controls namelist
```

如果你想试试这个，把前面的文本保存为你的 work 目录中
一个名为 ``inlist_load`` 的文件。确保你的文件以
一个空白的新行结尾。然后编辑你的主 inlist
文件，使它会在 inlist 中所有地方使用 ``inlist_load`` 而不是
``inlist_project``（即 ``extra_star_job_inlist_name(1)`` 和
``extra_controls_inlist_name(1)``）。

然后像往常一样，执行

```
./rn
```

MESA 就会使用你新保存的文件启动。与 photos 不同，
保存的模型并没有系统内部状态的完整快照。
Photos 保证会给出相同的结果；保存的模型则不
保证。当你运行一个保存的模型时，可能会与你
保存它之前那次运行中看到的结果略有差异。这些差异应该
很微小，所以你不必担心，但也别被
它们吓到。

## 了解众多的 MESA 选项

看完前面的 inlist 之后，你可能更急于问的问题是
“那些选项是从哪里来的？”以及“我怎样找到
适合我的问题的选项？”。你的第一站应该是
仪器论文（instrument papers），它们讨论了最重要的标志（flag）。

包含所有 MESA 选项说明及其
默认值的文件位于目录

```
$MESA_DIR/star/defaults
```

这些选项按它们所属的 namelist 来组织。所以
``controls.defaults`` 文件包含了对 controls namelist 中
选项的讨论。

假设我们想更多地了解这个“Dutch_wind”是什么。在
controls.defaults 中搜索“Dutch”这个词，很快就能找到
这些选项的以下摘要。

```
      ! Dutch_scaling_factor
      ! ~~~~~~~~~~~~~~~~~~~~

      ! The "Dutch" wind scheme for massive stars combines results from several papers,
      ! all with authors mostly from the Netherlands.

      ! The particular combination we use is based on
      ! Glebbeek, E., et al, A&A 497, 255-264 (2009) [more Dutch authors!]

      ! For Teff > 1e4 and surface H > 0.4 by mass, use Vink et al 2001
      ! Vink, J.S., de Koter, A., & Lamers, H.J.G.L.M., 2001, A&A, 369, 574.

      ! For Teff > 1e4 and surface H < 0.4 by mass, use Nugis & Lamers 2000
      ! Nugis, T.,& Lamers, H.J.G.L.M., 2000, A&A, 360, 227
      ! Some folks use 0.8 for non-rotating models (Maeder & Meynet, 2001).

      ! ::

    Dutch_scaling_factor = 0d0

      ! Dutch_wind_lowT_scheme
      ! ~~~~~~~~~~~~~~~~~~~~~~

      ! For Teff < 1e4

      ! Use de Jager if ``Dutch_wind_lowT_scheme = 'de Jager'``
      ! de Jager, C., Nieuwenhuijzen, H., & van der Hucht, K. A. 1988, A&AS, 72, 259.

      ! Use van Loon if ``Dutch_wind_lowT_scheme = 'van Loon'``
      ! van Loon et al. 2005, A&A, 438, 273.

      ! Use Nieuwenhuijzen if ``Dutch_wind_lowT_scheme = 'Nieuwenhuijzen'``
      ! Nieuwenhuijzen, H.; de Jager, C. 1990, A&A, 231, 134

      ! ::

    Dutch_wind_lowT_scheme = 'de Jager'
```

你可以浏览这些 .defaults 文件来熟悉
有哪些可用选项。你很容易被选项的庞大数量
所淹没。这时 test_suite 就派上用场了。
