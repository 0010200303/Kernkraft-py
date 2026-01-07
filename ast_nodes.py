import abc
import typing
from llvmlite import ir

i8 = ir.IntType(8)
i32 = ir.IntType(32)
i8p = ir.PointerType(i8)

ZERO = ir.Constant(i32, 0)
ONE = ir.Constant(i32, 1)
TWO = ir.Constant(i32, 2)

type_from_name_mapping = {
    "i32": i32,
    "bool": ir.IntType(1),
    "void": ir.VoidType(),
    "char": i8,
    "i8": i8,
}

name_from_type_mapping = {
    i32: "i32",
    i8p: "i8p",
    ir.IntType(1): "i1/bool",
    ir.VoidType(): "void",
    i8: "i8/char",
}

reserved_types = set()

reserved_keywords = {
    "struct",
    "union",
    "func",
    "len",
}

def _is_scalar_type(ty: ir.Type) -> bool:
    # Scalars are values typically loaded/stored directly (vs aggregates/arrays)
    return isinstance(ty, (ir.IntType, ir.PointerType))

def _mangle_type_for_symbol(ty: ir.Type) -> str:
    # Keep deterministic and C-symbol-ish.
    s = name_from_type_mapping.get(ty, str(ty))
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    return "".join(out)

def _sizeof_as_i32(builder: ir.IRBuilder, element_type: ir.Type) -> ir.Value:
    null_tptr = ir.Constant(ir.PointerType(element_type), None)
    one_past = builder.gep(null_tptr, [ONE], name=".sizeof.gep")
    return builder.ptrtoint(one_past, i32, name=".sizeof")

class ASTNode(abc.ABC):
    _type: ir.Type = None

    @abc.abstractmethod
    def __repr__(self, level: int = 0) -> str:
        pass

    @abc.abstractmethod
    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Type:
        pass

class TrackedNode(ASTNode):
    def __init__(self, line: int, column: int):
        super().__init__()
        self.line = line
        self.column = column

class ExpressionsNode(TrackedNode):
    def __init__(self, line: int, column: int):
        super().__init__(line, column)
        self.children: list[ASTNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"ExpressionsNode() at {self.line}:{self.column}\n"
        for child in self.children:
            ret += child.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module, imports: typing.Dict[str, ir.Module] = {}) -> None:
        builder.comment(f"Expressions originating at {self.line}:{self.column}")

        set(type_from_name_mapping.keys())

        for _import in imports.values():
            # import types
            for type_name, type in _import.context.identified_types.items():
                module.context.identified_types[type_name] = type
                type_from_name_mapping[type_name] = type
                name_from_type_mapping[type] = type_name

            # import functions
            for function_name, function in _import.globals.items():
                if not isinstance(function, ir.Function) or function.linkage != "":
                    continue

                imported_function = ir.Function(module, function.function_type, name=function_name)
                imported_function.linkage = "external"

        for child in self.children:
            child.generate_ir(builder, module)

