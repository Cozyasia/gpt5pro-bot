"""Read-only AST audit of payment wiring. Never imports main.py or prints secrets."""
import ast
from pathlib import Path

tree=ast.parse(Path("main.py").read_text(encoding="utf-8"),filename="main.py")
names={"on_successful_payment","_poll_yoo_credit_payment","_poll_yoo_subscription_payment","_poll_crypto_invoice","_poll_crypto_sub_invoice"}
for node in ast.walk(tree):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
        print("DEFINITION",node.name,"line",node.lineno)
    if isinstance(node,ast.Call):
        f=node.func
        name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else ""
        if name in {"patch_runtime","add_handler","register_handlers"}:
            details=[]
            for arg in node.args:
                if isinstance(arg,ast.Call):
                    details.append(arg.func.id if isinstance(arg.func,ast.Name) else getattr(arg.func,"attr","call"))
                elif isinstance(arg,ast.Name):
                    details.append(arg.id)
            print("CALL",name,"line",node.lineno,"args",",".join(details[:4]))
    if isinstance(node,ast.ImportFrom) and node.module and ("payment" in node.module or "credit_store" in node.module):
        print("IMPORT",node.module,"line",node.lineno,"names",",".join(a.name for a in node.names))
    if isinstance(node,ast.Assign):
        for target in node.targets:
            if isinstance(target,ast.Attribute) and target.attr in names:
                print("ASSIGN",target.attr,"line",node.lineno)
