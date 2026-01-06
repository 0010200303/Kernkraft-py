import argparse
import subprocess
import sys
from pathlib import Path
import re

from lexer import Lexer
from parser import Parser
from ir_gen import IR_Generator

_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")

def _scan_imports(source_text: str) -> list[str]:
    out: list[str] = []
    for raw in source_text.splitlines():
        line = raw.split("//", 1)[0].split("#", 1)[0].strip()
        if not line:
            continue
        m = _IMPORT_RE.match(line)
        if m:
            out.append(m.group(1))
    return out

def _resolve_module_path(module_name: str, base_dir: Path) -> Path:
    cand = base_dir / f"{module_name}.kk"
    if cand.exists():
        return cand
    cand2 = Path(f"{module_name}.kk")
    if cand2.exists():
        return cand2
    raise FileNotFoundError(f"module not found: {module_name} (looked for {cand} and {cand2})")

def _compile_module_ir(
    source_path: Path,
    target_triple: str,
    compiled: dict[str, "ir.Module"],
    visiting: set[str],
) -> "ir.Module":
    from llvmlite import ir

    module_name = source_path.stem
    if module_name in compiled:
        return compiled[module_name]
    if module_name in visiting:
        raise RuntimeError(f"cyclic import detected at module: {module_name}")

    visiting.add(module_name)

    data = source_path.read_text(encoding="utf-8")
    deps: dict[str, ir.Module] = {}
    for dep_name in _scan_imports(data):
        dep_path = _resolve_module_path(dep_name, source_path.parent)
        deps[dep_name] = _compile_module_ir(dep_path, target_triple, compiled, visiting)

    tokens = Lexer(data).tokenize()
    ast = Parser(tokens).parse()
    mod = IR_Generator(ast, module_name, target_triple).generate_module(imports=deps)

    compiled[module_name] = mod
    visiting.remove(module_name)
    return mod

def compile_to_llvm_ir(source_path: Path, target_triple: str, imports: dict[str, "ir.Module"] | None = None) -> str:
    data = source_path.read_text(encoding="utf-8")
    tokens = Lexer(data).tokenize()
    ast = Parser(tokens).parse()

    module_name = source_path.stem
    return IR_Generator(ast, module_name, target_triple).generate(imports=imports or {})

def _compile_project(
    main_path: Path,
    target_triple: str,
) -> tuple[str, dict[str, "ir.Module"]]:
    from llvmlite import ir  # type: ignore

    compiled: dict[str, ir.Module] = {}
    visiting: set[str] = set()

    main_src = main_path.read_text(encoding="utf-8")
    deps: dict[str, ir.Module] = {}
    for dep_name in _scan_imports(main_src):
        dep_path = _resolve_module_path(dep_name, main_path.parent)
        deps[dep_name] = _compile_module_ir(dep_path, target_triple, compiled, visiting)

    main_ir = compile_to_llvm_ir(main_path, target_triple, imports=deps)
    return main_ir, compiled

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
        llvm_ir, compiled_modules = _compile_project(in_path, args.target)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(llvm_ir, encoding="utf-8")

        dep_out_dir = out_path.parent
        for name, mod in compiled_modules.items():
            (dep_out_dir / f"{name}.ll").write_text(str(mod), encoding="utf-8")
        return 0

    # emit exe
    ll_path = default_ll
    llvm_ir, compiled_modules = _compile_project(in_path, args.target)
    ll_path.write_text(llvm_ir, encoding="utf-8")

    # Write dependency IR files into out_dir for linking
    dep_ll_paths: list[Path] = []
    for name, mod in compiled_modules.items():
        p = out_dir / f"{name}.ll"
        p.write_text(str(mod), encoding="utf-8")
        dep_ll_paths.append(p)

    exe_path = Path(args.output) if args.output else default_exe
    exe_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run([args.clang, str(ll_path), *[str(p) for p in dep_ll_paths], "-o", str(exe_path)], check=True)
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
