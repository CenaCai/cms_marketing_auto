"""将误嵌在 _sync_resolved_assets_to_strategy 内的 5 个 Handler 方法提拔为真正的类方法。

背景：commit 712621c 中，_sync_resolved_assets_to_strategy（模块级函数）在 line 3700 处本应结束，
但其后的 5 个 _handle_* 方法（带 self 参数、被 do_POST 以 self._handle_X 调用）被多缩进了一级，
错误地嵌进了 _sync 的函数体。导致这些方法是嵌套函数而非 Handler 方法，运行时
self._handle_complete 等抛 AttributeError。

本脚本：用 ast 精确定位 -> 抽出这 5 个方法并整体去缩进 4 空格 -> 插入 Handler 类内
（紧接 _handle_service_approve 之后）-> 从 _sync 中删除。_sync 自身保持模块级函数不变。
"""
import ast

P = r'C:/Users/cenacai/WorkBuddy/2026-08-31-18-52-03/autopilot-poc/cockpit.py'
src = open(P, 'r', encoding='utf-8').read()
lines = src.split('\n')
tree = ast.parse(src)

# 定位模块级 _sync_resolved_assets_to_strategy
sync = next((n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == '_sync_resolved_assets_to_strategy'), None)
assert sync is not None, "找不到 _sync_resolved_assets_to_strategy"

# 其内嵌套的全部 handler（commit 712621c 把这些本应属于 Handler 的方法整体多缩进了一级，
# 错误地嵌进了 _sync 的函数体；它们都带 self 参数、被 do_POST 以 self._handle_X 调用）。
nested = [n for n in sync.body if isinstance(n, ast.FunctionDef)]
nested.sort(key=lambda n: n.lineno)
print("发现嵌套 handler 数:", len(nested))

# 抽出每个 handler 的文本块（按行）。handler 本就在 col 4（与 Handler 类方法同级缩进），
# 只需「搬移」到 Handler 类内即可，不要去缩进（否则会变成 col 0 模块级）。
blocks = []
for n in nested:
    start = n.lineno - 1          # 0-based
    end = n.end_lineno            # 0-based 末尾行（含）
    block = lines[start:end]
    blocks.append('\n'.join(block))

lifted_text = '\n'.join(blocks)

# 从原文件删除嵌套区域（1-based 闭区间 [min_start, max_end]）
h_min = min(n.lineno for n in nested)
h_max = max(n.end_lineno for n in nested)
del lines[h_min - 1:h_max]

# 定位 Handler 类内的 _handle_service_approve 末尾行（1-based），在其后插入
handler = next((c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Handler'), None)
sa = next((m for m in handler.body if isinstance(m, ast.FunctionDef) and m.name == '_handle_service_approve'), None)
sa_end = sa.end_lineno  # 1-based
# 0-based 插入点：在 sa_end 行之后
ins_idx = sa_end
lines[ins_idx:ins_idx] = [lifted_text, '']  # 末尾补一个空行，便于与随后的模块级 _sync 分隔

new_src = '\n'.join(lines)
open(P, 'w', encoding='utf-8', newline='\n').write(new_src)

# 验证
tree2 = ast.parse(new_src)
handler2 = next((c for c in tree2.body if isinstance(c, ast.ClassDef) and c.name == 'Handler'), None)
methods = [m.name for m in handler2.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
print("lifted handlers:", [n.name for n in nested])
print("removed 1-based lines:", h_min, "->", h_max)
print("inserted after _handle_service_approve (line", sa_end, ")")
print("Handler method count:", len(methods))
for m in ['_handle_complete', '_handle_service_push', '_handle_campaign_push',
          '_handle_campaign_create', '_handle_legacy_push', '_guard', '_handle_brief']:
    print("  ", m, ":", m in methods)
sync2 = next((c for c in tree2.body if isinstance(c, ast.FunctionDef) and c.name == '_sync_resolved_assets_to_strategy'), None)
print("_sync still module-level:", sync2 is not None and isinstance(tree2.body[tree2.body.index(sync2)], ast.FunctionDef))
