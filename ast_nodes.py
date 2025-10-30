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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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
    def __init__(self, identifier: str, line: int, column: int, fields: list[str | int | Self] = None):
        super().__init__(line, column)
        self.identifier = identifier
        self.fields = fields or []

    def __repr__(self, level: int = 0):
        return "\t" * level + f'IdentifierNode("{self.identifier}", fields={self.fields}) at {self.line}:{self.column}\n'

    def fields_to_str(self) -> str:
        if not self.fields:
            return ""

        s = ""

        for field in self.fields:
            if isinstance(field, IdentifierNode):
                s += "." + field.identifier
            else:
                s += "." + str(field)

        # s = "." + ".".join([field.identifier if isinstance(field, IdentifierNode) else str(field) for field in self.fields])
        return s

    def gep_into_fields(self, builder: ir.IRBuilder, module: ir.Module, ptr: ir.Value) -> ir.Value | ir.GEPInstr:
        if not self.fields:
            return ptr

        indices = [ir.Constant(ir.IntType(32), 0)]

        current_field = None
        if isinstance(ptr.type, ir.PointerType):
            current_field = ptr.type.pointee
        else:
            current_field = ptr.allocated_type

        indexing_string = False

        for field in self.fields:
            if isinstance(field, str):
                field_index = current_field.field_names.index(field)
                current_field = current_field.elements[field_index]

                indices.append(ir.Constant(ir.IntType(32), field_index))
            elif isinstance(field, int):
                if isinstance(current_field, ir.ArrayType) and field >= current_field.count:
                    raise IndexError(f"Array index {field} out of bounds for array of size {current_field.count} at {self.line}:{self.column}")

                indices.append(ir.Constant(ir.IntType(32), field))

                # indexing into string so stop since this is only gonna be a single character
                if isinstance(current_field, ir.PointerType) and isinstance(current_field.pointee, ir.IntType) and current_field.pointee.width == 8:
                    indexing_string = True
                    break

                current_field = current_field.element
            elif isinstance(field, IdentifierNode):
                field_value = field.generate_ir(builder, module)

                indices.append(field_value)

                # indexing into string so stop since this is only gonna be a single character
                if isinstance(current_field, ir.PointerType) and isinstance(current_field.pointee, ir.IntType) and current_field.pointee.width == 8:
                    indexing_string = True
                    break

                current_field = current_field.element

        # special case for string indexing
        if indexing_string == True:
            if not (isinstance(current_field, ir.PointerType) and isinstance(current_field.pointee, ir.IntType) and current_field.pointee.width == 8):
                raise TypeError(f"String indexing resulted in non-char type at {self.line}:{self.column}")
            gep = builder.gep(ptr, indices[:-1], name=".ptr:" + self.identifier + self.fields_to_str())
            load = builder.load(gep, name=".load:" + self.identifier + self.fields_to_str())
            return builder.gep(load, [indices[-1]], name=".ptr:" + self.identifier + self.fields_to_str())
        # normal gep
        else:
            return builder.gep(ptr, indices, name=".ptr:" + self.identifier + self.fields_to_str())

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> ir.Value:
        # check function args
        args = list(filter(lambda arg: arg.name == self.identifier, builder.function.args))
        arg = args[0] if args else None
        if arg is not None:
            if isinstance(arg.type, ir.PointerType):
                ptr = self.gep_into_fields(builder, module, arg)
                return builder.load(ptr, name=".load:" + self.identifier + self.fields_to_str())

            return arg

        ptr = module.symbol_table.get(self.identifier)
        if ptr is None:
            ptr = module.globals.get(self.identifier)
        if ptr is None:
            raise ValueError(f"Variable {self.identifier} not found at {self.line}:{self.column}")

        ptr = self.gep_into_fields(builder, module, ptr)

        if isinstance(ptr, ir.GEPInstr):
            if isinstance(ptr.type.pointee, ir.Aggregate):
                return ptr
            return builder.load(ptr, name=".load:" + self.identifier + self.fields_to_str())
        elif isinstance(ptr.allocated_type, ir.Aggregate):
            return ptr
        elif ptr is not None:
            return builder.load(ptr, name=".load:" + self.identifier + self.fields_to_str())

        raise ValueError(f"Variable {self.identifier} not found at {self.line}:{self.column}")

class AssignmentNode(TrackedNode):
    def __init__(self, identifier: IdentifierNode, value: ASTNode, line: int, column: int, typed: str = None, typed_arr_len: int = None):
        super().__init__(line, column)
        self.identifier = identifier
        self.value = value
        self.typed = typed
        self.typed_arr_len = typed_arr_len

    def __repr__(self, level: int = 0):
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

    def generate_ir(self, builder: ir.IRBuilder, module: ir.Module) -> None:
        # check name validity
        if self.identifier.identifier in reserved_types:
            raise ValueError(f"Cannot use reserved type name {self.identifier.identifier} as variable name at {self.line}:{self.column}")
        elif self.identifier.identifier in reserved_keywords:
            raise ValueError(f"Cannot use reserved keyword {self.identifier.identifier} as variable name at {self.line}:{self.column}")

        ptr = module.symbol_table.get(self.identifier.identifier)
        if ptr is None:
            # alloc
            if self.identifier.fields:
                raise ValueError(f"Cannot declare variable with field access {self.identifier.identifier}.{'.'.join(self.identifier.fields)} at {self.line}:{self.column}")

            if self.typed is None and self.value is None:
                raise ValueError(f"Variable {self.identifier.identifier} must have a type or value at {self.line}:{self.column}")

            var_type = None
            if self.typed is not None:
                var_type = type_from_name_mapping.get(self.typed)
                if var_type is None:
                    raise ValueError(f"Unknown type {self.typed} for variable {self.identifier.identifier} at {self.line}:{self.column}")

                if self.typed_arr_len is not None:
                    var_type = ir.ArrayType(var_type, self.typed_arr_len)

            value = None
            if self.value is not None:
                value = self.value.generate_ir(builder, module)
                if value is None:
                    raise ValueError(f"Should not happen: value generation returned None for variable {self.identifier.identifier} at {self.line}:{self.column} from node: {self.value}")

                # if value is not None:
                if var_type is not None and var_type != value.type:
                    if isinstance(var_type, ir.IntType) and var_type.width == 8 and isinstance(value.type, ir.IntType) and value.type.width == 32:
                        value = builder.trunc(value, var_type, name=".trunc:" + self.identifier.identifier)
                    else:
                        raise TypeError(f"Type mismatch for variable {self.identifier.identifier} at {self.line}:{self.column}: expected {self.typed}, got {name_from_type_mapping[value.type]}")

            builder.position_at_start(builder.block)
            ptr = builder.alloca(var_type, name=self.identifier.identifier)
            builder.position_at_end(builder.block)

            module.symbol_table[self.identifier.identifier] = ptr

            # store
            if value is not None:
                builder.store(value, ptr)
        else:
            # store only
            ptr = self.identifier.gep_into_fields(builder, module, ptr)

            value = self.value.generate_ir(builder, module)
            if self.typed is not None:
                raise TypeError(f"Variable {self.identifier.identifier} already declared at {self.line}:{self.column}")

            builder.store(value, ptr)

# region literals
class StringLiteralNode(TrackedNode):
    def __init__(self, value: str, line: int, column: int):
        super().__init__(line, column)
        self._type = ir.PointerType(ir.IntType(8))
        self.value = value

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level: int = 0):
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

    def __repr__(self, level = 0):
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
