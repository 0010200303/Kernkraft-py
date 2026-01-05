import argparse
import subprocess
import sys
from pathlib import Path

from lexer import Lexer
from parser import Parser
from ir_gen import IR_Generator

def compile_to_llvm_ir(source_path: Path, target_triple: str) -> str:
    data = source_path.read_text(encoding="utf-8")
    tokens = Lexer(data).tokenize()
    ast = Parser(tokens).parse()

    module_name = source_path.stem
    return IR_Generator(ast, module_name, target_triple).generate(imports={})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kkpy", description="Kernkraft compiler")
    parser.add_argument("input", help="Input .kk file")
    parser.add_argument("--emit", choices=["ll", "exe"], default="exe", help="Output type")
    parser.add_argument("-o", "--output", default=None, help="Output path (file). Defaults to ./bin/<name> or ./bin/<name>.ll")
    parser.add_argument("--out-dir", default="build", help="Output directory (used if -o/--output is not set)")
    parser.add_argument("--target", default="x86_64-pc-linux-gnu", help="LLVM target triple")
    parser.add_argument("--clang", default="clang", help="Clang executable to use for linking")
    parser.add_argument("--run", action="store_true", help="Run produced executable (only with --emit=exe)")
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"error: input not found: {in_path}", file=sys.stderr)
        return 2
    if in_path.suffix != ".kk":
        print(f"error: expected a .kk file, got: {in_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = in_path.stem
    default_ll = out_dir / f"{base_name}.ll"
    default_exe = out_dir / base_name

    # only emit ir
    if args.emit == "ll" or args.emit == "ir":
        out_path = Path(args.output) if args.output else default_ll
        llvm_ir = compile_to_llvm_ir(in_path, args.target)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(llvm_ir, encoding="utf-8")
        return 0

    # emit exe
    ll_path = default_ll
    llvm_ir = compile_to_llvm_ir(in_path, args.target)
    ll_path.write_text(llvm_ir, encoding="utf-8")

    exe_path = Path(args.output) if args.output else default_exe
    exe_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run([args.clang, str(ll_path), "-o", str(exe_path)], check=True)
    except FileNotFoundError:
        print(f"error: clang not found: {args.clang}", file=sys.stderr)
        return 127
    except subprocess.CalledProcessError as e:
        return e.returncode

    if args.run:
        try:
            subprocess.run([str(exe_path)], check=True)
            print()
        except subprocess.CalledProcessError as e:
            return e.returncode

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
