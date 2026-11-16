"""AST-only inspection of exact payment handler registrations and patch order."""
import ast
from pathlib import Path
tree=ast.parse(Path("main.py").read_text(encoding="utf-8"))
def fmt(n):
    if isinstance(n,ast.Name): return n.id
    if isinstance(n,ast.Attribute): return fmt(n.value)+"."+n.attr
    if isinstance(n,ast.Call): return fmt(n.func)+"("+",".join(fmt(x) for x in n.args[:3])+")"
    if isinstance(n,ast.Constant): return repr(n.value)[:40]
    return type(n).__name__
for n in ast.walk(tree):
    if isinstance(n,ast.Call):
        f=fmt(n.func)
        if f.endswith(".add_handler"):
            if any(isinstance(x,ast.Call) and fmt(x.func) in ("PreCheckoutQueryHandler","MessageHandler") for x in n.args):
                print("HANDLER",n.lineno,fmt(n.args[0]))
        if f.endswith("patch_runtime") or f.endswith("install_production_patches"):
            print("PATCH",n.lineno,fmt(n))
    if isinstance(n,(ast.Import,ast.ImportFrom)):
        if isinstance(n,ast.ImportFrom) and n.module and ("payment" in n.module or "prod" in n.module):
            print("IMPORT",n.lineno,n.module,",".join(a.name for a in n.names)[:160])
    if isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name) and t.id in ("on_successful_payment","_poll_yoo_credit_payment"):
                print("REBIND",n.lineno,t.id,fmt(n.value))
