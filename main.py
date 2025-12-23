import os
from lexer import Lexer
from parser import Parser
from ir_gen import IR_Generator

def print_tokens(tokens: list) -> None:
    for token in tokens:
        print(token)

if __name__ == "__main__":
    with open("tust_linked_list.kk", "r", encoding="utf-8") as f:
        data = f.read()

        # tokenize
        tokens = Lexer(data).tokenize()
        print_tokens(tokens)

        # parse
        ast = Parser(tokens).parse()
        print(ast)

        # generate IR
        ir = IR_Generator(
            ast,
            "tust_module",
            "x86_64-pc-windows-msvc"
        ).generate()
        with open("bin/tust.ll", "w", encoding="utf-8") as f:
            f.write(ir)

        # link IR using clang
        os.system("clang bin/tust.ll -o bin/tust")

        # run the generated executable
        print()
        os.system("./bin/tust")
        print()
