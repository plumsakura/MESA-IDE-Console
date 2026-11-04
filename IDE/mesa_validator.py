# ⚠️ 本文件为弃用死代码（阶段 3 起整体注释保留，按用户要求不删除）。
# 原因：全项目无任何 import 引用；
#   mesa_validator.py 的功能已由 mesa_linter.py / core.linting 承担（含 difflib 拼写建议可作移植参考）；
#   data_analyzer.py 的绘图逻辑已由 mesa_plotter.py 承担。
# 如确认不再需要，可直接删除本文件（git 历史中仍保留完整内容）。
#
# import sqlite3
# import difflib
# import re
# import os
# 
# 
# class MESAValidator:
#     def __init__(self, db_path='mesa_data.db'):
#         self.db_path = db_path
#         self.valid_params = set()
# 
#         # 将原来的正则修改为：匹配等号左边除空白外的所有字符
#         self.re_assignment = re.compile(r'^\s*([^=\s]+)\s*=')
# 
#         self._load_parameters()
#         self.popup = None  # 必须显式声明初值，防止 close_popup 时报错
# 
#     def _load_parameters(self):
#         """内部方法：从数据库加载所有参数名到内存，打造极速检查"""
#         if not os.path.exists(self.db_path):
#             print(f"[验证器警告] 找不到数据库文件: {self.db_path}，拼写检查将被禁用。")
#             return
# 
#         try:
#             conn = sqlite3.connect(self.db_path)
#             cursor = conn.cursor()
# 
#             # 根据你提供的表名 (parameters) 和字段名 (name) 查询
#             cursor.execute('SELECT name FROM parameters')
#             rows = cursor.fetchall()
# 
#             # 将所有合法参数存入集合 (Set 查询的时间复杂度为 O(1))
#             self.valid_params = {row[0] for row in rows}
# 
#             conn.close()
#         except sqlite3.Error as e:
#             print(f"[验证器错误] 读取数据库失败: {e}")
# 
#     def check_file(self, content):
#         """
#         扫描文件内容，验证变量名是否存在于数据库中
#         返回格式同 Linter
#         """
#         issues = []
# 
#         # 如果数据库没加载成功，直接返回空列表
#         if not self.valid_params:
#             return issues
# 
#         lines = content.splitlines()
# 
#         for i, line in enumerate(lines, 1):
#             stripped = line.strip()
# 
#             # 忽略注释和空行
#             if not stripped or stripped.startswith('!'):
#                 continue
# 
#             # 解析赋值语句
#             match = self.re_assignment.match(stripped)
#             if match:
#                 var_name = match.group(1)
# 
#                 # 开始查参
#                 if var_name not in self.valid_params:
#                     # 如果找不到，使用 difflib 提供拼写建议
#                     suggestions = difflib.get_close_matches(var_name, self.valid_params, n=1, cutoff=0.7)
# 
#                     if suggestions:
#                         msg = f"未知参数 '{var_name}'。您是不是想输入 '{suggestions[0]}'?"
#                     else:
#                         msg = f"未知参数 '{var_name}'，它不存在于任一 namelist 中。"
# 
#                     issues.append({
#                         "line": i,
#                         "type": "未知参数",
#                         "level": "error",
#                         "message": msg
#                     })
# 
#         return issues
