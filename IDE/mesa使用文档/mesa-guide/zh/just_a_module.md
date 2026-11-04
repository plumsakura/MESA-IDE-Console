<!-- 译文：MESA 26.4.1 官方文档 using_mesa/just_a_module.html 的中文翻译 -->
<!-- 原文：en/just_a_module.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/just_a_module.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 只是一个模块

本文档介绍如何在 MESA 之外使用 MESA 的状态方程、不透明度以及核反应网络。

从 Zenodo 下载这组目录和 makefile：[Just A Module](http://doi.org/10.5281/zenodo.4763740)。

把 zip 文件解压到你喜欢的任何位置。

## 1. 状态方程

开始之前，请先浏览 [
eos 模块概览
](../eos/overview.html#overview-of-eos-module) 和 [
eos 模块控制项
](../eos/defaults.html#eos-module-controls)。

在你解压 zip 文件的位置

```
cd my_eos
cp $MESA_DIR/eos/test/src/sample_eos.f90 .
```

编辑 sample_eos.f90 并修改变量

```
my_mesa_dir = '../..'
```

把它改成你的 $MESA_DIR，或者使用空字符串，此时你的 $MESA_DIR 会被自动使用

```
my_mesa_dir = ''
```

在你编辑 sample_eos.f90 的时候，花点时间探索一下源代码。保存并退出 sample_eos.f90。
现在花点时间探索一下 makefile，并用它来构建可执行文件

```
make
```

运行这个交互式可执行文件，它名为 sample_eos

```
./sample_eos
loading eos tables

give the temperature, density, and mass fractions (h1, he4, c12, n14, o16, ne20, mg24) =>
hit return for T = 1e9 K, Rho = 1e9 g/cc, x(c12) = 1 ; enter -1 to stop

T     =  1.000000E+09 Rho   =  1.000000E+04 abar  =  1.200000E+01 zbar  =  6.000000E+00
h1    =  0.000000E+00 he4   =  0.000000E+00 c12   =  1.000000E+00 n14   =  0.000000E+00
o16   =  0.000000E+00 ne20  =  0.000000E+00 mg24  =  0.000000E+00

quantity      value          d/d(Rho)       d/d(T)       d^2/d(Rho)^2   d^2/d(Rho)d(T) d^2/d(T)^2
p tot   =   3.033664E+21   4.616282E+16   1.098950E+13   7.389591E+11  -2.632100E+07   3.148155E+04
p gas   =   5.117530E+20   4.616282E+16   9.018528E+11   7.389591E+11  -2.632100E+07   1.218618E+03
p rad   =   2.521911E+21   0.000000E+00   1.008764E+13   0.000000E+00   0.000000E+00   3.026293E+04

e tot   =   8.606704E+17  -7.955833E+13   3.425527E+09   1.626134E+10  -3.604408E+05   1.309327E+01
e gas   =   1.040971E+17  -3.900997E+12   3.992340E+08   1.129877E+09  -5.781150E+04   4.014391E+00
e rad   =   7.565733E+17  -7.565733E+13   3.026293E+09   1.513147E+10  -3.026293E+05   9.078880E+00

s tot   =   1.476688E+09  -1.098950E+05   3.425527E+00   2.186704E+01  -3.604408E-04   9.667743E-09
s gas   =   4.679233E+08  -9.018528E+03   3.992340E-01   1.691755E+00  -5.781150E-05   3.615157E-09
s rad   =   1.008764E+09  -1.008764E+05   3.026293E+00   2.017529E+01  -3.026293E-04   6.052587E-09

n_ion   =   5.018451E+26   5.018451E+22   0.000000E+00
n_ele   =   3.200158E+27   2.870797E+23   1.414171E+18
eta_e   =  -4.182056E+00   9.451310E-05  -1.319764E-09
cv      =   3.425527E+09  -3.604408E+05   1.309327E+01
cp      =   2.958707E+10  -5.803942E+06   2.045230E+02
gamma_1 =   1.314315E+00   5.192048E-06  -3.807384E-10
gamma_2 =   1.322910E+00   9.783797E-07  -1.079536E-10
gamma_3 =   1.320812E+00   2.002091E-06  -1.740076E-10
grad_ad =   2.440906E-01   5.590452E-07  -6.168458E-11
chi_t   =   3.622516E+00  -5.143301E-05   2.381262E-09
chi_d   =   1.521685E-01   1.443976E-05  -5.143301E-10
c_sound =   6.310334E+08  -2.640054E+04   1.141379E+00

dsp   =  2.220446E-16 dpe   =  7.993606E-15 dsp   = -2.331468E-15

give the temperature, density, and mass fractions (h1, he4, c12, n14, o16, ne20, mg24) =>
hit return for T = 1e9 K, Rho = 1e9 g/cc, x(c12) = 1 ; enter -1 to stop

-1
STOP normal termination
```

作为课后练习，请编辑 sample_eos.f90，写出
\(\partial{T}/\partial{\rho}|_{S}\)
。
正如 sample_eos.f90 中所提到的，查看 $MESA_DIR/eos/public/eos_def.f90 中包含的整数索引可能会很有用。

## 2. 不透明度

开始之前，请先浏览 [
kap 模块概览
](../kap/overview.html#overview-of-kap-module) 和 [
kap 模块控制项
](../kap/defaults.html#kap-module-controls)。

在你解压 zip 文件的位置

```
cd my_kap
cp $MESA_DIR/kap/test/src/sample_kap.f90 .
cp $MESA_DIR/kap/test/sample_kap_agb.model .
```

编辑 sample_kap.f90 并修改变量

```
my_mesa_dir = '../..'
```

把它改成你的 ``$MESA_DIR``，或者使用空字符串，此时你的 ``$MESA_DIR`` 会被自动使用

```
my_mesa_dir = ''
```

在你编辑 sample_kap.f90 的时候，花点时间探索一下源代码。保存并退出 sample_kap.f90。
现在花点时间探索一下 makefile，并用它来构建可执行文件

```
make
```

运行这个可执行文件，它名为 sample_kap，它会读取一个 mesa 模型文件，并写出每个网格单元处的不透明度及其导数

```
./sample_kap
 Npts        1331
Nspec          31

Z_init   1.0000000000000000E-002

write kap_test.data
```

用下面的命令（例如）来探索输出

```
head -4 kap_test.data
                       grid                     log_T                    log_Rho                      kappa                   kappa_CO                dlnK_dlnRho                  dlnK_dlnT
                          1   3.5585465937700458E+000   -8.4473997504616456E+000    1.7963661540128417E-003    1.7963661540128417E-003    5.9324713626960102E-001    7.7443291473465914E+000
                          2   3.5585885995787634E+000   -8.4471065383083204E+000    1.7984321714713182E-003    1.7984321714713182E-003    5.9331124051888307E-001    7.7411914141868570E+000
                          3   3.5586446634268447E+000   -8.4467158120772723E+000    1.8011910725944315E-003    1.8011910725944315E-003    5.9339708647788947E-001    7.7370154334784580E+000
```

## 3. 核反应网络

开始之前，请先浏览 [
net 模块概览
](../net/overview.html#overview-of-net-module) 和 [
反应网络
](../net/nets.html#reaction-networks)。

在你解压 zip 文件的位置

```
cd my_net
cp $MESA_DIR/net/test/src/sample_net.f90 .
```

编辑 sample_net.f90 并修改变量

```
my_mesa_dir = '../..'
```

把它改成你的 ``$MESA_DIR``，或者使用空字符串，此时你的 ``$MESA_DIR`` 会被自动使用

```
my_mesa_dir = ''
```

在你编辑 sample_net.f90 的时候，花点时间探索一下源代码。保存并退出 sample_net.f90。
现在花点时间探索一下 makefile，并用它来构建可执行文件

```
make
```

运行这个交互式可执行文件，它名为 sample_net

```
./sample_net

load approx21.net

give the temperature, density, and mass fractions (h1, he4, c12, n14, o16, ne20, mg24) =>
hit return for T = 1e9 K, Rho = 1e4 g/cc, x(c12) = 1 ; enter -1 to stop

T     =  1.000000E+09 Rho   =  1.000000E+04 abar  =  1.200000E+01 zbar  =  6.000000E+00
h1    =  0.000000E+00 he4   =  0.000000E+00 c12   =  1.000000E+00 n14   =  0.000000E+00
o16   =  0.000000E+00 ne20  =  0.000000E+00 mg24  =  0.000000E+00

d(h1)/dt   =  0.000000E+00  d(he4)/dt  =  5.582829E-09    d(c12)/dt  = -3.349697E-08    d(n14)/dt  =  0.000000E+00
d(o16)/dt  =  0.000000E+00  d(ne20)/dt =  2.791414E-08    d(mg24)/dt =  0.000000E+00
1 - sum    = -6.617445E-24
eps_nuc    =  6.217517E+09     erg/g/sec

give the temperature, density, and mass fractions (h1, he4, c12, n14, o16, ne20, mg24) =>
hit return for T = 1e9 K, Rho = 1e4 g/cc, x(c12) = 1 ; enter -1 to stop

-1
STOP normal termination
```

作为课后练习，请编辑 sample_net.f90，修改网络以及相关的写出语句。
