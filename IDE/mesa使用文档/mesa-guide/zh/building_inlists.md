<!-- 译文：MESA 26.4.1 官方文档 using_mesa/building_inlists.html 的中文翻译 -->
<!-- 原文：en/building_inlists.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/building_inlists.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 构建 inlist

MESA 的 inlist 由五个主要段组成，分别标记为 ``&star_job``、``&controls``、
``&eos``、``&skap`` 与 ``&pgstar``。``&star_job`` 段包含"应当使用哪些 MESA 模块"的指示，
``&controls`` 段则是指定 star 模块选项的地方。``&kap`` 与 ``&eos`` 段分别用于指定
不透明度（opacity）与状态方程（equation of state）的控制项。
``&pgstar`` 段包含创建 pgstar 绘图的命令。

## ``&star_job``

MESA 的主要模块（**star** 之外）有：[
状态方程（eos）
](../modules.html#eos)、[
不透明度（kap）
](../modules.html#kap)、[
大气（atm）
](../modules.html#atm)，以及核反应。
在 inlist 的这一段里，你需要选择使用哪种大气模型、哪套核反应网络，
以及使用哪些核反应速率。
你还要在这里指定起始模型的一些信息，以及演化输出的相关信息。
这里只描述最常用的一部分控制项。可用控制项的完整列表见 [
star_job
](../reference/star_job.html#star-job)。

### 起始模型

要开始一次演化，你可以新建一个前主序（pre main sequence）模型并从那里开始（情形 1），
也可以从先前算好的模型开始（情形 2）。对于后者，强烈建议从
与后续演化所用 MESA 版本相同的模型开始。

情形 1：

```
      create_pre_main_sequence_model = .true.
      load_saved_model = .false.
```

情形 2：

```
      create_pre_main_sequence_model = .false.
      load_saved_model = .true.
      load_model_filename = 'start.mod'
```

### 输出

有一系列控制项用来指定我们想要的 MESA 输出。
history 文件包含恒星在某些时间步上的全局信息。profile 文件包含
给定时刻恒星模型内部剖面的信息。这些文件的默认值位于 ``$MESA_DIR/star/defaults``。
如果你想要与默认不同的输出，就把这些文件复制到你的工作目录、给它们改名
（这里我们用 ``my_history_columns.list`` 与 ``my_profile_columns.list``），
再按你的喜好定制。只要你把下面几行写进 inlist，MESA 就会使用你工作目录里的
文件，而不是默认文件。

```
      history_columns_file = 'my_history_columns.list'
      profile_columns_file = 'my_profile_columns.list'
```

你可能想保存演化得到的最终模型。这种情况下必须告诉 MESA 这么做
（默认是 ``save_model_when_terminate=.false.``）并指定最后一个模型的名字。

```
      save_model_when_terminate = .true.
      save_model_filename = 'final.mod'
```

### 初始化学组成

有几种方式指定初始化学组成。
（待补充）。

你也可以使用基于已发表数据的预定义化学组成。它们通过控制项 ``initial_zfracs`` 设置。
MESA 中默认的初始组成是 ``initial_zfracs` `=` `3``，对应 [GS98](https://link.springer.com/article/10.1023%2FA%3A1005161325181) 的金属丰度。
MESA 中这个控制项有 8 种可能的预定义选择。

例如，如果你想使用 [AGSS09](https://www.annualreviews.org/doi/pdf/10.1146/annurev.astro.46.060407.145222) 给出的更新的太阳组成，
就需要设置 ``initial_zfracs` `=` `6``。
由于"必须使用与所采用太阳组成相匹配的不透明度表"这一点非常重要，我们还要把
``kap_file_prefix`` 设为 2009 太阳组成对应的值（默认表对应 gs98 组成）。

```
      initial_zfracs = 6
      kappa_file_prefix = 'a09'
```

### 核反应

选择核反应网络。网络的选取应当依据你要研究的物理问题。在研究主序演化时
选择非常全面的核反应集合并无必要，反而会显著拖慢计算。但研究
演化的高级燃烧阶段时，它又是必需的。MESA 中可用核反应网络的说明
见 ``$MESA_DIR/data/net_data`` 里的 README 文件。MESA 使用的默认反应网络是 ``basic.net``。

例如，演化水平分支（氦燃烧）上的恒星模型时，这套网络是不够的。
一种选择是使用名为 ``pp_and_cno_extras.net`` 的核反应网络，它对
氢燃烧与氦燃烧的覆盖更完整。

```
      change_initial_net = .true.
      new_net_name = 'pp_and_cno_extras.net'
```

## ``&controls``

### 能量方程

在 MESA 中，能量方程可以写成 dLdm 形式或 dedt 形式（见 [MESAV](https://arxiv.org/pdf/1903.01426.pdf)）。
如 [MESAV](https://arxiv.org/pdf/1903.01426.pdf) 所述，使用 dedt 形式能得到好得多的能量守恒。
dLdm 形式目前是 MESA 的默认值。如果偏好 dEdt 形式，必须在 inlist 中指定。

```
      energy_eqn_option = 'dedt'
```

### 起始质量与金属丰度

需要指定的主要恒星参数是初始质量 M、金属丰度 Z 与氦丰度 Y。
如果只指定 M 与 Z，氦含量默认取 Y=0.24 + 2Z。

```
      initial_mass = 2.0
      initial_z = 2d-2
```

### 何时停止

### 不透明度控制（Opacity controls）

在氦燃烧期间及之后，为了处理额外的 C/O，应当使用 Type2 不透明度。使用 Type2 不透明度
需要指定基准金属丰度 Zbase，它给出任何 CO 增强之前的金属丰度。在中心氢高于
给定阈值、或金属丰度并不显著高于 Zbase 的区域，会改用 Type1 表，并有混合区
以便平滑过渡。原因是 Type1 表覆盖更宽的 X 范围，且对每个 X 在 Z 方向分辨率更高。
更多信息请参考 ``$MESA_DIR/star/defaults/controls.defaults`` 文件。

如果演化包含氦燃烧，就应当使用 type2 不透明度。

```
      use_Type2_opacities = .true.
      Zbase = 2d-2
```

### 对流与对流边界

MESA 用 MLT 对流理论处理对流，并提供不同的形式化方案。默认情况下 MESA 使用
[Cox&Giuli 1968](https://ui.adsabs.harvard.edu/abs/1968pss..book.....C/abstract) 的形式化方案。

如果你想使用其它方案，例如 [Henyey 对流理论](http://articles.adsabs.harvard.edu/pdf/1965ApJ...142..841H)，
可以用 ``MLT_option`` 控制项指定。这个选项还可以指定若干参数，其中主要的是
混合长参数。注意 MESA 中该参数的默认值是 ``mixing_length_alpha=2``，
这个值并非来自任何标定。

```
      MLT_option = 'Henyey'
      mixing_length_alpha = 1.8d0
```

有两种判据可用于确定对流边界的位置：Schwarzschild 判据与 Ledoux 判据。
默认情况下 MESA 使用 Schwarzschild 判据。如果判定正确，对流边界的位置
不应取决于使用哪种判据。但使用 Schwarzschild 或 Ledoux 判据会导致
对流区之外的丰度剖面不同。关于这个话题，[MESAIV](https://arxiv.org/pdf/1710.08424.pdf) 与
[MESAV](https://arxiv.org/pdf/1903.01426.pdf) 论文里有大量讨论。
MESA 引入了两种新算法：**Predictive mixing**（见 [MESAIV](https://arxiv.org/pdf/1710.08424.pdf)）
与 **Convective PreMixing**（见 [MESAV](https://arxiv.org/pdf/1903.01426.pdf)）。默认情况下 MESA
两者都不用，这会导致对流边界判定严重错误，对恒星模型的演化产生重要影响。
因此强烈建议使用其中一种算法。

如果使用 **Convective premixing**，没有额外参数需要指定。

```
      use_Ledoux_criterion = .true.
      do_conv_premix = .true.
```

如果使用 **Predictive mixing**，则有额外的控制项，见 [MESAIV](https://arxiv.org/pdf/1710.08424.pdf)。

```
      predictive_mix(1) = .true.
      predictive_zone_type(1) = 'any'
      predictive_zone_loc(1) = 'core'
      predictive_bdy_loc(1) = 'any'
      predictive_superad_thresh(1) = 0.005

      predictive_mix(2) = .true.
      predictive_zone_type(2) = 'any'
      predictive_zone_loc(2) = 'surf'
      predictive_bdy_loc(2) = 'any'
      predictive_superad_thresh(2) = 0.001
```

### 超射（Overshooting）

### 时间步与网格控制

## ``&kap``

## ``&eos``

## ``&colors``

``&colors`` 段用于配置自定义的 colors 模块，以便在恒星演化过程中计算合成测光（synthetic photometry）。
该模块对恒星大气模型做插值，计算热辐射星等以及指定测光滤光片下的合成星等，
并把它们作为额外的 history 列加入输出。

### 启用合成测光

要启用 colors 模块，把 ``use_colors`` 控制项设为 ``.true.``。这样每个时间步都会
使用插值得到的恒星大气模型计算合成星等。

```
      ! Enable the colors module
      use_colors = .true.

      ! Filter system specification
      ! This points to a directory containing Johnson filter transmission curves.
      ! The Johnson directory should contain files like:
      !   - U.dat, B.dat, V.dat, R.dat, I.dat, J.dat, M.dat   (filter transmission curves)
      instrument = 'data/colors_data/filters/Generic/Johnson'

      ! Stellar atmosphere model directory
      ! Should contain:
      ! - lookup_table.csv: mapping file with columns for filename, Teff, log_g, metallicity
      ! - Individual SED files: wavelength vs surface flux for each stellar model
      ! - flux_cube.bin: pre-computed interpolation grid (if using linear/hermite interpolation)
      stellar_atm = 'data/colors_data/stellar_models/Kurucz2003all/'

      ! Physical parameters for synthetic photometry
      distance = 3.0857d19         ! Distance to star in cm (1 pc = 3.0857e16 m for absolute mags)

      ! Output options
      colors_results_directory = 'SED'
      make_csv = .true.            ! Write detailed SED files showing filter convolution  -- This is also needed for plotting the SED.
                                   ! Creates files like: SED/B_SED.csv, SED/VEGA_B_SED.csv

      !zero point. Select between: Vega, AB, ST
      mag_system = 'Vega'

      ! Vega spectrum for zero-point calibration
      ! This file should contain wavelength (Å) and flux (erg/s/cm²/Å) columns
      ! Used to define the zero-point of the magnitude system (Vega = 0.0 mag)
      vega_sed = 'data/colors_data/stellar_models/vega_flam.csv'
```

### 关键控制项

-
**use_colors**：启用或禁用 colors 模块（默认：``.false.``）。

-
**instrument**：指定测光系统或滤光片集合（例如 ‘Gaia’）。

-
**stellar_atm**：恒星大气模型网格的路径（例如 Kurucz 2003 模型）。

-
**vega_sed**：用于零点定标的 Vega 参考光谱路径。

-
**distance**：计算绝对星等时假定的恒星距离（单位秒差距；默认：10 pc）。

-
**make_csv**：若为 ``.true.``，把 SED 与测光结果输出为 CSV 文件以便核对。

-
**colors_results_directory**：当 ``make_csv`` 启用时存放输出 CSV 文件的目录。

该模块使用预先算好的恒星大气模型网格（例如 Kurucz 2003，覆盖 Teff = 3500-50000 K、
log g = 0.0-5.0、[M/H] = -5.0 到 +1.0），根据恒星演化中的参数（Teff、log g、金属丰度）
插值得到光谱能量分布（SED）。这些 SED 与滤光片透射曲线卷积，得到合成星等。

### 额外的 history 列

启用后，该模块会向 history 文件加入以下列：

-
``Mag_bol``：热辐射星等（Bolometric magnitude）。

-
``Flux_bol``：热辐射流量（Bolometric flux）。

-
各滤光片对应的星等（例如 ``Gbp``、``G``、``Grp``、``Grvs``）。

请确保滤光片名称与 ``instrument`` 目录中的一致。
