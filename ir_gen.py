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

    def generate(self) -> str:
        module = ir.Module(name=self.module_name)
        module.triple = self.module_triple

        # sloppy, no scoping
        if not hasattr(module, "symbol_table"):
            module.symbol_table = {}

        # printf
        printf_func = ir.Function(module, printf_type, name="printf")
        printf_func.linkage = "external"

        # malloc
        malloc_func = ir.Function(module, malloc_type, name="malloc")
        malloc_func.linkage = "external"

        # free
        free_func = ir.Function(module, free_type, name="free")
        free_func.linkage = "external"

        # calloc
        calloc_func = ir.Function(module, calloc_type, name="calloc")
        calloc_func.linkage = "external"

        # realloc
        realloc_func = ir.Function(module, realloc_type, name="realloc")
        realloc_func.linkage = "external"

        # main func
        main_func = ir.Function(module, main_type, "main")
        block = main_func.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        # generate IR for AST
        self.ast_root.generate_ir(builder, module)

        builder.ret(ir.Constant(i32, 0))
        return str(module)
