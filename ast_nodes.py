import abc
from typing import Self
from llvmlite import ir

type_from_name_mapping = {
    "i32": ir.IntType(32),
    "str": ir.PointerType(ir.IntType(8)),
    "bool": ir.IntType(1),
    "void": ir.VoidType(),
    "char": ir.IntType(8),
    "i8": ir.IntType(8),
}

name_from_type_mapping = {
    ir.IntType(32): "i32",
    ir.PointerType(ir.IntType(8)): "str",
    ir.IntType(1): "i1/bool",
    ir.VoidType(): "void",
    ir.IntType(8): "i8/char",
}

reserved_types = set(type_from_name_mapping.keys())

reserved_keywords = {
    "struct",
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

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        builder.comment(f"Expressions originating at {self.line}:{self.column}")

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

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.CallInstr:
        func = module.globals.get(self.name)
        if not func:
            raise ValueError(f"Function {self.name} not found")

        args = []
        for arg in self.args:
            args.append(arg.generate_ir(builder, module))

        return builder.call(func, args, name=".call:" + self.name)

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

    @abc.abstractmethod
    def generate_ptr(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        """Generate an lvalue pointer for assignments (must be storable)."""
        raise NotImplementedError("Only virtual method")

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
        if not isinstance(struct_ty, ir.Aggregate):
            raise TypeError(f"Member access base must point to an aggregate at {self.line}:{self.column}")

        field_names = getattr(struct_ty, "field_names", None)
        if not field_names or self.member not in field_names:
            raise ValueError(f"Unknown field '{self.member}' at {self.line}:{self.column}")

        field_index = field_names.index(self.member)
        return builder.gep(
            base_ptr,
            [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_index)],
            name=".ptr.memberaccess:" + self.member,
        )

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
            return builder.zext(idx_val, ir.IntType(32), name=".zext.idx")
        return builder.trunc(idx_val, ir.IntType(32), name=".trunc.idx")

    def generate_ptr(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        base_val = self.identifier.generate_ir(builder, module)
        if not isinstance(base_val.type, ir.PointerType):
            raise TypeError(f"Index access base must be a pointer at {self.line}:{self.column}")

        idx_val = self._as_i32_index(builder, self.index.generate_ir(builder, module))

        pointee = base_val.type.pointee

        # Static array: [N x T]*
        if isinstance(pointee, ir.ArrayType):
            return builder.gep(
                base_val,
                [ir.Constant(ir.IntType(32), 0), idx_val],
                name=".ptr.index",
            )

        # Dynamic array: array.T* where body is { T*, i32, i32 } and element pointer is field 0.
        if isinstance(pointee, ir.IdentifiedStructType) and (pointee.name or "").startswith("array."):
            data_ptr_ptr = builder.gep(
                base_val,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
                name=".ptr.array.data",
            )
            data_ptr = builder.load(data_ptr_ptr, name=".load.array.data")
            return builder.gep(data_ptr, [idx_val], name=".ptr.index")

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

    def _sizeof_as_i32(self, builder: ir.IRBuilder, element_type: ir.Type) -> ir.Value:
        # sizeof(T) = ptrtoint(gep(T* null, 1))  (target-independent in IR)
        i32 = ir.IntType(32)
        null_tptr = ir.Constant(ir.PointerType(element_type), None)
        one_past = builder.gep(null_tptr, [ir.Constant(i32, 1)], name=".sizeof.gep")
        return builder.ptrtoint(one_past, i32, name=".sizeof")

    def _ensure_dynamic_array_append_function(
        self,
        builder: ir.IRBuilder,
        array_ty: ir.IdentifiedStructType,
        element_type: ir.Type,
    ) -> None:
        # Minimal: only scalar elements (ints/pointers). Struct elements need memcpy support.
        if not _is_scalar_type(element_type):
            return

        module = builder.module
        mangled = _mangle_type_for_symbol(element_type)
        fn_name = f"array_append_{mangled}"
        if module.globals.get(fn_name):
            return

        realloc_fn = module.globals["realloc"]

        i8 = ir.IntType(8)
        i8p = ir.PointerType(i8)
        i32 = ir.IntType(32)

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
        data_ptr_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name=".ptr.data")
        len_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 1)], name=".ptr.len")
        cap_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 2)], name=".ptr.cap")

        data_ptr = b.load(data_ptr_ptr, name=".load.data")
        length = b.load(len_ptr, name=".load.len")
        cap = b.load(cap_ptr, name=".load.cap")

        has_room = b.icmp_signed("<", length, cap, name=".cmp.has_room")
        b.cbranch(has_room, store_bb, grow_bb)

        # grow:
        b.position_at_start(grow_bb)
        cap_is_zero = b.icmp_signed("==", cap, ir.Constant(i32, 0), name=".cmp.cap0")
        cap_dbl = b.mul(cap, ir.Constant(i32, 2), name=".cap.dbl")
        new_cap = b.select(cap_is_zero, ir.Constant(i32, 1), cap_dbl, name=".cap.new")

        sizeof_t = self._sizeof_as_i32(b, element_type)
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

        new_len = b.add(length2, ir.Constant(i32, 1), name=".len.inc")
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

        i32 = ir.IntType(32)
        arr_ptr_ty = ir.PointerType(array_ty)
        fn_ty = ir.FunctionType(ir.VoidType(), [arr_ptr_ty])
        fn = ir.Function(module, fn_ty, name=fn_name)
        (arr_arg,) = fn.args
        arr_arg.name = "arr"

        entry = fn.append_basic_block("entry")
        b = ir.IRBuilder(entry)

        # { T*, i32, i32 } => data,len,cap
        data_ptr_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 0)], name=".arr.ptr.data")
        len_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 1)], name=".arr.ptr.len")
        cap_ptr = b.gep(arr_arg, [ir.Constant(i32, 0), ir.Constant(i32, 2)], name=".arr.ptr.cap")

        b.store(ir.Constant(ir.PointerType(element_type), None), data_ptr_ptr)
        b.store(ir.Constant(i32, 0), len_ptr)
        b.store(ir.Constant(i32, 0), cap_ptr)
        b.ret_void()

    def generate_dynamic_array_type(self, builder: ir.IRBuilder, element_type: ir.Type) -> ir.LiteralStructType:
        val = builder.module.context.identified_types.get("array." + str(element_type))
        if val is not None:
            # Ensure helpers exist even if type was created earlier in this module/context.
            self._ensure_dynamic_array_init_function(builder, val, element_type)
            self._ensure_dynamic_array_append_function(builder, val, element_type)
            return val

        data_ptr_type = ir.PointerType(element_type)
        length_type = ir.IntType(32)
        cap_type = ir.IntType(32)

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
            ptr = module.symbol_table.get(self.identifier.get_base_identifier().identifier)
        else:
            ptr = module.symbol_table.get(self.identifier.identifier)

        if ptr is None:
            # alloc
            if self.typed is None and self.value is None:
                raise ValueError(f"Variable {self.identifier.identifier} must have a type or value at {self.line}:{self.column}")
            
            var_type = None
            if self.typed is not None:
                var_type = type_from_name_mapping.get(self.typed)
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
                dst_ptr = self.identifier.generate_ptr(builder, module)
            else:
                dst_ptr = module.symbol_table.get(self.identifier.identifier)
                if dst_ptr is None:
                    dst_ptr = self.identifier.generate_ir(builder, module)

            value = self.value.generate_ir(builder, module)
            if self.typed is not None:
                raise TypeError(f"Variable {self.identifier.identifier} already declared at {self.line}:{self.column}")

            builder.store(value, dst_ptr)

