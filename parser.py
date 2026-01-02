from typing import TypeVar, Type
from tokens import *
from ast_nodes import *

T = TypeVar('T', bound=BaseToken)

UNARY_PREFIX_BINDING_POWER = 50

ADDITIVE_BINDING_POWER = 10, 11
MULTIPLICATIVE_BINDING_POWER = 20, 21
MODULO_BINDING_POWER = 20, 21
COMPARISON_BINDING_POWER = 3, 4

class Parser:
    def __init__(self, tokens: list[BaseToken]):
        if not tokens:
            raise ValueError("Tokens list for parser cannot be empty")

        self.tokens = tokens

        self.index = 0
        self.current_token = self.tokens[self.index]

    def advance(self, steps: int = 1) -> None:
        self.index += steps
        if self.index < len(self.tokens):
            self.current_token = self.tokens[self.index]
        else:
            self.current_token = EndOfFileToken()

    def peek(self, steps: int = 1) -> BaseToken | None:
        if self.index + steps < len(self.tokens):
            return self.tokens[self.index + steps]
        return EndOfFileToken()

    def check(self, expected_type: Type[T], steps: int = 0) -> bool:
        return isinstance(self.peek(steps), expected_type)

    def consume(self, expected_type: Type[T], err_msg: str = None) -> T:
        if not isinstance(self.current_token, expected_type):
            raise Exception(err_msg or f"Expected {expected_type.__name__} got {type(self.current_token).__name__} at {self.current_token_pos()}")
        token: T = self.current_token
        self.advance()
        return token
    
    def current_token_pos(self) -> str:
        return f"{self.current_token.line}:{self.current_token.column}"



    def parse_statement(self) -> ASTNode:
        expression = self.parse_expression()

        if self.check(AssignmentToken) or self.check(ColonToken):
            if not isinstance(expression, (IdentifierNode, AccessNode)):
                raise Exception(f"Invalid assignment target at {self.current_token_pos()}: {expression}")

            return self.parse_assignment(expression)
        elif self.check(OpenParenthesisToken):
            if not isinstance(expression, (IdentifierNode | AccessNode)):
                raise Exception(f"Invalid call target at {self.current_token_pos()}: {expression}")
            
            return self.parse_call(expression)

        return expression

    def get_prefix_binding_power(self) -> int | None:
        if self.check(MinusToken):
            return UNARY_PREFIX_BINDING_POWER
        return None

    def get_infix_binding_power(self) -> tuple[int, int] | None:
        if self.check(PlusToken) or self.check(MinusToken):
            return ADDITIVE_BINDING_POWER
        elif self.check(AsteriskToken) or self.check(SlashToken):
            return MULTIPLICATIVE_BINDING_POWER
        elif self.check(PercentToken):
            return MODULO_BINDING_POWER
        elif self.check(EqualToken) or self.check(NotEqualToken) or self.check(LessThanToken) or \
             self.check(GreaterThanToken) or self.check(LessOrEqualToken) or self.check(GreaterOrEqualToken):
            return COMPARISON_BINDING_POWER
        return None

    def parse_prefix(self) -> ASTNode:
        if self.check(MinusToken):
            binding_power = self.get_prefix_binding_power()
            operator_token = self.consume(MinusToken)
            operand = self.parse_expression(binding_power)
            return UnaryNegationNode(operand, operator_token.line, operator_token.column)
        elif self.check(OpenParenthesisToken):
            self.consume(OpenParenthesisToken)
            expr = self.parse_statement()
            self.consume(CloseParenthesisToken, f"Expected ')' after expression but got {self.current_token}")
            return expr
#region literals
        elif self.check(StringLiteralToken):
            return self.parse_string_literal()
        elif self.check(IntegerLiteralToken):
            return self.parse_integer_literal()
# endregion
        elif self.check(IdentifierToken):
            return self.parse_identifier()
# region keywords
        elif self.check(StructToken):
            return self.parse_struct()
        elif self.check(UnionToken):
            return self.parse_union()
        elif self.check(FuncToken):
            return self.parse_function()
        elif self.check(ReturnToken):
            token = self.consume(ReturnToken)
            expr = self.parse_statement()
            return ReturnNode(expr, token.line, token.column)
        elif self.check(IfToken):
            return self.parse_if()
        elif self.check(WhileToken):
            return self.parse_while()
        elif self.check(LenToken):
            return self.parse_len()
        elif self.check(ImportToken):
            return self.parse_import()
