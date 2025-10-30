from tokens import *

class Lexer:
    RESERVED_KEYWORDS = {
        "struct": StructToken,
        "func": FuncToken,
        "return": ReturnToken,
        "if": IfToken,
        "else": ElseToken,
        "elif": ElifToken,
        "while": WhileToken,
        "len": LenToken,
    }

    def __init__(self, data: str):
        if not data:
            raise ValueError("Input data for lexer cannot be empty")

        self.data = data
        self.tokens = []

        self.position = 0
        self.current_char = self.data[self.position]

        # indentation tracking
        self.indent_level = 0

        # line tracking
        self.line = 1
        self.column = 1

    def advance(self, steps: int = 1) -> None:
        self.position += steps
        self.column += steps

        if self.position < len(self.data):
            self.current_char = self.data[self.position]
        else:
            self.current_char = None

    def peek(self, steps: int = 1) -> str:
        if self.position + steps < len(self.data):
            return self.data[self.position + steps]
        return None

    def check(self, expected_char: str) -> bool:
        return self.current_char == expected_char

    def consume(self, expected_char: str, err_msg: str = None) -> None:
        if self.current_char != expected_char:
            raise Exception(err_msg or f"Expected '{expected_char}' at position {self.position}")
        self.advance()

    def new_line(self) -> None:
        self.line += 1
        self.column = 0

    def handle_indentation(self) -> None:
        if self.current_char == '\n' or (self.current_char == '/' and self.peek() == '/'):
            return

        # count indentation
        space_count = 0
        while self.position < len(self.data) and self.data[self.position] == ' ':
            space_count += 1
            self.advance()

        if space_count % 4 != 0:
            raise Exception(f"Indentation must be multiple of 4 spaces at line {self.line}")
        new_level = space_count // 4

        # indent
        if new_level > self.indent_level:
            for _ in range(new_level - self.indent_level):
                self.tokens.append(IndentToken(self.line, self.column))
            self.indent_level = new_level

        # dedent
        elif new_level < self.indent_level:
            for _ in range(self.indent_level - new_level):
                self.tokens.append(DedentToken(self.line, self.column))
            self.indent_level = new_level

    def string_literal(self) -> StringLiteralToken:
        self.consume('"', f"Expected '\"' at the start of string literal at {self.position}")

        start_pos = self.position
        while self.current_char is not None and self.current_char != '"':
            if self.current_char == "\n":
                self.new_line()

            self.advance()

        if self.current_char is None:
            raise Exception(f"Unterminated string literal at {self.position}")

        value = self.data[start_pos:self.position]
        self.advance()
        return StringLiteralToken(value, self.line, self.column - (self.position - start_pos) - 1)

    def identifier(self) -> IdentifierToken:
        start_pos = self.position
        while (self.current_char is not None and (self.current_char.isalnum() or self.current_char == '_')):
            self.advance()

        name = self.data[start_pos:self.position]
        return IdentifierToken(name, self.line, self.column - (self.position - start_pos))

    def tokenize(self) -> list[BaseToken]:
        # Handle indentation at start of file
        self.handle_indentation()
        
        while self.current_char is not None:
            # line tracking
            if self.current_char == '\n':
                self.new_line()

                if self.tokens and isinstance(self.tokens[-1], EndOfLineToken) is False:
                    self.tokens.append(EndOfLineToken(self.line, self.column))
                self.advance()
                
                # Handle indentation after newline
                self.handle_indentation()

            # comments
            elif self.current_char == '/' and self.peek() == '/':
                while self.current_char is not None and self.current_char != '\n':
                    self.advance()
                self.new_line()
                
                # Handle indentation after comment
                self.handle_indentation()

            # whitespace
            elif self.current_char.isspace():
                self.advance()

            # identifier
            elif self.current_char.isalpha() or self.current_char == '_':
                identifier = self.identifier()
                keyword = self.RESERVED_KEYWORDS.get(identifier.identifier)
                if keyword:
                    self.tokens.append(keyword(identifier.line, identifier.column))
                else:
                    self.tokens.append(identifier)

            # equals
            elif self.current_char == '=':
                # equals / greaterorequal / lesseorequal
                if self.peek() == '=':
                    self.tokens.append(EqualToken(self.line, self.column))
                    self.advance(2)
                else:
                    # assignment
                    self.tokens.append(AssignmentToken(self.line, self.column))
                    self.advance()
            
            elif self.current_char == '!' and self.peek() == '=':
                self.tokens.append(NotEqualToken(self.line, self.column))
                self.advance(2)

# region literals
            # string literal
            elif self.current_char == '"':
                self.tokens.append(self.string_literal())

            # integer literal
            elif self.current_char.isdigit():
                start_pos = self.position
                while self.current_char is not None and self.current_char.isdigit():
                    self.advance()
                value = int(self.data[start_pos:self.position])
                self.tokens.append(IntegerLiteralToken(value, self.line, self.column - (self.position - start_pos)))
# endregion

# region operators
            # plus
            elif self.current_char == '+':
                self.tokens.append(PlusToken(self.line, self.column))
                self.advance()

            # minus
            elif self.current_char == '-':
                # weird
                if self.peek() == '>':
                    self.tokens.append(ArrowToken(self.line, self.column))
                    self.advance(2)
                else:
                    self.tokens.append(MinusToken(self.line, self.column))
                    self.advance()

            # asterisk
            elif self.current_char == '*':
                self.tokens.append(AsteriskToken(self.line, self.column))
                self.advance()

            # slash
            elif self.current_char == '/':
                self.tokens.append(SlashToken(self.line, self.column))
                self.advance()

            # percent
            elif self.current_char == '%':
                self.tokens.append(PercentToken(self.line, self.column))
                self.advance()

            # less than
            elif self.current_char == '<':
                if self.peek() == '=':
                    self.tokens.append(LessOrEqualToken(self.line, self.column))
                    self.advance(2)
                else:
                    self.tokens.append(LessThanToken(self.line, self.column))
                    self.advance()

            # greater than
            elif self.current_char == '>':
                if self.peek() == '=':
                    self.tokens.append(GreaterOrEqualToken(self.line, self.column))
                    self.advance(2)
                else:
                    self.tokens.append(GreaterThanToken(self.line, self.column))
                    self.advance()
# endregion

            # parentheses
            elif self.current_char == '(':
                self.tokens.append(OpenParenthesisToken(self.line, self.column))
                self.advance()
            elif self.current_char == ')':
                self.tokens.append(CloseParenthesisToken(self.line, self.column))
                self.advance()

            # brackets
            elif self.current_char == '[':
                self.tokens.append(OpenBracketToken(self.line, self.column))
                self.advance()
            elif self.current_char == ']':
                self.tokens.append(CloseBracketToken(self.line, self.column))
                self.advance()

            # comma
            elif self.current_char == ',':
                self.tokens.append(CommaToken(self.line, self.column))
                self.advance()

            # colon
            elif self.current_char == ':':
                self.tokens.append(ColonToken(self.line, self.column))
                self.advance()
            
            # dot
            elif self.current_char == '.':
                self.tokens.append(DotToken(self.line, self.column))
                self.advance()

            else:
                raise Exception(f"Unexpected character: {self.current_char} at position {self.position}")

        # Emit remaining dedents at EOF
        for _ in range(self.indent_level):
            self.tokens.append(DedentToken(self.line, self.column))

        return self.tokens + [EndOfFileToken(self.line, self.column)]
