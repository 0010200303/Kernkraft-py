# Kernkraft Python Compiler

A small “toy” compiler pipeline implemented in Python to get the Kernkraft compiler architecture working end-to-end.

> **Important:** This project exists only to bootstrap the **very first** version of the Kernkraft compiler *written in Kernkraft itself* (self-hosting).
> As a result, it is intentionally **very limited**, likely **buggy**, and **unoptimized**. Do not expect good diagnostics, performance, or complete language coverage.

This project focuses on the classic compiler stages:

- **Lexing**: source text → tokens
- **Parsing**: tokens → AST
- **IR generation**: AST → LLVM IR (via `llvmlite`)

## Project layout

The package is intentionally flat (see `pyproject.toml`):

- `main.py` — CLI entry point (`kkpy`)
- `lexer.py` — tokenizer / lexical analysis
- `tokens.py` — token kinds + token data structures
- `parser.py` — parser building an AST from tokens
- `ast_nodes.py` — AST node definitions
- `ir_gen.py` — LLVM IR generation using `llvmlite`

## Install

From the repo root:

```bash
pipx install -e .
```

This installs the `kkpy` command (configured in `pyproject.toml`).

## Usage

Run the compiler via the installed script:

```bash
kkpy path/to/source.kk
```

**Output:** depends on the current implementation in `main.py` / `ir_gen.py` (commonly printing LLVM IR, or writing an IR file). Check `main.py` to see the currently supported flags/behaviors.

## What’s supported?

This is a “get the pipeline working” compiler, so expect limitations. The supported syntax/semantics are defined by the current lexer/parser rules and AST/IR coverage.

To understand exactly what the language supports right now:
- skim `tokens.py` for token kinds
- skim `parser.py` for grammar constructs
- skim `ir_gen.py` for what AST nodes can be lowered to LLVM IR

## Development notes

- Python: **3.10+**
- Backend: **LLVM IR via `llvmlite`**