# region literals
class StringLiteralNode(TrackedNode):
    def __init__(self, value: str, line: int, column: int):
        super().__init__(line, column)
        self._type = ir.PointerType(ir.IntType(8))
        self.value = value

    def __repr__(self, level: int = 0) -> str:
        return "\t" * level + f'StringLiteralNode("{self.value}") at {self.line}:{self.column}\n'

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        name =  ".literal:" + self.value
        if module.globals.get(name):
            str_ptr = builder.bitcast(module.globals[name], self._type, name=".ptr" + name)
            return str_ptr

        byte_arr = bytes(self.value, "utf8").decode("unicode_escape").encode("utf8") + b"\00"

        c_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(byte_arr)), bytearray(byte_arr))
        global_str = ir.GlobalVariable(module, c_str.type, name=name)
        global_str.linkage = "private"
        global_str.global_constant = True
        global_str.unnamed_addr = True
        global_str.initializer = c_str

        str_ptr = builder.gep(global_str, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], name=".ptr" + name)

        return str_ptr

class IntegerLiteralNode(TrackedNode):
    def __init__(self, value: int, line: int, column: int):
        super().__init__(line, column)
        self._type = ir.IntType(32)
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
        if module.globals.get(self.name):
            raise ValueError(f"Struct {self.name} already defined at {self.line}:{self.column}")

        field_names = []
        field_types = []
        for field in self.fields:
            if field.typed is None:
                raise ValueError(f"Field {field.identifier.identifier} in struct {self.name} must have a type at {field.line}:{field.column}")
            elif field.value is not None:
                raise ValueError(f"Field {field.identifier.identifier} in struct {self.name} cannot have an initial value at {field.line}:{field.column}")

            field_type = type_from_name_mapping.get(field.typed)
            if field_type is None:
                raise ValueError(f"Unknown type {field.typed} for field {field.identifier.identifier} in struct {self.name} at {field.line}:{field.column}")

            if field_names.count(field.identifier.identifier) != 0:
                raise ValueError(f"Duplicate field {field.identifier.identifier} in struct {self.name} at {field.line}:{field.column}")

            field_types.append(field_type)
            field_names.append(field.identifier.identifier)

        builder.module.context.get_identified_type(self.name).set_body(*field_types)
        builder.module.context.get_identified_type(self.name).field_names = field_names

        type_from_name_mapping[self.name] = builder.module.context.get_identified_type(self.name)
        name_from_type_mapping[builder.module.context.get_identified_type(self.name)] = self.name

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
        if module.globals.get(self.name):
            raise ValueError(f"Function {self.name} already defined at {self.line}:{self.column}")

        params_types = []
        for param in self.params:
            if param.typed is None:
                raise ValueError(f"Parameter {param.identifier.identifier} in function {self.name} must have a type at {param.line}:{param.column}")

            param_type = type_from_name_mapping.get(param.typed)
            if param_type is None:
                raise ValueError(f"Unknown type {param.typed} for parameter {param.identifier.identifier} in function {self.name} at {param.line}:{param.column}")

            if isinstance(param_type, ir.Aggregate):
                param_type = ir.PointerType(param_type)

            params_types.append(param_type)

        func_type = ir.FunctionType(type_from_name_mapping.get(self.return_type, ir.VoidType()), params_types)
        func = ir.Function(module, func_type, name=self.name)

        if len(func.args) != len(self.params):
            raise ValueError(f"Function {self.name} parameter count mismatch at {self.line}:{self.column}")
        for i, param in enumerate(self.params):
            func.args[i].name = param.identifier.identifier

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


        if not (isinstance(operand_value.type, ir.Aggregate) or isinstance(operand_value.allocated_type, ir.Aggregate)):
            raise TypeError(f"Length operand must be an aggregate at {self.line}:{self.column}")

        return ir.Constant(ir.IntType(32), 2)
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
