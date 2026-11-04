<!-- 译文：MESA 26.4.1 官方文档 using_mesa/extending_mesa.html 的中文翻译 -->
<!-- 原文：en/extending_mesa.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/extending_mesa.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 扩展 MESA

有时候，MESA 众多的 inlist 选项不足以解决你感兴趣的问题。扩展 MESA
相对来说既容易又轻松。MESA 的设计使得在大多数用法下，人们不应该
需要去修改 MESA 的核心代码（也就是 $MESA_DIR 的内容）。

MESA 提供了一个 ``run_star_extras.f90`` 文件，让你可以提供自己的代码，
在计算过程中执行。
这让你能够做到单靠 inlist 无法做到的事情，例如用简单的例程
在每一步改变参数，
或者覆盖许多默认的物理例程。

也许已经有人写过与你想要的类似的东西了。
查看[用户提交的
例程](https://mesastar.org/marketplace/add-ons/)
列表就知道了。
如果你开发了新的、有用的东西，请考虑与社区分享。

## 第一步

### 启用 ``run_star_extras.f90``

利用这些能力的第一步是启用它们。
在你在教程中创建的 MESA work 目录中，
进入 src 目录

```
cd tutorial/src
```

并选择你喜欢的文本编辑器打开 ``run_star_extras.f90``。
``run_star_extras.f90`` 的初始自带版本相当乏味。
它“包含”了另一个文件，其中存放着默认的一组例程。

```
include 'standard_run_star_extras.inc'
```

这个文件里包含的例程正是我们想要定制的那些。因为我们希望这些修改
只适用于当前这份 MESA 工作副本，而不是整个 MESA，
所以我们要把这个 include 语句替换成被包含文件的内容。
这样修改的影响范围就仅限于当前工作副本。

删除前面提到的 include 行，并插入
``$MESA_DIR/include/standard_run_star_extras.inc`` 的内容。

在我们做任何修改之前，应该先检查代码能否编译通过。

```
cd ..
./mk
```

如果编译不通过，请确认你完整地插入了该文件
并删除了 include 行。

### 控制流程

不同的 ``run_star_extras.f90`` 例程会在 MESA 执行过程中的不同时点被调用。
下面是一个总结这一点的流程图。

[![flowchart]](flowchart.pdf)

第一个例程 ``extras_controls`` 特别重要。
它正是你告诉 MESA 对于其余所有钩子
究竟应该调用哪些子例程的地方。

MESA 的核心是灰色的“take step”方框，
其中包含了 MESA 用来求值和求解
恒星结构方程的全部机制。

在为 run_star_extras.f90 编写 Fortran 代码时，
有几点重要且有用的东西需要了解。

### ``star_info`` 结构

``star_info`` 结构包含了关于正在演化的恒星的所有信息。
按惯例，在 ``run_star_extras.f90`` 中始终使用变量名 ``s``
来指代这个结构。
在 Fortran 中，百分号（``%``）运算符用于访问该结构的各个组成部分。
（所以你可以像在 C 中读 ``s.x` `=` `3`` 那样
读 ``s%` `x` `=` `3``。）

``star_info`` 结构包含恒星模型本身（即网格划分信息、热力学剖面、
化学成分剖面）。这些组成部分列在文件
``$MESA_DIR/star_data/public/star_data_*.inc`` 中，
这些文件被分成几个不同的类别，记录在 ``star_data.inc`` 文件中。
此外，``star_info`` 还包含你在 ``controls`` inlist 中设置的参数值
（即 ``initial_mass``、``xa_central_lower_limit``）。
回想一下，控制项列表位于
``$MESA_DIR/star/defaults/controls.defaults``。
这些参数都可以在代码中直接读取。

``s%` `xtra(1:30)`` 数组是一个用来写入 ``real(dp)`` 类型临时数据的地方，
这些数据遵循时间步的逻辑，因此会跨重启保留、在重试中恢复，等等。

### 用户指定的 inlist 控制项

在使用 ``run_star_extras.f90`` 时，有一组控制项会被一再证明是有用的，
那就是 ``x_ctrl``、``x_integer_ctrl``、``x_logical_ctrl``
和 ``x_character_ctrl``。它们是双精度、整数、布尔和字符值的数组
（默认长度为 100）。
你可以在 inlist 中设置这些元素
并在之后访问它们。

```
&controls
  x_ctrl(1) = 3.14
  x_ctrl(2) = 2.78
  x_integer_ctrl(1) = 42
  x_logical_ctrl(1) = .true.
  x_character_ctrl(1) = 'hello world'
/ ! end of controls inlist
```

并在之后作为 star 结构的一部分来访问它们
（即 ``s%` `x_ctrl(1)`` 等）。有了这些控制项，
你就可以在 inlist 中指定参数，

### 物理常数

MESA 在 ``$MESA_DIR/const/public/const_def.f90`` 中定义其常数。
除非另有说明，MESA 使用 cgs 单位。最常见的非 cgs 单位是
太阳单位。由于 ``run_star_extras`` 模块包含了
``use` `const_def`` 这一行，你已经可以访问这些定义。
使用内置常数可以确保你使用的定义与 MESA
完全相同。

## 添加历史与剖面输出

本节涵盖上面流程图中属于“write data”方框的那些例程。
其中包含这些钩子

-
``how_many_extra_history_columns``

-
``data_for_extra_history_columns``

-
``how_many_extra_profile_columns``

-
``data_for_extra_profile_columns``

向历史文件和/或剖面文件添加新数据，就像编辑这些函数一样简单。
这两者都非常直接。

也许我们感兴趣的是量化核能产生在中心集中的程度。
让我们在历史文件中添加几列，
用来追踪其内部包含了 90% 核能产生的拉格朗日质量和物理半径。
这样一来就能看到核能产生的集中程度。

让我们指明想要在历史文件中添加两列。

```
integer function how_many_extra_history_columns(id)
   integer, intent(in) :: id
   integer :: ierr
   type (star_info), pointer :: s
   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return
   how_many_extra_history_columns = 2
end function how_many_extra_history_columns
```

现在让我们计算想要输出的信息。
这个子例程可以访问 star_info 指针，
因此你可以利用 star/public/star_data_*.inc 中定义的任何量
来计算关于恒星的额外信息。
下面是一个计算我们想知道的东西的子例程。
这个例程中展示了一些值得记住的“最佳实践”，
所以请读一遍代码并注意其中的注释。

```
subroutine data_for_extra_history_columns(id, n, names, vals, ierr)

   integer, intent(in) :: id, n
   character (len=maxlen_history_column_name) :: names(n)
   real(dp) :: vals(n)
   integer, intent(out) :: ierr
   type (star_info), pointer :: s

   real(dp), parameter :: frac = 0.90
   integer :: i
   real(dp) :: edot, edot_partial

   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return

   ! calculate the total nuclear energy release rate by integrating
   ! the specific rate (eps_nuc) over the star.  using the dot_product
   ! intrinsic is a common idiom for calculating integrated quantities.
   ! note that one needs to explicitly limit the range of the arrays.
   ! NEVER assume that the array size is the same as the number of zones.
   edot = dot_product(s% dm(1:s% nz), s% eps_nuc(1:s% nz))

   ! the center of the star is at i = s% nz and the surface at i = 1 .
   ! so go from the center outward until 90% of the integrated eps_nuc
   ! is enclosed.  exit and then i will contain the desired cell index.
   edot_partial = 0
   do i = s% nz, 1, -1
      edot_partial = edot_partial + s% dm(i) * s% eps_nuc(i)
      if (edot_partial .ge. (frac * edot)) exit
   end do

   ! note: do NOT add these names to history_columns.list
   ! the history_columns.list is only for the built-in log column options.
   ! it must not include the new column names you are adding here.

   ! column 1
   names(1) = "m90"
   vals(1) = s% q(i) * s% star_mass  ! in solar masses

   ! column 2
   names(2) = "log_R90"
   vals(2) = log10(s% R(i) / rsun) ! in solar radii

   ierr = 0
end subroutine data_for_extra_history_columns
```

向剖面添加新输出的过程与历史完全类似，
使用函数 ``how_many_extra_profile_columns`` 和
子例程 ``data_for_extra_profile_columns``。

这里我只是把自带示例的注释去掉了。

```
integer function how_many_extra_profile_columns(id)
   use star_def, only: star_info
   integer, intent(in) :: id
   integer :: ierr
   type (star_info), pointer :: s
   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return
   how_many_extra_profile_columns = 1
end function how_many_extra_profile_columns

subroutine data_for_extra_profile_columns(id, n, nz, names, vals, ierr)
   use star_def, only: star_info, maxlen_profile_column_name
   use const_def, only: dp
   integer, intent(in) :: id, n, nz
   character (len=maxlen_profile_column_name) :: names(n)
   real(dp) :: vals(nz,n)
   integer, intent(out) :: ierr
   type (star_info), pointer :: s
   integer :: k
   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return

   ! note: do NOT add the extra names to profile_columns.list
   ! the profile_columns.list is only for the built-in profile column options.
   ! it must not include the new column names you are adding here.

   ! here is an example for adding a profile column
   if (n /= 1) stop 'data_for_extra_profile_columns'
   names(1) = 'beta'
   do k = 1, nz
      vals(k,1) = s% Pgas(k)/s% Peos(k)
   end do

end subroutine data_for_extra_profile_columns
```

## 选择何时输出历史或剖面

我们常常想在一路上的一系列里程碑处输出一个剖面或更新历史。
对剖面而言尤其如此，
因为每几步就保存并存储一个剖面既不可能（甚至也不可取）。
所以需要一种按需输出的办法。

``star_info`` 结构有几个标志——``need_to_save_profiles_now`` 和
``need_to_update_history_now``——
它们让你可以告诉 MESA 是时候输出数据了。

设置它们的地方是函数 extras_finish_step，它会在每一步结束时
被调用。

对我们的这个大质量恒星，让我们在中心密度上按对数等间隔的区间
转储一个剖面。我们会让用户指定每个数量级的分段数。
我们需要小心，
因为在 rho-T 空间中的轨迹并不保证是单调的。

下面就是做这件事的一些代码。同样，请读一遍，因为其中的注释
讨论了一些有用的 MESA 特性。

```
! returns either keep_going or terminate.
! note: cannot request retry; extras_check_model can do that.
integer function extras_finish_step(id)

   integer, intent(in) :: id
   integer :: ierr
   type (star_info), pointer :: s

   integer :: f

   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return

   extras_finish_step = keep_going

   ! MESA provides a number of variables that make it easy to get user input.
   ! these are part of the star_info structure and are named
   ! x_character_ctrl, x_integer_ctrl, x_logical_ctrl, and x_ctrl.
   ! by default there are num_x_ctrls, which defaults to 100, of each.
   ! they can be specified in the controls section of your inlist.

   f = s% x_integer_ctrl(1)

   ! MESA also provides a number of arrays that are useful for implementing
   ! algorithms which require a state. if you use these variables
   ! restarts and retries will work without doing anything special.
   ! they are named xtra, ixtra, lxtra.
   ! they are automatically versioned, that is if you set s% xtra(1), then
   ! s% xtra_old(1) will contains the value of s% xtra(1) from the previous step.

   s% xtra(1) = s% log_center_density

   ! this expression will evaluate to true if f times the log center density
   ! has crossed an integer during the last step.  If f = 5, then we will get
   ! output at log center density = {... 1.0, 1.2, 1.4, 1.6, 1.8, 2.0 ... }
   if ((floor(f * s% xtra_old(1)) - floor(f * s% xtra(1)) .ne. 0)) then

      ! save a profile & update the history
      s% need_to_update_history_now = .true.
      s% need_to_save_profiles_now = .true.

      ! by default the priority is 1; you can change that if you'd like
      ! s% save_profiles_model_priority = ?

   endif

   ! see extras_check_model for information about custom termination codes
   ! by default, indicate where (in the code) MESA terminated
   if (extras_finish_step == terminate) s% termination_code = t_extras_finish_step

end function extras_finish_step
```

为了防止你把磁盘塞满，MESA 只会保存有限数量的剖面。
默认是 100。
如果你想确保在 ``extras_finish_step`` 中触发的那些剖面能够
留下来——也许你正在制作一部动画——
你应该把 ``max_num_profile_models`` 设置得大于
你预计会生成的剖面数量。你可能还想把它们被保存时的优先级调高，
即把 ``save_profiles_model_priority`` 设置为 10。
这会防止 MESA 为了其他自动保存的剖面而丢弃它们。
这样就能保住你自己触发的那些剖面。

## 添加自定义停止条件

MESA 提供了许多选择何时终止运行的方式。
如果你的条件可以表达为
“当量 X 升到某个上限之上或降到某个下限之下时停止”，
那么很有可能你只需设置几个现有的标志就可以选择停止。
看一看 star/defaults/controls.defaults 中“when to stop”那一节，
它大约从第 940 行开始。

如果你的条件不在那里，
或者是一个更复杂的逻辑条件组合，
那么你很可能需要自己实现它。

做这件事的地方是子例程 extras_check_model。（你也可以
用这个例程来触发重试。）

下面是一个当恒星的光度由氖燃烧主导时
就停止的例程。

```
! returns either keep_going, retry, or terminate.
integer function extras_check_model(id)

  use chem_def, only : i_burn_ne, category_name

  integer, intent(in) :: id
  integer :: ierr
  type (star_info), pointer :: s

  integer :: i_burn_max

  ierr = 0
  call star_ptr(id, s, ierr)
  if (ierr /= 0) return

  extras_check_model = keep_going

  ! if you want to check multiple conditions, it can be useful
  ! to set a different termination code depending on which
  ! condition was triggered.  MESA provides 9 customizable
  ! termination codes, named t_xtra1 .. t_xtra9.  You can
  ! customize the messages that will be printed upon exit by
  ! setting the corresponding termination_code_str value.
  ! termination_code_str(t_xtra1) = 'my termination condition'

  ! determine the category of maximum burning
  i_burn_max = maxloc(s% L_by_category,1)

  ! stop if the luminosity is dominated by neon burning
  if ( i_burn_max .eq. i_burn_ne) then
     extras_check_model = terminate
     s% termination_code = t_xtra1
     termination_code_str(t_xtra1) = 'neon burning is dominant'
     return
  end if

  ! by default, indicate where (in the code) MESA terminated
  if (extras_check_model == terminate) s% termination_code = t_extras_check_model

end function extras_check_model
```

## 使用“其他”钩子

MESA 提供了一种覆盖大多数物理例程的方法，
而无需修改 ``run_star_extras`` 之外的任何东西。
利用这一功能需要两个主要步骤。
在下面的例子中，我们会添加一些控制项，
让我们能够控制我们的大质量恒星中
各种非核的中微子损失（例如等离激元、轫致辐射）。

### 编写一个例程

进入 ``$MESA_DIR/star/other``，你会看到一组以
``other_*.f90`` 模式命名的文件。
这个目录中的例程让你可以覆盖/修改
MESA 的许多物理和数值方面的行为。

找到与你想要改变的 MESA 方面相对应的那个文件。
打开它并通读其内容。
许多文件都有帮助性的注释和示例。

注意，我们并不想直接编辑这些文件。相反，我们想把
这些文件提供的模板例程复制到我们工作目录中的
run_star_extras.f90 副本里，然后在那里进一步修改它们。
这些模板例程要么命名为 ``null_other_*``，要么命名为 ``default_other_*``。

对于我们的中微子例子，把下面的子例程复制到
run_star_extras.f90 中。

```
   subroutine null_other_neu( &
      id, k, T, log10_T, Rho, log10_Rho, abar, zbar, log10_Tlim, flags, &
      loss, sources, ierr)
      use star_def
      use neu_lib, only: neu_get
      use neu_def
      integer, intent(in) :: id  ! id for star
      integer, intent(in) :: k  ! cell number or 0 if not for a particular cell
      real(dp), intent(in) :: T  ! temperature
      real(dp), intent(in) :: log10_T  ! log10 of temperature
      real(dp), intent(in) :: Rho  ! density
      real(dp), intent(in) :: log10_Rho  ! log10 of density
      real(dp), intent(in) :: abar  ! mean atomic weight
      real(dp), intent(in) :: zbar  ! mean charge
      real(dp), intent(in) :: log10_Tlim
      logical, intent(inout) :: flags(num_neu_types)  ! true if should include the type of loss
      real(dp), intent(inout) :: loss(num_neu_rvs)  ! total from all sources
      real(dp), intent(inout) :: sources(num_neu_types, num_neu_rvs)
      integer, intent(out) :: ierr
      call neu_get( &
         T, log10_T, Rho, log10_Rho, abar, zbar, log10_Tlim, flags, &
         loss, sources, ierr)
   end subroutine null_other_neu
```

这个模板例程说明了接口，并且就其本身而言，
它会产生与默认 MESA 例程完全相同的结果。
这很有用，因为人们最常想做的那几类修改
都是基于修改 MESA 已经算出的信息，
而不是把物理例程整个重新实现一遍。

在这个例子中，我们想添加一些控制项，让我们可以切换
是否包含特定种类的非核中微子损失。

让我们重命名这个子例程，并添加我们想要的功能。

```
subroutine tutorial_other_neu(  &
     id, k, T, log10_T, Rho, log10_Rho, abar, zbar, log10_Tlim, flags, &
     loss, sources, ierr)
   use neu_lib, only: neu_get
   use neu_def
   integer, intent(in) :: id ! id for star
   integer, intent(in) :: k ! cell number or 0 if not for a particular cell
   real(dp), intent(in) :: T ! temperature
   real(dp), intent(in) :: log10_T ! log10 of temperature
   real(dp), intent(in) :: Rho ! density
   real(dp), intent(in) :: log10_Rho ! log10 of density
   real(dp), intent(in) :: abar ! mean atomic weight
   real(dp), intent(in) :: zbar ! mean charge
   real(dp), intent(in) :: log10_Tlim
   logical, intent(inout) :: flags(num_neu_types) ! true if should include the type of loss
   real(dp), intent(inout) :: loss(num_neu_rvs) ! total from all sources
   real(dp), intent(inout) :: sources(num_neu_types, num_neu_rvs)
   integer, intent(out) :: ierr

   ! before we can use controls associated with the star we need to get access
   type (star_info), pointer :: s
   call star_ptr(id, s, ierr)
   if (ierr /= 0) then ! OOPS
      return
   end if

   ! separately control whether each type of neutrino loss is included
   flags(pair_neu_type) = s% x_logical_ctrl(1)
   flags(plas_neu_type) = s% x_logical_ctrl(2)
   flags(phot_neu_type) = s% x_logical_ctrl(3)
   flags(brem_neu_type) = s% x_logical_ctrl(4)
   flags(reco_neu_type) = s% x_logical_ctrl(5)

   ! the is the normal routine that MESA provides
   call neu_get(  &
       T, log10_T, Rho, log10_Rho, abar, zbar, log10_Tlim, flags, &
       loss, sources, ierr)

end subroutine tutorial_other_neu
```

### 指示 MESA 使用你的例程

要让 MESA 执行你的 ``other_*`` 例程，你必须做两件事。
没有同时做到这两点，
是人们在使用 ``other_*`` 钩子时遇到的最常见问题。

第一，编辑 inlist 的 controls 部分，把相应的
``use_other_*`` 标志设置为 ``.true.``。在我们的例子中，这意味着添加这一行

```
use_other_neu = .true.
```

第二，编辑 ``run_star_extras.f90`` 中的 ``extras_controls`` 例程，把
``other_neu`` 指向你想要执行的例程。

```
subroutine extras_controls(id, ierr)
   integer, intent(in) :: id
   integer, intent(out) :: ierr
   type (star_info), pointer :: s
   ierr = 0
   call star_ptr(id, s, ierr)
   if (ierr /= 0) return

   ! this is the place to set any procedure pointers you want to change
   ! e.g., other_wind, other_mixing, other_energy  (see star_data_procedures.inc)
   s% other_neu => tutorial_other_neu

end subroutine extras_controls
```

现在，重新编译你的工作目录

```
./mk
```

然后像平常一样运行 MESA。
