import os
from lexer import Lexer
from parser import Parser
from ir_gen import IR_Generator

MAIN = "tust10"
MODULES = []

def print_tokens(tokens: list) -> None:
    for token in tokens:
        print(token)

def generate_module(name: str) -> None:
    with open(f"tusts/{name}.kk", "r", encoding="utf-8") as f:
        data = f.read()

        tokens = Lexer(data).tokenize()
        ast = Parser(tokens).parse()

        module = IR_Generator(
            ast,
            name,
            "x86_64-pc-windows-msvc"
        ).generate_module()
        return module

if __name__ == "__main__":
    modules = {}
    for module_name in MODULES:
        module = generate_module(module_name)
        modules[module_name] = module

        with open(f"bin/{module_name}.ll", "w", encoding="utf-8") as out:
            out.write(str(module))

    with open(f"tusts/{MAIN}.kk", "r", encoding="utf-8") as f:
        data = f.read()

        tokens = Lexer(data).tokenize()
        ast = Parser(tokens).parse()

        main = IR_Generator(
            ast,
            MAIN,
            "x86_64-pc-windows-msvc"
        ).generate(modules)

        with open(f"bin/{MAIN}.ll", "w", encoding="utf-8") as out:
            out.write(str(main))

        linkable_modules = " ".join([f"bin/{m}.ll" for m in MODULES])
        os.system(f"clang bin/{MAIN}.ll {linkable_modules} -o bin/{MAIN}")

        print()
        os.system(f"./bin/{MAIN}")
        print()

