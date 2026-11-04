<!-- 译文：MESA 26.4.1 官方文档 using_mesa/troubleshooting.html 的中文翻译 -->
<!-- 原文：en/troubleshooting.md（抓取自 https://docs.mesastar.org/en/26.4.1/using_mesa/troubleshooting.html） -->
<!-- 说明：代码、命令、参数名与链接保持原文；译文与英文原文冲突时以英文原文为准。 -->
# 疑难排查

## 获取帮助

### 外部软件包（ADIPLS、GYRE、STELLA）

MESA 乐于提供外部软件工具的特定版本，例如 GYRE、ADIPLS 和 STELLA。
虽然 MESA 开发者并不主动支持这些外部软件包，但我们支持与它们之间的接口。
例如，请参见 ``$MESA_DIR/astero/test_suite`` 中的 ``astero_adipls`` 和
``astero_gyre``，了解在一次恒星演化运行期间如何调用这些软件包。
另请参见 ``$MESA_DIR/star/test_suite/ccsn_IIp``，了解如何从 mesa/star
运行的输出为 STELLA 准备输入。最后，
``$MESA_DIR/stella/res/stella_extras.f90`` 中有一些例程，
可以把 STELLA 的部分输出转换成对 MESA 更“友好”的形式。
我们同样支持所有这些接口，并一如既往地欢迎关于如何使用它们的问题，
以及让它们变得更好的建议。
对于这些接口，我们始终欢迎各种问题，
也欢迎让它们变得更好的建议。
任何关于这些接口的反馈都受到欢迎。

如果上述工具对某人的实验有所帮助，那真是太好了。如果某人在使用其中
某个软件包时遇到困难或缺陷，那么 (a) 不要在会出问题的参数范围内
使用该软件包，(b) 把报告直接提交给这些软件包的开发者。GYRE 就是
一个极好的例子。人们在 mesa-users 上不太看到与 GYRE 相关的问题，
原因之一就是 GYRE 拥有活跃而稳健的支持体系（参见
[gyre-forums](http://user.astro.wisc.edu/~townsend/gyre-forums/)）。
话虽如此，也可能有另一位 mesa-user 在使用这些外部工具之一时
遇到过同样的难题，并且已经解决了该问题，
愿意与社区分享其解决方案。
我们一如既往地欢迎 mesa-users 上关于这些外部软件包的帖子。
我们始终欢迎这样的分享与讨论。