class CallNode(TrackedNode):
    def __init__(self, name: str, line: int, column: int):
        super().__init__(line, column)
        self.name = name
        self.args: list[ASTNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"CallNode({self.name}) at {self.line}:{self.column}\n"
        for arg in self.args:
            ret += arg.__repr__(level + 1)
        return ret

    def coerce_call_arg(self,
                        builder: ir.IRBuilder,
                        value: ir.Value,
                        exspected_ty: ir.Type,
                        arg_index: int) -> ir.Value:
        if value.type == exspected_ty:
            return value

        if isinstance(exspected_ty, ir.Aggregate) and isinstance(value.type, ir.PointerType):
            if value.type.pointee == exspected_ty:
                return builder.load(value, name=f".load.agg.arg.{arg_index}")

        # string to C-string
        if exspected_ty == i8p:
            str_ty = type_from_name_mapping.get("str")
            if str_ty is not None:
                # str: extract data field
                if value.type == str_ty:
                    return builder.extract_value(value, 0, name=f".str.data.arg.{arg_index}")

                # str*: load data field
                if isinstance(value.type, ir.PointerType) and value.type.pointee == str_ty:
                    data_ptr_ptr = builder.gep(value, [ZERO, ZERO], name=f".ptr.str.data.arg.{arg_index}")
                    return builder.load(data_ptr_ptr, name=f".load.str.data.arg.{arg_index}")

        # array to pointer decay
        if isinstance(exspected_ty, ir.PointerType) and isinstance(value.type, ir.PointerType):
            if isinstance(value.type.pointee, ir.ArrayType) and value.type.pointee.element == exspected_ty.pointee:
                return builder.gep(value, [ZERO, ZERO], inbounds=True, name=f".decay.arg.{arg_index}")

        if isinstance(exspected_ty, ir.PointerType) and isinstance(exspected_ty.pointee, ir.Aggregate):
            if value.type == exspected_ty.pointee:
                pointee = exspected_ty.pointee

                if isinstance(pointee, ir.IdentifiedStructType):
                    name = pointee.name or ""
                    is_runtime_agg = (name == "str") or name.startswith("array.")
                    is_user_agg = ("$" in name) or getattr(pointee, "is_union", False)
                    if is_user_agg and not is_runtime_agg:
                        raise TypeError(
                            f"Call arg {arg_index} at {self.line}:{self.column}: "
                            f"user struct/union arguments must be passed by reference (an lvalue), not by value"
                        )

                tmp = builder.alloca(value.type, name=f".tmp.arg.{arg_index}")
                builder.store(value, tmp)
                return tmp

        exp = name_from_type_mapping.get(exspected_ty, str(exspected_ty))
        got = name_from_type_mapping.get(value.type, str(value.type))
        raise TypeError(f"Call arg {arg_index} type mismatch at {self.line}:{self.column}: expected {exp}, got {got}")

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.CallInstr:
        func = module.globals.get(self.name)
        if not func:
            func = module.globals.get(module.module_name + "$" + self.name)
        if not func:
            raise ValueError(f"Function {self.name} not found")

        func_ty = func.function_type
        sret = getattr(func, "_sret", False)
        if sret:
            fixed_param_tys = list(func_ty.args)[1:]
        else:
            fixed_param_tys = list(func_ty.args)

        if (not func_ty.var_arg) and (len(self.args) != len(fixed_param_tys)):
            raise ValueError(f"Function {self.name} expects {len(fixed_param_tys)} args, got {len(self.args)} at {self.line}:{self.column}")
        if len(self.args) < len(fixed_param_tys):
            raise ValueError(f"Function {self.name} expects at least {len(fixed_param_tys)} args, got {len(self.args)} at {self.line}:{self.column}")
        
        call_args: list[ir.Value] = []
        sret_slot = None
        if sret:
                sret_ty = getattr(func, "_sret_type")
                sret_slot = builder.alloca(sret_ty, name=".sret.slot")
                call_args.append(sret_slot)

        for idx, arg_node in enumerate(self.args):
            # by reference lvalue
            if getattr(func, "_kk_user", False) and idx < len(fixed_param_tys):
                exp_ty = fixed_param_tys[idx]

                if isinstance(exp_ty, ir.PointerType) and isinstance(exp_ty.pointee, ir.IntType):
                    lptr = None

                    if isinstance(arg_node, IdentifierNode):
                        name = arg_node.identifier
                        lptr = module.symbol_table.get(name)
                        if lptr is None:
                            lptr = next((a for a in builder.function.args if a.name == name), None)
                        if lptr is None:
                            lptr = module.globals.get(name)
                    elif isinstance(arg_node, AccessNode):
                        lptr = arg_node.generate_ptr(builder, module)

                    if lptr is None or lptr.type != exp_ty:
                        raise TypeError(f"Call arg {idx} at {self.line}:{self.column}: expected an lvalue for by reference parameter")

                    call_args.append(lptr)
                    continue

            value = arg_node.generate_ir(builder, module)
            if idx < len(fixed_param_tys):
                value = self.coerce_call_arg(builder, value, fixed_param_tys[idx], idx)
            call_args.append(value)

        call = builder.call(func, call_args, name=".call:" + self.name)
        if sret:
            return builder.load(sret_slot, name=".sret.load")
        return call

class IdentifierNode(TrackedNode):
    def __init__(self, identifier: str, line: int, column: int):
        super().__init__(line, column)
        self.identifier = identifier

    def __repr__(self, level: int = 0) -> str:
        return "\t" * level + f'IdentifierNode("{self.identifier}") at {self.line}:{self.column}\n'

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        # check function args
        args = [arg for arg in builder.function.args if arg.name == self.identifier]
        arg = args[0] if args else None
        if arg is not None:
            # Only auto-load pointers to scalars; keep pointers to aggregates (e.g. struct*) as pointers.
            if isinstance(arg.type, ir.PointerType) and _is_scalar_type(arg.type.pointee):
                return builder.load(arg, name=".load:" + self.identifier)
            return arg

        ptr = module.symbol_table.get(self.identifier)
        if ptr is None:
            ptr = module.globals.get(self.identifier)
        if ptr is None:
            raise ValueError(f"Variable {self.identifier} not found at {self.line}:{self.column}")

        if isinstance(ptr.type, ir.PointerType) and _is_scalar_type(ptr.type.pointee):
            return builder.load(ptr, name=".load:" + self.identifier)
        return ptr

    def get_joined_name(self) -> str:
        return self.identifier

class AccessNode(TrackedNode):
    def __init__(self, identifier: ExpressionsNode, line: int, column: int):
        super().__init__(line, column)
        self.identifier = identifier

    def __repr__(self, level: int = 0) -> str:
        raise NotImplementedError("Only virtual method")

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        raise NotImplementedError("Only virtual method")

    def get_base_identifier(self) -> IdentifierNode:
        current = self.identifier
        while isinstance(current, AccessNode):
            current = current.identifier
        return current

    def get_joined_name(self) -> str:
        if isinstance(self.identifier, AccessNode):
            base = self.identifier.get_joined_name()
        elif isinstance(self.identifier, IdentifierNode):
            base = self.identifier.identifier
        else:
            base = self.get_base_identifier().identifier

        if isinstance(self, MemberAccessNode):
            return f"{base}${self.member}"

        if isinstance(self, IndexAccessNode):
            if isinstance(getattr(self, "index", None), IntegerLiteralNode):
                return f"{base}$idx{self.index.value}"
            return f"{base}$idx"
        return base

    @abc.abstractmethod
    def generate_ptr(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        raise NotImplementedError("Only virtual method")

    def generate_ptr_store(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        return self.generate_ptr(builder, module)

class MemberAccessNode(AccessNode):
    def __init__(self, identifier: ExpressionsNode, member: str, line: int, column: int):
        super().__init__(identifier, line, column)
        self.member = member

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"MemberAccessNode({self.member}) at {self.line}:{self.column}\n"
        ret += self.identifier.__repr__(level + 1)
        return ret

    def generate_ptr(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        base_val = self.identifier.generate_ir(builder, module)
        if not isinstance(base_val.type, ir.PointerType):
            raise TypeError(f"Member access base must be a pointer at {self.line}:{self.column}")
        base_ptr = base_val

        struct_ty = base_ptr.type.pointee

        # union access
        if getattr(struct_ty, "is_union", False):
            idx_map = getattr(struct_ty, "union_variant_index", {})
            if self.member not in idx_map:
                raise ValueError(f"Unknown union variant '{self.member}' at {self.line}:{self.column}")
            
            variant_i = idx_map[self.member]
            variant_ty = struct_ty.union_variant_types[variant_i]

            payload_ptr_ptr = builder.gep(base_ptr, [ZERO, ONE], name=".ptr.union.payload")
            payload_i8p = builder.load(payload_ptr_ptr, name=".load.union.payload")
            return builder.bitcast(payload_i8p, ir.PointerType(variant_ty), name=".ptr.union.variant." + self.member)

        if not isinstance(struct_ty, ir.Aggregate):
            raise TypeError(f"Member access base must point to an aggregate at {self.line}:{self.column}")

        field_names = getattr(struct_ty, "field_names", None)
        if not field_names or self.member not in field_names:
            raise ValueError(f"Unknown field '{self.member}' at {self.line}:{self.column}")

        field_index = field_names.index(self.member)
        return builder.gep(base_ptr, [ZERO, ir.Constant(i32, field_index)], name=".ptr.memberaccess:" + self.member)

    def generate_ptr_store(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        base_value = self.identifier.generate_ir(builder, module)
        if not isinstance(base_value.type, ir.PointerType):
            raise TypeError(f"Member access base must be a pointer at {self.line}:{self.column}")
        base_ptr = base_value
        union_ty = base_ptr.type.pointee

        if not getattr(union_ty, "is_union", False):
            return self.generate_ptr(builder, module)

        idx_map = getattr(union_ty, "union_variant_index", {})
        if self.member not in idx_map:
            raise ValueError(f"Unknown union variant '{self.member}' at {self.line}:{self.column}")

        variant_i = idx_map[self.member]
        variant_ty = union_ty.union_variant_types[variant_i]

        tag_ptr = builder.gep(base_ptr, [ZERO, ZERO], name=".ptr.union.tag")
        payload_ptr_ptr = builder.gep(base_ptr, [ZERO, ONE], name=".ptr.union.payload")

        nbytes = _sizeof_as_i32(builder, variant_ty)
        raw = builder.call(module.globals["malloc"], [nbytes], name=".call.union.malloc")

        builder.store(ir.Constant(i32, variant_i), tag_ptr)
        builder.store(raw, payload_ptr_ptr)

        return builder.bitcast(raw, ir.PointerType(variant_ty), name=".ptr.union.variant.store." + self.member)

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        ptr = self.generate_ptr(builder, module)
        if isinstance(ptr.type, ir.PointerType) and _is_scalar_type(ptr.type.pointee):
            return builder.load(ptr, name=".load.memberaccess:" + self.member)
        return ptr

class IndexAccessNode(AccessNode):
    def __init__(self, identifier: ExpressionsNode, index: ASTNode, line: int, column: int):
        super().__init__(identifier, line, column)
        self.index = index

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"IndexAccessNode() at {self.line}:{self.column}\n"
        ret += "\t" * (level + 1) + "Base:\n"
        ret += self.identifier.__repr__(level + 2)
        ret += "\t" * (level + 1) + "Index:\n"
        ret += self.index.__repr__(level + 2)
        return ret

    def _as_i32_index(self, builder: ir.IRBuilder, idx_val: ir.Value) -> ir.Value:
        if not isinstance(idx_val.type, ir.IntType):
            raise TypeError(f"Index must be an integer at {self.line}:{self.column}")
        if idx_val.type.width == 32:
            return idx_val
        if idx_val.type.width < 32:
            return builder.zext(idx_val, i32, name=".zext.idx")
        return builder.trunc(idx_val, i32, name=".trunc.idx")

    def generate_ptr(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        base_val = self.identifier.generate_ir(builder, module)
        if not isinstance(base_val.type, ir.PointerType):
            raise TypeError(f"Index access base must be a pointer at {self.line}:{self.column}")

        idx_val = self._as_i32_index(builder, self.index.generate_ir(builder, module))

        pointee = base_val.type.pointee

        # Static array: [N x T]*
        if isinstance(pointee, ir.ArrayType):
            return builder.gep(base_val, [ZERO, idx_val], name=".ptr.index")

        # Dynamic array: array.T* where body is { T*, i32, i32 } and element pointer is field 0.
        if isinstance(pointee, ir.IdentifiedStructType) and (pointee.name or "").startswith("array."):
            data_ptr_ptr = builder.gep(base_val, [ZERO, ZERO], name=".ptr.array.data")
            data_ptr = builder.load(data_ptr_ptr, name=".load.array.data")
            return builder.gep(data_ptr, [idx_val], name=".ptr.index")

        # String: str* where body is { i8*, i32, i32 } and data pointer is field 0.
        str_ty = type_from_name_mapping.get("str")
        if str_ty is not None and pointee == str_ty:
            data_ptr_ptr = builder.gep(base_val, [ZERO, ZERO], name=".ptr.str.data")
            data_ptr = builder.load(data_ptr_ptr, name=".load.str.data")
            return builder.gep(data_ptr, [idx_val], name=".ptr.str.index")

        # Plain pointer indexing (e.g. i8* for str, or T*).
        return builder.gep(base_val, [idx_val], name=".ptr.index")

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        ptr = self.generate_ptr(builder, module)
        if isinstance(ptr.type, ir.PointerType) and _is_scalar_type(ptr.type.pointee):
            return builder.load(ptr, name=".load.index")
        return ptr

class AssignmentNode(TrackedNode):
    def __init__(self, identifier: IdentifierNode | AccessNode, value: ASTNode, line: int, column: int, typed: str = None, typed_arr_len: int = None):
        super().__init__(line, column)
        self.identifier = identifier
        self.value = value
        self.typed = typed
        self.typed_arr_len = typed_arr_len

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + 'AssignmentNode()'
        if self.typed is not None:
            ret += f": {self.typed}"
        if self.typed_arr_len is not None:
            ret += f"[{self.typed_arr_len}]"
        ret += f" at {self.line}:{self.column}\n"
        if self.value is not None:
            ret += self.value.__repr__(level + 1)
        ret += self.identifier.__repr__(level + 1)
        return ret

    def _ensure_dynamic_array_append_function(
        self,
        builder: ir.IRBuilder,
        array_ty: ir.IdentifiedStructType,
        element_type: ir.Type,
    ) -> None:
        # Minimal: only scalar elements (ints/pointers). Allow `str` and aggregate (struct) elements.
        if not _is_scalar_type(element_type):
            str_ty = type_from_name_mapping.get("str")
            if str_ty is not None and element_type == str_ty:
                pass
            elif isinstance(element_type, ir.Aggregate):
                # allow storing structs by-value into the element slot
                pass
            else:
                return

        module = builder.module
        mangled = _mangle_type_for_symbol(element_type)
        fn_name = f"array_append_{mangled}"
        if module.globals.get(fn_name):
            return

        realloc_fn = module.globals["realloc"]

        arr_ptr_ty = ir.PointerType(array_ty)
        fn_ty = ir.FunctionType(ir.VoidType(), [arr_ptr_ty, element_type])
        fn = ir.Function(module, fn_ty, name=fn_name)

        arr_arg, elem_arg = fn.args
        arr_arg.name = "arr"
        elem_arg.name = "elem"

        entry = fn.append_basic_block("entry")
        grow_bb = fn.append_basic_block("grow")
        store_bb = fn.append_basic_block("store")

        b = ir.IRBuilder(entry)

        # Field pointers: { T*, i32, i32 } => data,len,cap
        data_ptr_ptr = b.gep(arr_arg, [ZERO, ZERO], name=".ptr.data")
        len_ptr = b.gep(arr_arg, [ZERO, ONE], name=".ptr.len")
        cap_ptr = b.gep(arr_arg, [ZERO, TWO], name=".ptr.cap")

        data_ptr = b.load(data_ptr_ptr, name=".load.data")
        length = b.load(len_ptr, name=".load.len")
        cap = b.load(cap_ptr, name=".load.cap")

        has_room = b.icmp_signed("<", length, cap, name=".cmp.has_room")
        b.cbranch(has_room, store_bb, grow_bb)

        # grow:
        b.position_at_start(grow_bb)
        cap_is_zero = b.icmp_signed("==", cap, ZERO, name=".cmp.cap0")
        cap_dbl = b.mul(cap, TWO, name=".cap.dbl")
        new_cap = b.select(cap_is_zero, ONE, cap_dbl, name=".cap.new")

        sizeof_t = _sizeof_as_i32(b, element_type)
        new_cap_i32 = b.zext(new_cap, i32, name=".zext.newcap")
        nbytes = b.mul(new_cap_i32, sizeof_t, name=".mul.nbytes")

        old_i8p = b.bitcast(data_ptr, i8p, name=".bc.old")
        raw_new = b.call(realloc_fn, [old_i8p, nbytes], name=".call.realloc")
        new_data_ptr = b.bitcast(raw_new, ir.PointerType(element_type), name=".bc.new")

        b.store(new_data_ptr, data_ptr_ptr)
        b.store(new_cap, cap_ptr)
        b.branch(store_bb)

        # store:
        b.position_at_start(store_bb)
        data_ptr2 = b.load(data_ptr_ptr, name=".load.data2")
        length2 = b.load(len_ptr, name=".load.len2")

        elem_ptr = b.gep(data_ptr2, [length2], name=".ptr.elem")
        b.store(elem_arg, elem_ptr)

        new_len = b.add(length2, ONE, name=".len.inc")
        b.store(new_len, len_ptr)
        b.ret_void()

    def _ensure_dynamic_array_init_function(
        self,
        builder: ir.IRBuilder,
        array_ty: ir.IdentifiedStructType,
        element_type: ir.Type,
    ) -> None:
        module = builder.module
        mangled = _mangle_type_for_symbol(element_type)
        fn_name = f"array_init_{mangled}"
        if module.globals.get(fn_name):
            return

        arr_ptr_ty = ir.PointerType(array_ty)
        fn_ty = ir.FunctionType(ir.VoidType(), [arr_ptr_ty])
        fn = ir.Function(module, fn_ty, name=fn_name)
        (arr_arg,) = fn.args
        arr_arg.name = "arr"

        entry = fn.append_basic_block("entry")
        b = ir.IRBuilder(entry)

        # { T*, i32, i32 } => data,len,cap
        data_ptr_ptr = b.gep(arr_arg, [ZERO, ZERO], name=".arr.ptr.data")
        len_ptr = b.gep(arr_arg, [ZERO, ONE], name=".arr.ptr.len")
        cap_ptr = b.gep(arr_arg, [ZERO, TWO], name=".arr.ptr.cap")

        b.store(ir.Constant(ir.PointerType(element_type), None), data_ptr_ptr)
        b.store(ZERO, len_ptr)
        b.store(ZERO, cap_ptr)
        b.ret_void()

    def generate_dynamic_array_type(self, builder: ir.IRBuilder, element_type: ir.Type) -> ir.LiteralStructType:
        val = builder.module.context.identified_types.get("array." + str(element_type))
        if val is not None:
            # Ensure helpers exist even if type was created earlier in this module/context.
            self._ensure_dynamic_array_init_function(builder, val, element_type)
            self._ensure_dynamic_array_append_function(builder, val, element_type)
            return val

        data_ptr_type = ir.PointerType(element_type)
        length_type = i32
        cap_type = i32

        val = builder.module.context.get_identified_type("array." + str(element_type))
        val.set_body(data_ptr_type, length_type, cap_type)

        self._ensure_dynamic_array_init_function(builder, val, element_type)
        self._ensure_dynamic_array_append_function(builder, val, element_type)
        return val

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        # check name validity
        if isinstance(self.identifier, IdentifierNode):
            if self.identifier.identifier in reserved_types:
                raise ValueError(f"Cannot use reserved type name {self.identifier.identifier} as variable name at {self.line}:{self.column}")
            elif self.identifier.identifier in reserved_keywords:
                raise ValueError(f"Cannot use reserved keyword {self.identifier.identifier} as variable name at {self.line}:{self.column}")

        ptr = None
        if isinstance(self.identifier, AccessNode):
            base_name = self.identifier.get_base_identifier().identifier
            ptr = module.symbol_table.get(base_name)

            if ptr is None:
                arg = next((a for a in builder.function.args if a.name == base_name), None)
                if arg is not None:
                    ptr = arg

            if ptr is None:
                ptr = module.globals.get(base_name)

            if ptr is None:
                raise ValueError(f"Variable {base_name} not found at {self.line}:{self.column}")
        else:
            name = self.identifier.identifier
            ptr = module.symbol_table.get(name)

            if ptr is None:
                arg = next((a for a in builder.function.args if a.name == name), None)
                if arg is not None and isinstance(arg.type, ir.PointerType):
                    ptr = arg

            if ptr is None:
                ptr = module.globals.get(name)

        if ptr is None:
            # alloc
            if self.typed is None and self.value is None:
                raise ValueError(f"Variable {self.identifier.identifier} must have a type or value at {self.line}:{self.column}")
            
            var_type = None
            if self.typed is not None:
                var_type = type_from_name_mapping.get(self.typed)
                if var_type is None:
                    var_type = type_from_name_mapping.get(module.name + "$" + self.typed)
                if var_type is None:
                    raise ValueError(f"Unknown type {self.typed} for variable {self.identifier.identifier} at {self.line}:{self.column}")

                if self.typed_arr_len is not None:
                    if self.typed_arr_len > 0:
                        var_type = ir.ArrayType(var_type, self.typed_arr_len)
                    elif self.typed_arr_len == -1:
                        var_type = self.generate_dynamic_array_type(builder, var_type)
                    else:
                        raise ValueError(f"Invalid array size {self.typed_arr_len} for variable {self.identifier.identifier} at {self.line}:{self.column}")

            value = None
            if self.value is not None:
                value = self.value.generate_ir(builder, module)
                if value is None:
                    raise ValueError(f"Should not happen: value generation returned None for variable {self.identifier.identifier} at {self.line}:{self.column} from node: {self.value}")

                if var_type is None:
                    var_type = value.type

                if var_type is not None and var_type != value.type:
                    if isinstance(var_type, ir.IntType) and var_type.width == 8 and isinstance(value.type, ir.IntType) and value.type.width == 32:
                        value = builder.trunc(value, var_type, name=".trunc:" + self.identifier.identifier)
                    else:
                        got = name_from_type_mapping.get(value.type, str(value.type))
                        raise TypeError(f"Type mismatch for variable {self.identifier.identifier} at {self.line}:{self.column}: expected {self.typed}, got {got}")

            builder.position_at_start(builder.block)
            ptr = builder.alloca(var_type, name=self.identifier.identifier)
            
            # default-init unions: { tag=-1, payload=null }
            if value is None and getattr(var_type, "is_union", False):
                tag_ptr = builder.gep(ptr, [ZERO, ZERO], name=".ptr.union.tag")
                payload_ptr = builder.gep(ptr, [ZERO, ONE], name="ptr.union.payload")

                builder.store(ir.Constant(i32, -1), tag_ptr)
                builder.store(ir.Constant(i8p, None), payload_ptr)
            
            builder.position_at_end(builder.block)

            module.symbol_table[self.identifier.identifier] = ptr

            # default-init dynamic arrays: { data=null, len=0, cap=0 }
            if (
                value is None
                and isinstance(var_type, ir.IdentifiedStructType)
                and (var_type.name or "").startswith("array.")
                and getattr(var_type, "elements", None)
                and isinstance(var_type.elements[0], ir.PointerType)
            ):
                elem_ty = var_type.elements[0].pointee
                self._ensure_dynamic_array_init_function(builder, var_type, elem_ty)
                init_fn = module.globals.get(f"array_init_{_mangle_type_for_symbol(elem_ty)}")
                builder.call(init_fn, [ptr], name=".call:array_init")

            if value is not None:
                builder.store(value, ptr)
        else:
            # store only (supports member access lvalues)
            if isinstance(self.identifier, AccessNode):
                dst_ptr = self.identifier.generate_ptr_store(builder, module)
            else:
                name = self.identifier.identifier
                dst_ptr = module.symbol_table.get(name)
                if dst_ptr is None:
                    arg = next((a for a in builder.function.args if a.name == name), None)
                    if arg is not None and isinstance(arg.type, ir.PointerType):
                        dst_ptr = arg
                    else:
                        dst_ptr = self.identifier.generate_ir(builder, module)

            value = self.value.generate_ir(builder, module)
            if self.typed is not None:
                raise TypeError(f"Variable {self.identifier.identifier} already declared at {self.line}:{self.column}")

            if not isinstance(dst_ptr.type, ir.PointerType):
                raise TypeError(f"Assignment target is not addressable at {self.line}:{self.column}")

            dst_ty = dst_ptr.type.pointee

            # Allow "struct copy": dst is T (stored via T*), RHS is T* (an lvalue pointer).
            if dst_ty != value.type:
                if isinstance(dst_ty, ir.Aggregate) and isinstance(value.type, ir.PointerType) and value.type.pointee == dst_ty:
                    value = builder.load(value, name=".load.copy")
                elif isinstance(dst_ty, ir.IntType) and dst_ty.width == 8 and isinstance(value.type, ir.IntType) and value.type.width == 32:
                    value = builder.trunc(value, dst_ty, name=".trunc.assign")
                elif (isinstance(dst_ty, ir.PointerType) and isinstance(dst_ty.pointee, ir.Aggregate) and value.type == dst_ty.pointee):
                    nbytes = _sizeof_as_i32(builder, dst_ty.pointee)
                    raw = builder.call(module.globals["malloc"], [nbytes], name=".call.box.malloc")
                    boxed_ptr = builder.bitcast(raw, dst_ty, name=".box.ptr")
                    builder.store(value, boxed_ptr)
                    value = boxed_ptr
                else:
                    exp = name_from_type_mapping.get(dst_ty, str(dst_ty))
                    got = name_from_type_mapping.get(value.type, str(value.type))
                    raise TypeError(f"Type mismatch in assignment at {self.line}:{self.column}: expected {exp}, got {got}")

            builder.store(value, dst_ptr)

class StringLiteralNode(TrackedNode):
    def __init__(self, value: str, line: int, column: int):
        super().__init__(line, column)
        self.value = value

    def __repr__(self, level: int = 0) -> str:
        return "\t" * level + f'StringLiteralNode("{self.value}") at {self.line}:{self.column}\n'

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        str_ty = type_from_name_mapping["str"]

        byte_arr = bytes(self.value, "utf8").decode("unicode_escape").encode("utf8")
        name = ".literal.bytes:" + self.value

        if module.globals.get(name) is None:
            arr = ir.Constant(ir.ArrayType(i8, len(byte_arr)), bytearray(byte_arr))
            g = ir.GlobalVariable(module, arr.type, name=name)
            g.linkage = "private"
            g.global_constant = True
            g.unnamed_addr = True
            g.initializer = arr

        g = module.globals[name]
        src_ptr = builder.gep(g, [ZERO, ZERO], name=".literal.ptr")
        return builder.call(module.globals["str_from_bytes"], [src_ptr, ir.Constant(i32, len(byte_arr))])

# region literals
class IntegerLiteralNode(TrackedNode):
    def __init__(self, value: int, line: int, column: int):
        super().__init__(line, column)
        self._type = i32
        self.value = value

    def __repr__(self, level: int = 0) -> str:
        return "\t" * level + f'IntegerLiteralNode({self.value}) at {self.line}:{self.column}\n'

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        return ir.Constant(self._type, self.value)
# endregion

# region keyword nodes
class StructNode(TrackedNode):
    def __init__(self, name: str, line: int, column: int):
        super().__init__(line, column)
        self.name = name
        self.fields: list[AssignmentNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f'StructNode({self.name}) at {self.line}:{self.column}\n'
        for field in self.fields:
            ret += field.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        qualified_name = module.module_name + "$" + self.name
        if module.globals.get(qualified_name):
            raise ValueError(f"Struct {qualified_name} already defined at {self.line}:{self.column}")

        # Reuse any previously-created identified type (prevents duplicate %"Name" types).
        ctx = builder.module.context
        struct_ty = ctx.identified_types.get(qualified_name)
        if struct_ty is None:
            struct_ty = ctx.get_identified_type(qualified_name)
        else:
            if getattr(struct_ty, "is_opaque", False) is False and getattr(struct_ty, "elements", None):
                raise ValueError(f"Struct {qualified_name} already defined at {self.line}:{self.column}")

        type_from_name_mapping[qualified_name] = struct_ty
        name_from_type_mapping[struct_ty] = qualified_name

        helper = AssignmentNode(IdentifierNode(".__struct_field_tmp", self.line, self.column), None, self.line, self.column)
        field_names = []
        field_types = []
        for field in self.fields:
            qualified_field_type = module.module_name + "$" + field.typed
            if field.typed is None:
                raise ValueError(f"Field {field.identifier.identifier} in struct {qualified_name} must have a type at {field.line}:{field.column}")
            elif field.value is not None:
                raise ValueError(f"Field {field.identifier.identifier} in struct {qualified_name} cannot have an initial value at {field.line}:{field.column}")

            base_ty = None
            if qualified_field_type == qualified_name:
                base_ty = struct_ty
            else:
                base_ty = type_from_name_mapping.get(qualified_field_type) or type_from_name_mapping.get(field.typed)

            if base_ty is None:
                raise ValueError(f"Unknown type '{field.typed}' for field {field.identifier.identifier} in struct {self.name} at {field.line}:{field.column}")

            # Handle arrays on struct fields
            if field.typed_arr_len is not None:
                if field.typed_arr_len > 0:
                    field_type = ir.ArrayType(base_ty, field.typed_arr_len)
                elif field.typed_arr_len == -1:
                    field_type = helper.generate_dynamic_array_type(builder, base_ty)  # creates array.* + array_append_*
                else:
                    raise ValueError(f"Invalid array size {field.typed_arr_len} for field {field.identifier.identifier} at {field.line}:{field.column}")
            else:
                # Keep existing “user-defined types become pointers” behavior
                if qualified_field_type == qualified_name:
                    field_type = ir.PointerType(struct_ty)
                elif type_from_name_mapping.get(qualified_field_type) is not None:
                    field_type = ir.PointerType(base_ty)
                else:
                    field_type = base_ty

            field_types.append(field_type)
            field_names.append(field.identifier.identifier)

        struct_ty.set_body(*field_types)
        struct_ty.field_names = field_names

        # Keep mappings pointing at the same struct_ty instance (do NOT re-fetch it)
        type_from_name_mapping[qualified_name] = struct_ty
        name_from_type_mapping[struct_ty] = qualified_name

class UnionNode(TrackedNode):
    def __init__(self, name: str, line: int, column: int):
        super().__init__(line, column)
        self.name = name
        self.fields: list[AssignmentNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f'UnionNode({self.name}) at {self.line}:{self.column}\n'
        for field in self.fields:
            ret += field.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        qualified_name = module.module_name + "$" + self.name

        ctx = builder.module.context
        union_ty = ctx.identified_types.get(qualified_name)
        if union_ty is None:
            union_ty = ctx.get_identified_type(qualified_name)
        else:
            if getattr(union_ty, "is_opaque", False) is False and getattr(union_ty, "elements", None):
                raise ValueError(f"Union {qualified_name} already defined at {self.line}:{self.column}")

        type_from_name_mapping[qualified_name] = union_ty
        name_from_type_mapping[union_ty] = qualified_name

        variant_names: list[str] = []
        variant_types: list[ir.Type] = []

        for field in self.fields:
            if field.typed is None:
                raise ValueError(f"Variant {field.identifier.identifier} in union {qualified_name} must have a type at {field.line}:{field.column}")
            if field.value is not None:
                raise ValueError(f"Variant {field.identifier.identifier} in union {qualified_name} cannot have an initial value at {field.line}:{field.column}")

            ty = type_from_name_mapping.get(field.typed)
            if ty is None:
                ty = type_from_name_mapping.get(module.module_name + "$" + field.typed)
            if ty is None:
                raise ValueError(f"Unknown type '{field.typed}' for variant {field.identifier.identifier} in union {qualified_name} at {field.line}:{field.column}")

            if field.identifier.identifier in variant_names:
                raise ValueError(f"Duplicate variant '{field.identifier.identifier}' in union {qualified_name} at {field.line}:{field.column}")
            
            variant_names.append(field.identifier.identifier)
            variant_types.append(ty)

        union_ty.set_body(i32, i8p)
        union_ty.field_names = ["tag", "payload"]

        union_ty.is_union = True
        union_ty.union_variant_names = variant_names
        union_ty.union_variant_types = variant_types
        union_ty.union_variant_index = {name: i for i, name in enumerate(variant_names)}

        type_from_name_mapping[qualified_name] = union_ty
        name_from_type_mapping[union_ty] = qualified_name

class FunctionNode(TrackedNode):
    def __init__(self, name: str, line: int, column: int):
        super().__init__(line, column)
        self.name = name
        self.body: list[ASTNode] = []
        self.params: list[AssignmentNode] = []
        self.return_type: str | None = None

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f'FunctionNode({self.name}) at {self.line}:{self.column}\n'

        if self.params:
            ret += "\t" * (level + 1) + "Args:\n"
            for param in self.params:
                ret += param.__repr__(level + 1)

        ret += "\t" * (level + 1) + "Body:\n"
        for statement in self.body:
            ret += statement.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        qualified_name = module.module_name + "$" + self.name
        if module.globals.get(qualified_name):
            raise ValueError(f"Function {qualified_name} already defined at {self.line}:{self.column}")

        ret_ty = None
        if isinstance(self.return_type, tuple):
            base_name, arr_len = self.return_type
            base_ty = type_from_name_mapping.get(base_name) or type_from_name_mapping(module.module_name + "$" + base_name)
            if base_ty is None:
                raise ValueError(f"Unknown return type '{base_name}' for function {self.name} at {self.line}:{self.column}")

            if arr_len > 0:
                ret_ty = ir.ArrayType(base_ty, arr_len)
            elif arr_len == -1:
                helper = AssignmentNode(IdentifierNode(".__ret_array_tmp", self.line, self.column), None, self.line, self.column)
                ret_ty = helper.generate_dynamic_array_type(builder, base_ty)
            else:
                raise ValueError(f"Invalid array size {arr_len} for return type of function {self.name} at {self.line}:{self.column}")
        else:
            if self.return_type is not None:
                ret_ty = type_from_name_mapping.get(self.return_type) or type_from_name_mapping.get(module.module_name + "$" + self.return_type)
        
        sret = isinstance(ret_ty, ir.Aggregate)

        params_types = []
        for param in self.params:
            if param.typed is None:
                raise ValueError(f"Parameter {param.identifier.identifier} in function {qualified_name} must have a type at {param.line}:{param.column}")

            param_type = type_from_name_mapping.get(param.typed)
            if param_type is None:
                param_type = type_from_name_mapping.get(module.module_name + "$" + param.typed)
            if param_type is None:
                raise ValueError(f"Unknown type {param.typed} for parameter {param.identifier.identifier} in function {self.name} at {param.line}:{param.column}")

            if not isinstance(param_type, ir.PointerType):
                param_type = ir.PointerType(param_type)

            params_types.append(param_type)

        if sret:
            func_type = ir.FunctionType(ir.VoidType(), [ir.PointerType(ret_ty)] + params_types)
        else:
            func_type = ir.FunctionType(type_from_name_mapping.get(self.return_type, ir.VoidType()), params_types)
        func = ir.Function(module, func_type, name=qualified_name)
        func._kk_user = True

        if sret:
            func._sret = True
            func._sret_type = ret_ty

        expected_argc = len(self.params) + (1 if sret else 0)
        if len(func.args) != expected_argc:
            raise ValueError(f"Function {qualified_name} parameter count mismatch at {self.line}:{self.column}")

        for i, param in enumerate(self.params):
            func.args[i + (1 if sret else 0)].name = param.identifier.identifier

        if sret:
            func.args[0].name = ".sret"

        block = func.append_basic_block(name="entry")
        func_builder = ir.IRBuilder(block)

        # create new symbol table scope
        old_symbol_table = module.symbol_table
        module.symbol_table = {}

        for statement in self.body:
            statement.generate_ir(func_builder, module)
        
        if not func_builder.block.is_terminated:
            func_builder.ret_void()

        # restore old symbol table scope
        module.symbol_table = old_symbol_table

class ReturnNode(TrackedNode):
    def __init__(self, value: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.value = value

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"ReturnNode() at {self.line}:{self.column}\n"
        ret += self.value.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        ret_value = self.value.generate_ir(builder, module)
        func = builder.function

        if getattr(func, "_sret", False):
            sret_ptr = func.args[0]
            sret_pointee = sret_ptr.type.pointee

            if ret_value.type == sret_pointee:
                builder.store(ret_value, sret_ptr)
            elif isinstance(ret_value.type, ir.PointerType) and ret_value.type.pointee == sret_pointee:
                tmp = builder.load(ret_value, name=".load.ret.ptr")
                builder.store(tmp, sret_ptr)
            else:
                exp = name_from_type_mapping.get(sret_pointee, str(sret_pointee))
                got = name_from_type_mapping.get(ret_value.type, str(ret_value.type))
                raise TypeError(f"Return type mismatch at {self.line}:{self.column}: expected {exp}, got {got}")
            builder.ret_void()
            return
        
        builder.ret(ret_value)

class IfNode(TrackedNode):
    def __init__(self, condition: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.condition = condition
        self.then_branch: list[ASTNode] = []
        self.else_branch: list[ASTNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"IfNode() at {self.line}:{self.column}\n"
        ret += "\t" * (level + 1) + "Condition:\n"
        ret += self.condition.__repr__(level + 2)
        ret += "\t" * (level + 1) + "Then Body:\n"

        for stmt in self.then_branch:
            ret += stmt.__repr__(level + 2)

        if self.else_branch:
            ret += "\t" * (level + 1) + "Else Body:\n"
            for stmt in self.else_branch:
                ret += stmt.__repr__(level + 2)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        cond_value = self.condition.generate_ir(builder, module)

        if not isinstance(cond_value.type, ir.IntType) or cond_value.type.width != 1:
            raise TypeError(f"If condition must be of type bool at {self.line}:{self.column}")

        if self.else_branch is None or len(self.else_branch) == 0:
            with builder.if_then(cond_value) as then:
                for stmt in self.then_branch:
                    stmt.generate_ir(builder, module)
        else:
            with builder.if_else(cond_value) as (then, otherwise):
                with then:
                    for stmt in self.then_branch:
                        stmt.generate_ir(builder, module)
                with otherwise:
                    for stmt in self.else_branch:
                        stmt.generate_ir(builder, module)

class WhileNode(TrackedNode):
    def __init__(self, condition: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.condition = condition
        self.body: list[ASTNode] = []

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"WhileNode() at {self.line}:{self.column}\n"
        ret += "\t" * (level + 1) + "Condition:\n"
        ret += self.condition.__repr__(level + 2)
        ret += "\t" * (level + 1) + "Body:\n"

        for stmt in self.body:
            ret += stmt.__repr__(level + 2)

        return ret

    def generate_ir(self, builder, module):
        cond_value = self.condition.generate_ir(builder, module)

        if not isinstance(cond_value.type, ir.IntType) or cond_value.type.width != 1:
            raise TypeError(f"While condition must be of type bool at {self.line}:{self.column}")
        
        loop_bb = builder.append_basic_block("while.loop")
        after_bb = builder.append_basic_block("while.after")
        builder.cbranch(cond_value, loop_bb, after_bb)

        builder.position_at_start(loop_bb)

        builder.comment("while body")
        for stmt in self.body:
            stmt.generate_ir(builder, module)

        builder.comment("termination test")
        cond_value = self.condition.generate_ir(builder, module)
        builder.cbranch(cond_value, loop_bb, after_bb)

        builder.position_at_start(after_bb)

class LenNode(TrackedNode):
    def __init__(self, operand, line: int, column: int):
        super().__init__(line, column)
        self.operand = operand

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level
        ret += f"LenNode() at {self.line}:{self.column}\n"
        ret += self.operand.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        operand_value = self.operand.generate_ir(builder, module)

        # static array
        if isinstance(operand_value.type, ir.ArrayType):
            return ir.Constant(i32, operand_value.type.count)

        # pointer
        if isinstance(operand_value.type, ir.PointerType):
            pointee = operand_value.type.pointee

            # static array
            if isinstance(pointee, ir.ArrayType):
                return ir.Constant(i32, pointee.count)

            # dynamic array
            if isinstance(pointee, ir.IdentifiedStructType) and (pointee.name or "").startswith("array."):
                len_ptr = builder.gep(operand_value, [ZERO, ONE], name=".ptr.len")
                return builder.load(len_ptr, name=".load.len")

            # string
            str_ty = type_from_name_mapping.get("str")
            if str_ty is not None and pointee == str_ty:
                len_ptr = builder.gep(operand_value, [ZERO, ONE], name=".ptr.str.len")
                return builder.load(len_ptr, name=".load.str.len")
            
            raise TypeError(f"Length operand must be an array or string at {self.line}:{self.column}")

        # aggregate value
        if isinstance(operand_value.type, ir.IdentifiedStructType):
            # dynamic array
            if (operand_value.type.name or "").startswith("array."):
                return builder.extract_value(operand_value, 1, name=".extract.len")

            # string
            str_ty = type_from_name_mapping.get("str")
            if str_ty is not None and operand_value.type == str_ty:
                return builder.extract_value(operand_value, 1, name=".extract.str.len")

        raise TypeError(f"Length operand must be an array or string at {self.line}:{self.column}")

class ImportNode(TrackedNode):
    def __init__(self, name_parts: list[str], line: int, column: int):
        super().__init__(line, column)
        self.name_parts = name_parts

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level
        ret += f"ImportNode({'.'.join(self.name_parts)}) at {self.line}:{self.column}\n"
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Type:
        pass
# endregion

# region operators
class BinaryAdditionNode(TrackedNode):
    def __init__(self, left: ASTNode, right: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.left = left
        self.right = right

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"BinaryAdditionNode() at {self.line}:{self.column}\n"
        ret += self.left.__repr__(level + 1)
        ret += self.right.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        left_val = self.left.generate_ir(builder, module)
        right_val = self.right.generate_ir(builder, module)

        if not isinstance(left_val.type, ir.IntType) or not isinstance(right_val.type, ir.IntType):
            raise TypeError(f"Binary addition requires integer operands at {self.line}:{self.column}")

        result = builder.add(left_val, right_val, name=".add")
        return result

class BinarySubtractionNode(TrackedNode):
    def __init__(self, left: ASTNode, right: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.left = left
        self.right = right

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"BinarySubtractionNode() at {self.line}:{self.column}\n"
        ret += self.left.__repr__(level + 1)
        ret += self.right.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        left_val = self.left.generate_ir(builder, module)
        right_val = self.right.generate_ir(builder, module)

        if not isinstance(left_val.type, ir.IntType) or not isinstance(right_val.type, ir.IntType):
            raise TypeError(f"Binary subtraction requires integer operands at {self.line}:{self.column}")

        result = builder.sub(left_val, right_val, name=".sub")
        return result

class BinaryMultiplicationNode(TrackedNode):
    def __init__(self, left: ASTNode, right: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.left = left
        self.right = right

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"BinaryMultiplicationNode() at {self.line}:{self.column}\n"
        ret += self.left.__repr__(level + 1)
        ret += self.right.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        left_val = self.left.generate_ir(builder, module)
        right_val = self.right.generate_ir(builder, module)

        if not isinstance(left_val.type, ir.IntType) or not isinstance(right_val.type, ir.IntType):
            raise TypeError(f"Binary multiplication requires integer operands at {self.line}:{self.column}")

        result = builder.mul(left_val, right_val, name=".mul")
        return result

class BinaryDivisionNode(TrackedNode):
    def __init__(self, left: ASTNode, right: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.left = left
        self.right = right

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"BinaryDivisionNode() at {self.line}:{self.column}\n"
        ret += self.left.__repr__(level + 1)
        ret += self.right.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        left_val = self.left.generate_ir(builder, module)
        right_val = self.right.generate_ir(builder, module)

        if not isinstance(left_val.type, ir.IntType) or not isinstance(right_val.type, ir.IntType):
            raise TypeError(f"Binary division requires integer operands at {self.line}:{self.column}")

        result = builder.sdiv(left_val, right_val, name=".div")
        return result

class UnaryNegationNode(TrackedNode):
    def __init__(self, operand: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.operand = operand

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"UnaryNegationNode() at {self.line}:{self.column}\n"
        ret += self.operand.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        operand_val = self.operand.generate_ir(builder, module)

        if not isinstance(operand_val.type, ir.IntType):
            raise TypeError(f"Unary negation requires an integer operand at {self.line}:{self.column}")

        result = builder.neg(operand_val, name=".neg")
        return result

class BinaryModuloNode(TrackedNode):
    def __init__(self, left: ASTNode, right: ASTNode, line: int, column: int):
        super().__init__(line, column)
        self.left = left
        self.right = right

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"BinaryModuloNode() at {self.line}:{self.column}\n"
        ret += self.left.__repr__(level + 1)
        ret += self.right.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        left_val = self.left.generate_ir(builder, module)
        right_val = self.right.generate_ir(builder, module)

        if not isinstance(left_val.type, ir.IntType) or not isinstance(right_val.type, ir.IntType):
            raise TypeError(f"Binary modulo requires integer operands at {self.line}:{self.column}")

        result = builder.srem(left_val, right_val, name=".mod")
        return result



class _EqualityBaseNode(TrackedNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int, name: str, short: str, cmpop: str):
        super().__init__(line, column)
        self.lhs = lhs
        self.rhs = rhs
        self.name = name
        self.short = short
        self.cmpop = cmpop

    def __repr__(self, level: int = 0) -> str:
        ret = "\t" * level + f"{self.name} at {self.line}:{self.column}\n"
        ret += self.lhs.__repr__(level + 1)
        ret += self.rhs.__repr__(level + 1)
        return ret

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        lhs_val = self.lhs.generate_ir(builder, module)
        rhs_val = self.rhs.generate_ir(builder, module)

        if lhs_val.type != rhs_val.type:
            raise TypeError(f"{self.name} requires operands of the same type at {self.line}:{self.column}")

        if isinstance(lhs_val.type, ir.IntType):
            result = builder.icmp_signed(self.cmpop, lhs_val, rhs_val, name=f".{self.short}")
        else:
            raise TypeError(f"{self.name} not supported for type {name_from_type_mapping[lhs_val.type]} at {self.line}:{self.column}")

        return result

class BinaryEqualNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryEqual", "eq", "==")

class BinaryNotEqualNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryNotEqual", "ne", "!=")

class BinaryLessThanNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryLessThan", "lt", "<")

class BinaryGreaterThanNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryGreaterThan", "gt", ">")

class BinaryLessOrEqualNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryLessOrEqual", "le", "<=")

class BinaryGreaterOrEqualNode(_EqualityBaseNode):
    def __init__(self, lhs: ASTNode, rhs: ASTNode, line: int, column: int):
        super().__init__(lhs, rhs, line, column, "BinaryGreaterOrEqual", "ge", ">=")
# endregion
