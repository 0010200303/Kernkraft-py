import typing
import sys
from llvmlite import ir
from ast_nodes import *

# types
i8 = ir.IntType(8)
i32 = ir.IntType(32)

main_type = ir.FunctionType(i32, [i32])
printf_type = ir.FunctionType(i32, [ir.PointerType(i8)], var_arg=True)
malloc_type = ir.FunctionType(ir.PointerType(i8), [i32])
free_type = ir.FunctionType(ir.VoidType(), [ir.PointerType(i8)])
calloc_type = ir.FunctionType(ir.PointerType(i8), [i32, i32])
realloc_type = ir.FunctionType(ir.PointerType(i8), [ir.PointerType(i8), i32])
open_type = ir.FunctionType(i32, [ir.PointerType(i8), i32, i32])
read_type = ir.FunctionType(i32, [i32, ir.PointerType(i8), i32])
write_type = ir.FunctionType(i32, [i32, ir.PointerType(i8), i32])
close_type = ir.FunctionType(i32, [i32])

class IR_Generator:
    def __init__(
        self,
        ast_root: ExpressionsNode,
        module_name: str,
        module_triple: str
    ):
        self.ast_root = ast_root
        self.module_name = module_name
        self.module_triple = module_triple

    def _init_module(self, module: ir.Module) -> None:
        module.triple = self.module_triple
        module.module_name = self.module_name

        # sloppy, no scoping
        if not hasattr(module, "symbol_table"):
            module.symbol_table = {}

        if "printf" not in module.globals:
            ir.Function(module, printf_type, name="printf").linkage = "external"
        if "malloc" not in module.globals:
            ir.Function(module, malloc_type, name="malloc").linkage = "external"
        if "free" not in module.globals:
            ir.Function(module, free_type, name="free").linkage = "external"
        if "calloc" not in module.globals:
            ir.Function(module, calloc_type, name="calloc").linkage = "external"
        if "realloc" not in module.globals:
            ir.Function(module, realloc_type, name="realloc").linkage = "external"
        if "open" not in module.globals:
            ir.Function(module, open_type, name="open").linkage = "external"
        if "read" not in module.globals:
            ir.Function(module, read_type, name="read").linkage = "external"
        if "write" not in module.globals:
            ir.Function(module, write_type, name="write").linkage = "external"
        if "close" not in module.globals:
            ir.Function(module, close_type, name="close").linkage = "external"

        if "errno_ptr" not in module.globals:
            errno_loc_ty = ir.FunctionType(ir.PointerType(i32), [])
            if "__errno_location" not in module.globals:
                ir.Function(module, errno_loc_ty, name="__errno_location").linkage = "external"

            fn = ir.Function(module, ir.FunctionType(ir.PointerType(i32), []), name="errno_ptr")
            fn.linkage = "internal"
            b = ir.IRBuilder(fn.append_basic_block("entry"))
            p = b.call(module.globals["__errno_location"], [])
            b.ret(p)

        if "get_errno" not in module.globals:
            fn = ir.Function(module, ir.FunctionType(i32, []), name="get_errno")
            fn.linkage = "internal"
            b = ir.IRBuilder(fn.append_basic_block("entry"))
            p = b.call(module.globals["errno_ptr"], [])
            v = b.load(p)
            b.ret(v)

    def create_builder(
        self,
        module: ir.Module,
        func_name: str = "__entry",
        func_type: typing.Optional[ir.FunctionType] = None,
        linkage: str = "internal",
    ) -> ir.IRBuilder:
        if func_type is None:
            func_type = ir.FunctionType(ir.VoidType(), [])

        func = module.globals.get(func_name)
        if func is None:
            func = ir.Function(module, func_type, name=func_name)
            func.linkage = linkage

        block = func.append_basic_block("entry")
        builder = ir.IRBuilder(block)
        return builder

    def generate(self, imports: typing.Dict[str, ir.Module]) -> str:
        module = ir.Module(name=self.module_name)
        self._init_module(module)

        # main func
        main_func = ir.Function(module, main_type, "main")
        block = main_func.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        self.ast_root.generate_ir(builder, module, imports)

        if not builder.block.is_terminated:
            builder.ret(ir.Constant(i32, 0))
        return str(module)

    def generate_module(self) -> ir.Module:
        module = ir.Module(name=self.module_name)
        self._init_module(module)

        builder = self.create_builder(module, f"{self.module_name}$__entry")

        self.ast_root.generate_ir(builder, module)

        if not builder.block.is_terminated:
            builder.ret_void()

        return module
