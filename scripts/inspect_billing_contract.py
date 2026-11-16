"""Read-only AST inventory of billing call sites. No application imports."""
import ast
import pathlib
import sys

NAMES = {"_yoo_create_credit_payment", "_poll_yoo_credit_payment", "_usd_to_credits", "_credits_to_usd", "_credits_fmt_from_usd", "_user_balance_add", "_user_balance_get", "_wallet_total_add", "_wallet_total_take", "_create_credit_payment", "_credit_payment"}
CONFIG = {"USD_RUB", "CREDIT_RUB_VALUE", "CREDIT_USD_VALUE", "NEYRONIX_USD_CREDITS_ENABLED"}
def inspect(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.name in NAMES or "credit_payment" in node.name):
            print("DEF", node.name, node.lineno, node.end_lineno)
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in NAMES:
                print("CALL", name, node.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in CONFIG:
                    print("CONFIG", target.id, node.lineno)
if __name__ == "__main__":
    inspect(sys.argv[1] if len(sys.argv)>1 else "main.py")
