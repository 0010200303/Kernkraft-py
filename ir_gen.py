import typing
from collections import ChainMap
from llvmlite import ir
from ast_nodes import *

# types
i8 = ir.IntType(8)
i32 = ir.IntType(32)
i8p = ir.PointerType(i8)

ZERO = ir.Constant(i32, 0)
ONE = ir.Constant(i32, 1)
TWO = ir.Constant(i32, 2)

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

    def _init_string(self, module: ir.Module) -> None:
        ctx = module.context

        str_ty = ctx.identified_types.get("str")
        if str_ty is None:
            str_ty = ctx.get_identified_type("str")
        if getattr(str_ty, "is_opaque", False) or not getattr(str_ty, "elements", None):
            str_ty.set_body(i8p, i32, i32)
        
        type_from_name_mapping["str"] = str_ty
        name_from_type_mapping[str_ty] = "str"

        if "str_init" not in module.globals:
            fn = ir.Function(module, ir.FunctionType(ir.VoidType(), [ir.PointerType(str_ty)]), name="str_init")
            fn.linkage = "internal"
            (s_arg,) = fn.args
            s_arg.name = "s"
            b = ir.IRBuilder(fn.append_basic_block("entry"))

            data_ptr = b.gep(s_arg, [ZERO, ZERO], name=".ptr.data")
            len_ptr = b.gep(s_arg, [ZERO, ONE], name=".ptr.len")
            cap_ptr = b.gep(s_arg, [ZERO, TWO], name=".ptr.cap")

            b.store(ir.Constant(i8p, None), data_ptr)
            b.store(ZERO, len_ptr)
            b.store(ZERO, cap_ptr)
            b.ret_void()

        # Convert 'str*' to a default null terminated C string
        if ".kk.empty_cstr" not in module.globals:
            empty_arr = ir.Constant(ir.ArrayType(i8, 1), bytearray(b"\x00"))
            g = ir.GlobalVariable(module, empty_arr.type, name=".kk.empty_cstr")
            g.linkage = "private"
            g.global_constant = True
            g.unnamed_addr = True
            g.initializer = empty_arr

        if "str_to_cstr" not in module.globals:
            fn = ir.Function(module, ir.FunctionType(i8p, [ir.PointerType(str_ty)]), name="str_to_cstr")
            fn.linkage = "internal"
            (s_arg,) = fn.args
            s_arg.name = "s"

            entry = fn.append_basic_block("entry")
            is_null_bb = fn.append_basic_block("is_null")
            has_data_bb = fn.append_basic_block("has_data")

            b = ir.IRBuilder(entry)

            data_ptr_p = b.gep(s_arg, [ZERO, ZERO], name=".ptr.data")
            len_ptr_p = b.gep(s_arg, [ZERO, ONE], name=".ptr.len")
            data = b.load(data_ptr_p, name=".data")
            length = b.load(len_ptr_p, name=".len")

            is_null = b.icmp_signed("==", data, ir.Constant(i8p, None), name=".data.is_null")
            b.cbranch(is_null, is_null_bb, has_data_bb)

            b.position_at_start(is_null_bb)
            empty_g = module.globals[".kk.empty_cstr"]
            empty_p = b.gep(empty_g, [ZERO, ZERO], name=".empty.ptr")
            b.ret(empty_p)

            b.position_at_start(has_data_bb)
            endp = b.gep(data, [length], name=".end.ptr")
            b.store(ir.Constant(i8, 0), endp)
            b.ret(data)

        if "str_from_bytes" not in module.globals:
            fn = ir.Function(module, ir.FunctionType(str_ty, [i8p, i32]), name="str_from_bytes")
            fn.linkage = "internal"
            src_arg, len_arg = fn.args
            src_arg.name = "src"
            len_arg.name = "len"

            entry = fn.append_basic_block("entry")
            loop = fn.append_basic_block("loop")
            body = fn.append_basic_block("body")
            done = fn.append_basic_block("done")

            b = ir.IRBuilder(entry)

            # malloc(len + 1)
            nbytes = b.add(len_arg, ONE, name=".nbytes")
            raw = b.call(module.globals["malloc"], [nbytes], name=".call.malloc")
            dst = b.bitcast(raw, i8p, name=".dst")

            # i = 0
            i_ptr = b.alloca(i32, name=".i")
            b.store(ZERO, i_ptr)
            b.branch(loop)

            b.position_at_start(loop)
            i_val = b.load(i_ptr, name=".i.val")
            cond = b.icmp_signed("<", i_val, len_arg, name=".i.lt.len")
            b.cbranch(cond, body, done)

            b.position_at_start(body)
            src_i = b.gep(src_arg, [i_val], name=".src.i")
            byte = b.load(src_i, name=".byte")
            dst_i = b.gep(dst, [i_val], name=".dst.i")
            b.store(byte, dst_i)
            b.store(b.add(i_val, ONE, name=".i.inc"), i_ptr)
            b.branch(loop)

            b.position_at_start(done)
            endp = b.gep(dst, [len_arg], name=".dst.end")
            b.store(ir.Constant(i8, 0), endp)

            out_ptr = b.alloca(str_ty, name=".out")
            out_data_p = b.gep(out_ptr, [ZERO, ZERO], name=".out.data.p")
            out_len_p = b.gep(out_ptr, [ZERO, ONE], name=".out.len.p")
            out_cap_p = b.gep(out_ptr, [ZERO, TWO], name=".out.cap.p")

            b.store(dst, out_data_p)
            b.store(len_arg, out_len_p)
            b.store(len_arg, out_cap_p)

            b.ret(b.load(out_ptr, name=".out.val"))

        if "str_cmp" not in module.globals:
            fn = ir.Function(module, ir.FunctionType(i32, [ir.PointerType(str_ty), ir.PointerType(str_ty)]), name="str_cmp")
            fn.linkage = "internal"
            a_arg, b_arg = fn.args
            a_arg.name = "a"
            b_arg.name = "b"

            entry = fn.append_basic_block("entry")
            loop = fn.append_basic_block("loop")
            body = fn.append_basic_block("body")
            inc_bb = fn.append_basic_block("inc")
            diff_bb = fn.append_basic_block("diff")
            after = fn.append_basic_block("after")

            b = ir.IRBuilder(entry)

            a_data_p = b.gep(a_arg, [ZERO, ZERO], name=".a.data.p")
            a_len_p  = b.gep(a_arg, [ZERO, ONE],  name=".a.len.p")
            b_data_p = b.gep(b_arg, [ZERO, ZERO], name=".b.data.p")
            b_len_p  = b.gep(b_arg, [ZERO, ONE],  name=".b.len.p")

            a_data = b.load(a_data_p, name=".a.data")
            a_len  = b.load(a_len_p,  name=".a.len")
            b_data = b.load(b_data_p, name=".b.data")
            b_len  = b.load(b_len_p,  name=".b.len")

            a_lt_b = b.icmp_signed("<", a_len, b_len, name=".a_lt_b")
            min_len = b.select(a_lt_b, a_len, b_len, name=".minlen")

            i_ptr = b.alloca(i32, name=".i")
            b.store(ZERO, i_ptr)
            b.branch(loop)

            b.position_at_start(loop)
            i_val = b.load(i_ptr, name=".i.val")
            cont = b.icmp_signed("<", i_val, min_len, name=".i.lt.min")
            b.cbranch(cont, body, after)

            b.position_at_start(body)
            a_i_p = b.gep(a_data, [i_val], name=".a.i.p")
            b_i_p = b.gep(b_data, [i_val], name=".b.i.p")
            a_ch = b.zext(b.load(a_i_p, name=".a.ch"), i32, name=".a.ch32")
            b_ch = b.zext(b.load(b_i_p, name=".b.ch"), i32, name=".b.ch32")
            neq = b.icmp_signed("!=", a_ch, b_ch, name=".neq")
            b.cbranch(neq, diff_bb, inc_bb)

            b.position_at_start(diff_bb)
            b.ret(b.sub(a_ch, b_ch, name=".diff"))

            b.position_at_start(inc_bb)
            b.store(b.add(i_val, ONE, name=".i.inc"), i_ptr)
            b.branch(loop)

            b.position_at_start(after)
            b.ret(b.sub(a_len, b_len, name=".len.diff"))

        if "str_append_str" not in module.globals:
            fn = ir.Function(
                module,
                ir.FunctionType(ir.VoidType(), [ir.PointerType(str_ty), ir.PointerType(str_ty)]),
                name="str_append_str",
            )
            fn.linkage = "internal"
            dst_arg, src_arg = fn.args
            dst_arg.name = "dst"
            src_arg.name = "src"

            entry = fn.append_basic_block("entry")
            grow = fn.append_basic_block("grow")
            copy_loop = fn.append_basic_block("copy_loop")
            copy_body = fn.append_basic_block("copy_body")
            done = fn.append_basic_block("done")

            b = ir.IRBuilder(entry)

            dst_data_p = b.gep(dst_arg, [ZERO, ZERO], name=".dst.data.p")
            dst_len_p = b.gep(dst_arg, [ZERO, ONE], name=".dst.len.p")
            dst_cap_p = b.gep(dst_arg, [ZERO, TWO], name=".dst.cap.p")

            src_data_p = b.gep(src_arg, [ZERO, ZERO], name=".src.data.p")
            src_len_p = b.gep(src_arg, [ZERO, ONE], name=".src.len.p")

            dst_data = b.load(dst_data_p, name=".dst.data")
            dst_len = b.load(dst_len_p, name=".dst.len")
            dst_cap = b.load(dst_cap_p, name=".dst.cap")

            src_data = b.load(src_data_p, name=".src.data")
            src_len = b.load(src_len_p, name=".src.len")

            new_len = b.add(dst_len, src_len, name=".new.len")
            need_grow = b.icmp_signed(">", new_len, dst_cap, name=".need.grow")
            b.cbranch(need_grow, grow, copy_loop)

            b.position_at_start(grow)
            # new_cap = max(dst_cap*2 (or 1), new_len)
            cap0 = b.icmp_signed("==", dst_cap, ZERO, name=".cap0")
            cap2 = b.mul(dst_cap, ir.Constant(i32, 2), name=".cap2")
            cap_base = b.select(cap0, ONE, cap2, name=".cap.base")
            cap_lt_need = b.icmp_signed("<", cap_base, new_len, name=".cap.lt.need")
            new_cap = b.select(cap_lt_need, new_len, cap_base, name=".cap.new")

            # realloc(data, new_cap + 1)
            nbytes = b.add(new_cap, ONE, name=".nbytes")
            old_i8p = b.bitcast(dst_data, ir.PointerType(i8), name=".old.i8p")
            raw = b.call(module.globals["realloc"], [old_i8p, nbytes], name=".call.realloc")
            new_data = b.bitcast(raw, ir.PointerType(i8), name=".new.data")

            b.store(new_data, dst_data_p)
            b.store(new_cap, dst_cap_p)
            b.branch(copy_loop)

            b.position_at_start(copy_loop)
            # Refresh in case we grew
            dst_data2 = b.load(dst_data_p, name=".dst.data2")
            dst_len2 = b.load(dst_len_p, name=".dst.len2")
            src_len2 = b.load(src_len_p, name=".src.len2")
            src_data2 = b.load(src_data_p, name=".src.data2")

            i_ptr = b.alloca(i32, name=".i")
            b.store(ZERO, i_ptr)
            b.branch(copy_body)

            b.position_at_start(copy_body)
            i_val = b.load(i_ptr, name=".i.val")
            cont = b.icmp_signed("<", i_val, src_len2, name=".i.lt.srclen")
            with b.if_else(cont) as (then, otherwise):
                with then:
                    src_i = b.gep(src_data2, [i_val], name=".src.i")
                    ch = b.load(src_i, name=".ch")
                    dst_i = b.gep(dst_data2, [b.add(dst_len2, i_val, name=".dst.off")], name=".dst.i")
                    b.store(ch, dst_i)
                    b.store(b.add(i_val, ONE, name=".i.inc"), i_ptr)
                    b.branch(copy_body)
                with otherwise:
                    b.branch(done)
            b.unreachable()

            b.position_at_start(done)
            b.store(new_len, dst_len_p)
            endp = b.gep(dst_data2, [new_len], name=".dst.end")
            b.store(ir.Constant(i8, 0), endp)
            b.ret_void()

        if "str_append_char" not in module.globals:
            fn = ir.Function(
                module,
                ir.FunctionType(ir.VoidType(), [ir.PointerType(str_ty), i8]),
                name="str_append_char",
            )
            fn.linkage = "internal"
            dst_arg, ch_arg = fn.args
            dst_arg.name = "dst"
            ch_arg.name = "ch"

            entry = fn.append_basic_block("entry")
            grow = fn.append_basic_block("grow")
            append_bb = fn.append_basic_block("append")
            
            b = ir.IRBuilder(entry)

            dst_data_p = b.gep(dst_arg, [ZERO, ZERO], name=".dst.data.p")
            dst_len_p = b.gep(dst_arg, [ZERO, ONE], name=".dst.len.p")
            dst_cap_p = b.gep(dst_arg, [ZERO, TWO], name=".dst.cap.p")

            dst_data = b.load(dst_data_p, name=".dst.data")
            dst_len = b.load(dst_len_p, name=".dst.len")
            dst_cap = b.load(dst_cap_p, name=".dst.cap")

            new_len = b.add(dst_len, ONE, name=".new.len")
            need_grow = b.icmp_signed(">", new_len, dst_cap, name=".need.grow")
            b.cbranch(need_grow, grow, append_bb)

            # grow
            b.position_at_start(grow)
            cap0 = b.icmp_signed("==", dst_cap, ZERO, name=".cap0")
            cap2 = b.mul(dst_cap, ir.Constant(i32, 2), name=".cap2")
            cap_base = b.select(cap0, ONE, cap2, name=".cap.base")
            cap_lt_need = b.icmp_signed("<", cap_base, new_len, name=".cap.lt.need")
            new_cap = b.select(cap_lt_need, new_len, cap_base, name=".cap.new")

            nbytes = b.add(new_cap, ONE, name=".nbytes")
            old_i8p = b.bitcast(dst_data, ir.PointerType(i8), name=".old.i8p")
            raw = b.call(module.globals["realloc"], [old_i8p, nbytes], name=".call.realloc")
            new_data = b.bitcast(raw, ir.PointerType(i8), name=".new.data")

            b.store(new_data, dst_data_p)
            b.store(new_cap, dst_cap_p)
            b.branch(append_bb)

            # append
            b.position_at_start(append_bb)
            dst_data2 = b.load(dst_data_p, name=".dst.data2")
            dst_len2 = b.load(dst_len_p, name=".dst.len2")

            dest_ptr = b.gep(dst_data2, [dst_len2], name=".dst.append.ptr")
            b.store(ch_arg, dest_ptr)
            b.store(new_len, dst_len_p)
            endp = b.gep(dst_data2, [new_len], name=".dst.end")
            b.store(ir.Constant(i8, 0), endp)
            b.ret_void()

    def _init_module(self, module: ir.Module) -> None:
        module.triple = self.module_triple
        module.module_name = self.module_name

        # block scopring using ChainMap
        if not hasattr(module, "symbol_table") or module.symbol_table is None:
            module.symbol_table = ChainMap({})

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
        
        self._init_string(module)

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

    def generate_module(self, imports: typing.Optional[typing.Dict[str, ir.Module]] = None) -> ir.Module:
        module = ir.Module(name=self.module_name)
        self._init_module(module)

        builder = self.create_builder(module, f"{self.module_name}$__entry")

        self.ast_root.generate_ir(builder, module, imports or {})

        if not builder.block.is_terminated:
            builder.ret_void()

        return module
