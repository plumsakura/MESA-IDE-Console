<!-- 译文：MESA 26.4.1 官方文档 using_mesa/output.html 的中文翻译 -->
<!-- 原文：en/output.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/output.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# MESA 输出

## 输出文件

默认情况下，MESA 把数据存放在 LOGS 目录中。这些数据文件是
纯文本的，可以送进你惯用的绘图程序。你应当访问 MESA 论坛的
[Add-ons](https://mesastar.org/marketplace/add-ons/) 版块，
看看是否有人用你偏好的语言贡献过代码。（Python、
IDL、ruby 与 Mathematica 都有相当成熟的例程。）一个 Python 绘图的例子见
[本页后面](#plotting-mesa-output)。

在 LOGS 目录里，你会看到以下文件。

### history.data

一次运行的历史记录保存在文件 “history.data” 中，每个被记录的模型占一行。
history.data 的第一行是列号，第二行是列名，
其后的行则是对应的数值。发生 restart 时，history.data 中已有的行
不会被删除，新的数值只是追加到
文件末尾。因此日志里的 model_numbers 并不保证
单调递增。使用该历史记录的代码
必须承担删除已过时行的责任。
最简单的做法是：读取数据时按 model_number 作为数组下标
把数据存进数组。
这样，历史文件后面出现的较新数值会覆盖旧值，
你就自动丢弃了过时的数据。

### profiles.index

MESA 不会为每一步都保存剖面（那会占用太多
空间）。这个列表告诉你如何在剖面文件名里的编号
与 MESA 模型号之间换算。默认情况下，MESA 会在
运行结束时保存一个剖面。

profiles.index 里每个剖面对应一行，给出模型号、
它的优先级（priority）与剖面号。优先级 2 表示
该模型是因为演化中发生了某个特殊事件（例如
氦燃烧点火）而被保存的。优先级 1 表示该模型是因为
距最近一个剖面以来的模型数达到了
当前 profile_interval 参数的设置而被保存的。

### profile.data

剖面文件（profiles）包含一组选定模型的详细信息，
每个模型一个文件。剖面数据文件的文件名
由剖面号决定。例如，剖面号是
15 时，剖面数据就在名为 ‘profile15.data’ 的文件里。

每个剖面既包含一组恒星的全局量（例如
它的年龄），也包含恒星模型中每个点的大量性质，
每个点一行。在这两种情况下，数据行之前都
有一行列号与一行列名。

## 选择输出量

MESA 的默认输出由这些文件决定

```
$MESA_DIR/star/defaults/history_columns.list
$MESA_DIR/star/defaults/profile_columns.list
```

要自定义输出，请把这两个文件复制到你的工作
目录

```
cp $MESA_DIR/star/defaults/history_columns.list .
cp $MESA_DIR/star/defaults/profile_columns.list .
```

然后用文本编辑器打开 history_columns.list 或 profile_columns.list。
文件里描述了所有可用选项的完整列表。要
增加/删除你关心的列，就把相应行取消注释/加注释（‘!’ 是
注释字符）。

但如果你想要的 history 或 profile 物理量不在
列表里呢？那就需要[使用
run_star_extras.f](run_star_extras.html)。

## 绘制 MESA 输出

pgstar 很适合实时观察恒星模型演化、
以及快速生成视频，但更复杂、更高质量的
图需要在别的环境里做后处理。近些年最受欢迎的
环境大概是 Python，尤其是通过
[numpy](http://www.numpy.org) 与
[matplotlib](http://matplotlib.org) 这两个包。

你可能想自己写工具来读取和分析 MESA 计算的
输出，但[已经有很多现成的
工具](https://mesastar.org/marketplace/add-ons/)。沿着这个
方向，我们介绍一个用于 Python 脚本与
交互式会话的简单模块 ``mesa_reader``，它只依赖
[numpy](http://www.numpy.org)。

### 什么是 MESA Reader？

``mesa_reader`` 由三个类组成，你可以用它们
读取一个典型 ``LOGS`` 目录的内容。这三个
类分别是 ``MesaData``（对应剖面
或 history 文件里的数据）、``MesaProfileIndex``（对应
``profiles.index`` 里的数据）与 ``MesaLogDir``（把剖面、
剖面索引与 history 文件里的数据串在一起）。
关于 MESA Reader 如何安装、以及如何使用这
三个类的完整文档，见该项目的 [GitHub
仓库](https://github.com/wmwolf/py_mesa_reader) 与
配套的
[文档](https://wmwolf.github.io/py_mesa_reader)。

### 如何安装 MESA Reader？

mesa_reader 最稳定的发行版可以通过
[pip](https://pip.pypa.io/en/stable)
安装：

```
pip install mesa_reader
```

### 示例

下面给出 MESA Reader 的一些简单用例。

#### 基础

```
# import mesa_reader to make its classes accessible
import mesa_reader as mr

# make a MesaData object from a history file
h = mr.MesaData('LOGS/history.data')

# extract the star_age column of data
ages = h.data('star_age')

# or do it more succinctly
ages = h.star_age
```

这里 ``ages`` 现在是一个 numpy 数组，其数值与
``LOGS/history.data`` 文件中 ``star_age`` 这一列相同。

以上就是读取 history 文件的做法，那剖面（profiles）呢？如果我们
知道确切要加载哪个文件，也可以用同样的办法：

```
import mesa_reader as mr

# load the profile file into a MesaData instance
p = mr.MesaData('LOGS/profile1.data')

# access the temperature column of data
temperatures = 10 ** p.logT
```

但事先并不总是知道该加载哪个剖面文件，这很令人沮丧，
所以我们可以用 ``MesaLogDir`` 类来简化。它
让我们按模型号加载剖面，或者用最简单的方式——
直接加载最后保存的那个剖面：

```
import mesa_reader as mr

l = mr.MesaLogDir('./LOGS')

# load the profile associated with model number 100
p_100 = l.profile_data(100)
# the same as the following
p_100 = l.profile_data(model_number=100)

# load the profile with PROFILE number 12
p_12 = l.profile_data(profile_number=12)

# load the last profile saved (largest model number)
p_last = l.profile_data()
```

获取特定剖面文件的方式还有很多，甚至可以按
history 文件里的条件来筛选剖面。更多内容见完整
[文档](https://wmwolf.github.io/py_mesa_reader)。

#### HR 图

好，那怎么用这些数据画图呢？MESA Reader 本身
不含绘图能力，但它让在别的环境里绘图变得
极其简单。这个例子我们使用 matplotlib，并
假定它在 pylab 的交互模式下使用：

```
# start pylab mode
%pylab
# import mesa_reader
import mesa_reader as mr

# load and plot data
h = mr.MesaData('LOGS/history.data')
plot(h.log_Teff, h.log_L)

# set axis labels
xlabel('log Effective Temperature')
ylabel('log Luminosity')

# invert the x-axis
plt.gca().invert_xaxis()
```

对于一次模拟大质量脉动星的算例，这会得到
类似下图的结果：

[![HR 图示例]](hr_sample.pdf)

如果你的图样式与此不同也不必担心，那只是
``matplotlibrc`` 文件的差异，这里不
展开讨论。

### 温度-密度剖面

绘制温度-密度剖面（temperature-density profile）的过程非常相似：

```
%pylab
import mesa_reader as mr

# load entire LOG directory information
l = mr.MesaLogDir('./LOGS')
# grab the last profile
p = l.profile_data()

# this works even if you only have logRho and logT!
loglog(p.Rho, p.T)
xlabel("Density")
ylabel("Temperature")
```

它会得到类似下图的结果：

[![T-Rho 剖面示例]](TRho_sample.pdf)

### 更进一步

MESA Reader 非常通用，它并不只是用来抽取数据
列做简单绘图的工具（尽管那大概是最显而易见的
用法）。你可以用它筛选数据，只挑出满足某个
条件的时段或剖面（比如挑出恒星位于 HR 图某个
特定区域时保存的剖面）。稍
多花点巧思，还能画出更复杂的图，例如 Kippenhahn 图。