# endregion
        else:
            raise Exception(f"Unexpected token in expression: {self.current_token}")

    def parse_infix(self, left: ASTNode, binding_power: int) -> ASTNode:
        if self.check(PlusToken):
            operator_token = self.consume(PlusToken)
            right = self.parse_expression(binding_power)
            return BinaryAdditionNode(left, right, operator_token.line, operator_token.column)
        elif self.check(MinusToken):
            operator_token = self.consume(MinusToken)
            right = self.parse_expression(binding_power)
            return BinarySubtractionNode(left, right, operator_token.line, operator_token.column)
        elif self.check(AsteriskToken):
            operator_token = self.consume(AsteriskToken)
            right = self.parse_expression(binding_power)
            return BinaryMultiplicationNode(left, right, operator_token.line, operator_token.column)
        elif self.check(SlashToken):
            operator_token = self.consume(SlashToken)
            right = self.parse_expression(binding_power)
            return BinaryDivisionNode(left, right, operator_token.line, operator_token.column)
        elif self.check(PercentToken):
            operator_token = self.consume(PercentToken)
            right = self.parse_expression(binding_power)
            return BinaryModuloNode(left, right, operator_token.line, operator_token.column)

        elif self.check(EqualToken):
            operator_token = self.consume(EqualToken)
            right = self.parse_expression(binding_power)
            return BinaryEqualNode(left, right, operator_token.line, operator_token.column)
        elif self.check(NotEqualToken):
            operator_token = self.consume(NotEqualToken)
            right = self.parse_expression(binding_power)
            return BinaryNotEqualNode(left, right, operator_token.line, operator_token.column)
        elif self.check(LessThanToken):
            operator_token = self.consume(LessThanToken)
            right = self.parse_expression(binding_power)
            return BinaryLessThanNode(left, right, operator_token.line, operator_token.column)
        elif self.check(GreaterThanToken):
            operator_token = self.consume(GreaterThanToken)
            right = self.parse_expression(binding_power)
            return BinaryGreaterThanNode(left, right, operator_token.line, operator_token.column)
        elif self.check(LessOrEqualToken):
            operator_token = self.consume(LessOrEqualToken)
            right = self.parse_expression(binding_power)
            return BinaryLessOrEqualNode(left, right, operator_token.line, operator_token.column)
        elif self.check(GreaterOrEqualToken):
            operator_token = self.consume(GreaterOrEqualToken)
            right = self.parse_expression(binding_power)
            return BinaryGreaterOrEqualNode(left, right, operator_token.line, operator_token.column)

        raise Exception(f"Unexpected infix operator {self.current_token} at {self.current_token_pos()}")

    def parse_postfix(self, left: ASTNode) -> ASTNode:
        while True:
            if self.check(DotToken):
                self.consume(DotToken, f"Expected '.' but got {self.current_token}")
                member = self.consume(IdentifierToken, f"Expected member name after '.' but got {self.current_token}")
                left = MemberAccessNode(left, member.identifier, member.line, member.column)
            elif self.check(OpenBracketToken):
                self.consume(OpenBracketToken, f"Expected '[' but got {self.current_token}")
                index = self.parse_expression()
                left = IndexAccessNode(left, index, index.line, index.column)
                self.consume(CloseBracketToken, f"Expected ']' but got {self.current_token}")
            else:
                break

        return left

    def parse_expression(self, min_binding_power: int = 0) -> ASTNode:
        left = self.parse_prefix()

        while not (self.check(EndOfFileToken) or self.check(EndOfLineToken) or self.check(CloseParenthesisToken)):
            new_left = self.parse_postfix(left)
            if new_left is not left:
                left = new_left
                continue
            
            binding_powers = self.get_infix_binding_power()
            if binding_powers is None:
                break

            left_bp, right_bp = binding_powers
            if left_bp < min_binding_power:
                break

            left = self.parse_infix(left, right_bp)
        return left

    def parse_string_literal(self) -> StringLiteralNode:
        token = self.consume(StringLiteralToken, f"Expected string literal but got {self.current_token}")
        return StringLiteralNode(token.value, token.line, token.column)

    def parse_integer_literal(self) -> IntegerLiteralNode:
        token = self.consume(IntegerLiteralToken, f"Expected integer literal but got {self.current_token}")
        return IntegerLiteralNode(token.value, token.line, token.column)
    
    def parse_call(self, identifier_node: IdentifierNode | AccessNode) -> CallNode:
        call_node = CallNode(identifier_node.get_joined_name(), identifier_node.line, identifier_node.column)
        self.consume(OpenParenthesisToken, f"Expected '(' after function name but got {self.current_token}")

        while self.check(CloseParenthesisToken) is False:
            if self.check(EndOfFileToken):
                raise Exception(f"Unexpected end of file in function call at {self.current_token_pos()}")

            call_node.args.append(self.parse_statement())

            if self.check(CommaToken):
                self.advance()

                if self.check(CloseParenthesisToken):
                    raise Exception(f"Trailing comma in function call at {self.current_token_pos()}")
            elif self.check(CloseParenthesisToken) is False:
                raise Exception(f"Expected ',' or ')' after function argument but got {self.current_token}")

        self.consume(CloseParenthesisToken, f"Expected ')' after function arguments but got {self.current_token}")
        return call_node

    def parse_assignment(self, identifier_node: IdentifierNode | AccessNode) -> AssignmentNode:
        typed = None
        typed_arr_len = None
        if self.check(ColonToken):
            self.advance()
            typed = self.parse_qualified_name()

            if self.check(OpenBracketToken):
                self.advance()
                if self.check(IntegerLiteralToken):
                    arr_len_token = self.consume(IntegerLiteralToken, f"Expected array length integer literal after '[' but got {self.current_token}")
                    typed_arr_len = arr_len_token.value
                else:
                    typed_arr_len = -1 # dynamic array size

                self.consume(CloseBracketToken, f"Expected ']' after array length but got {self.current_token}")

        value_node = None
        if self.check(AssignmentToken):
            self.advance()
            value_node = self.parse_statement()

        return AssignmentNode(identifier_node, value_node, identifier_node.line, identifier_node.column, typed, typed_arr_len)

    def parse_identifier(self) -> IdentifierNode | AssignmentNode:
        token = self.consume(IdentifierToken, f"Expected identifier at {self.current_token_pos()} but got {self.current_token}")
        return IdentifierNode(token.identifier, token.line, token.column)

    def parse_struct(self) -> StructNode:
        token = self.consume(StructToken, f"Expected 'struct' keyword but got {self.current_token}")
        name_token = self.consume(IdentifierToken, f"Expected struct name but got {self.current_token}")
        self.consume(ColonToken, f"Expected ':' after struct name but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after struct declaration but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after struct declaration but got {self.current_token}")

        struct_node = StructNode(name_token.identifier, token.line, token.column)

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            field_node = self.parse_statement()
            if not isinstance(field_node, AssignmentNode):
                raise Exception(f"Expected field assignment in struct body but got {field_node}")
            struct_node.fields.append(field_node)
        self.consume(DedentToken, f"Expected dedentation after struct body but got {self.current_token}")

        return struct_node

    def parse_union(self) -> UnionNode:
        token = self.consume(UnionToken, f"Expected 'union' keyword but got {self.current_token}")
        name_token = self.consume(IdentifierToken, f"Expected union name but got {self.current_token}")
        self.consume(ColonToken, f"Expected ':' after union name but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after union declaration but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after union declaration but got {self.current_token}")

        union_node = UnionNode(name_token.identifier, token.line, token.column)

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            field_node = self.parse_statement()
            if not isinstance(field_node, AssignmentNode):
                raise Exception(f"Expected field assignment in union body but got {field_node}")
            union_node.fields.append(field_node)
        
        self.consume(DedentToken, f"Expected dedentation after union body but got {self.current_token}")
        return union_node

    def parse_function(self) -> FunctionNode:
        token = self.consume(FuncToken, f"Expected 'func' keyword but got {self.current_token}")
        name_token = self.consume(IdentifierToken, f"Expected function name but got {self.current_token}")
        self.consume(OpenParenthesisToken, f"Expected '(' after function name but got {self.current_token}")

        function_node = FunctionNode(name_token.identifier, token.line, token.column)
        
        while self.check(CloseParenthesisToken) is False:
            param = self.parse_identifier()
            param = self.parse_assignment(param)
            if not isinstance(param, AssignmentNode):
                raise Exception(f"Expected parameter assignment in function declaration but got {param}")
            elif param.value is not None:
                raise Exception(f"Function parameters cannot have default values, but got {param}")
            elif param.typed is None:
                raise Exception(f"Function parameters must have type annotations, but got {param}")

            function_node.params.append(param)

            if self.check(CommaToken):
                self.advance()

                if self.check(CloseParenthesisToken):
                    raise Exception(f"Trailing comma in function parameters but got {self.current_token}")

        self.consume(CloseParenthesisToken, f"Expected ')' after function parameters but got {self.current_token}")

        if self.check(ArrowToken):
            self.advance()
            function_node.return_type = self.parse_qualified_name()

        self.consume(ColonToken, f"Expected ':' after function declaration but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after function declaration but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after function declaration but got {self.current_token}")

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            function_node.body.append(self.parse_statement())
        self.consume(DedentToken, f"Expected dedentation after function body but got {self.current_token}")

        return function_node

    def parse_if(self) -> IfNode:
        token = self.consume(IfToken, f"Expected 'if' keyword but got {self.current_token}")
        condition = self.parse_expression()

        self.consume(ColonToken, f"Expected ':' after if condition but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after if condition but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after if condition but got {self.current_token}")

        if_node = IfNode(condition, token.line, token.column)

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            if_node.then_branch.append(self.parse_statement())
        self.consume(DedentToken, f"Expected dedentation after if body but got {self.current_token}")

        if self.check(ElseToken):
            else_branch = self.parse_else()
            if_node.else_branch = else_branch
        elif self.check(ElifToken):
            elif_node = self.parse_elif()
            if_node.else_branch.append(elif_node)

        return if_node

    def parse_else(self) -> list[ASTNode]:
        self.consume(ElseToken, f"Expected 'else' keyword but got {self.current_token}")
        self.consume(ColonToken, f"Expected ':' after else but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after else but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after else but got {self.current_token}")

        else_branch: list[ASTNode] = []

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            else_branch.append(self.parse_statement())
        self.consume(DedentToken, f"Expected dedentation after else body but got {self.current_token}")

        return else_branch

    def parse_elif(self) -> IfNode:
        token = self.consume(ElifToken, f"Expected 'elif' keyword but got {self.current_token}")
        condition = self.parse_expression()

        self.consume(ColonToken, f"Expected ':' after elif condition but got {self.current_token}")
        self.consume(EndOfLineToken, f"Expected end of line after elif condition but got {self.current_token}")
        self.consume(IndentToken, f"Expected indentation after elif condition but got {self.current_token}")

        elif_node = IfNode(condition, token.line, token.column)

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            elif_node.then_branch.append(self.parse_statement())
        self.consume(DedentToken, f"Expected dedentation after elif body but got {self.current_token}")

        if self.check(ElseToken):
            else_branch = self.parse_else()
            elif_node.else_branch = else_branch
        elif self.check(ElifToken):
            nested_elif_node = self.parse_elif()
            elif_node.else_branch.append(nested_elif_node)

        return elif_node

    def parse_while(self) -> WhileNode:
        token = self.consume(WhileToken, f"Expected 'while' keyword but got '{self.current_token}'")
        condition = self.parse_expression()

        self.consume(ColonToken, f"Expected ':' after while condition but got '{self.current_token}'")
        self.consume(EndOfLineToken, f"Expected end of line after while condition but got '{self.current_token}'")
        self.consume(IndentToken, f"Expected indentation after while condition but got '{self.current_token}'")

        while_node = WhileNode(condition, token.line, token.column)

        while self.check(DedentToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            while_node.body.append(self.parse_statement())
        self.consume(DedentToken, f"Expected dedentation after while body but got '{self.current_token}'")

        return while_node

    def parse_len(self) -> LenNode:
        token = self.consume(LenToken, f"Expected 'len' keyword but got '{self.current_token}'")
        self.consume(OpenParenthesisToken, f"Expected '(' after 'len' but got '{self.current_token}'")
        expr = self.parse_statement()
        self.consume(CloseParenthesisToken, f"Expected ')' after expression in 'len' but got '{self.current_token}'")
        return LenNode(expr, token.line, token.column)

    def parse_import(self) -> ImportNode:
        token = self.consume(ImportToken, f"Exspected 'import' keyword but got '{self.current_token}'")
        identifier = self.parse_qualified_name()
        self.consume(EndOfLineToken, f"Expected dedentation after while body but got '{self.current_token}'")
        return ImportNode(identifier, token.line, token.column)

    def parse_qualified_name(self) -> str:
        first = self.consume(IdentifierToken, f"Expected identifier at {self.current_token_pos()} but got {self.current_token}")
        parts = [first.identifier]

        while self.check(DotToken):
            self.advance()
            nxt = self.consume(IdentifierToken, f"Expected identifier after '.' at {self.current_token_pos()} but got {self.current_token}")
            parts.append(nxt.identifier)

        return "$".join(parts)

    def parse(self) -> ExpressionsNode:
        root = ExpressionsNode(0, 0)
        current = root

        while self.check(EndOfFileToken) is False:
            if self.check(EndOfLineToken):
                self.advance()
                continue

            current.children.append(self.parse_statement())
        return root
