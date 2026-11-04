# ⚠️ 本文件为弃用死代码（阶段 3 起整体注释保留，按用户要求不删除）。
# 原因：全项目无任何 import 引用；
#   mesa_validator.py 的功能已由 mesa_linter.py / core.linting 承担（含 difflib 拼写建议可作移植参考）；
#   data_analyzer.py 的绘图逻辑已由 mesa_plotter.py 承担。
# 如确认不再需要，可直接删除本文件（git 历史中仍保留完整内容）。
#
# # data_analyzer.py
# import mesa_reader as mr
# import matplotlib.pyplot as plt
# import os
# 
# 
# def get_hr_diagram(project_path):
#     """生成 HR 图的 Matplotlib Figure 对象"""
#     history_path = os.path.join(project_path, 'LOGS/history.data')
#     if not os.path.exists(history_path):
#         raise FileNotFoundError("找不到 LOGS/history.data，请先运行程序。")
# 
#     h = mr.MesaData(history_path)
# 
#     # 创建 Figure
#     fig, ax = plt.subplots(figsize=(6, 4))
#     ax.plot(h.log_Teff, h.log_L)
#     ax.invert_xaxis()
#     ax.set_title("HR Diagram")
#     ax.set_xlabel('log Effective Temperature')
#     ax.set_ylabel('log Luminosity')
#     ax.grid(True, linestyle='--', alpha=0.6)
# 
#     return fig
# 
# 
# def get_trho_profile(project_path):
#     """生成最后一个剖面的 T-Rho 图"""
#     log_dir_path = os.path.join(project_path, 'LOGS')
#     if not os.path.exists(log_dir_path):
#         raise FileNotFoundError("找不到 LOGS 目录。")
# 
#     l = mr.MesaLogDir(log_dir_path)
#     p = l.profile_data()  # 读取最后一个剖面
# 
#     fig, ax = plt.subplots(figsize=(6, 4))
#     ax.loglog(p.Rho, p.T)
#     ax.set_title(f"Density-Temperature Profile (Model {p.model_number})")
#     ax.set_xlabel("Density")
#     ax.set_ylabel("Temperature")
#     ax.grid(True, which="both", linestyle='--', alpha=0.6)
# 
#     return fig
