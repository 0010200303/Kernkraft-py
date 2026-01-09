import abc

class BaseToken(abc.ABC):
    line: int
    column: int

    def __init__(self, line: int, column: int):
        self.line = line
        self.column = column

    # @abc.abstractmethod
    def __repr__(self):
        return f"{self.__class__.__name__} at {self.line}:{self.column}"
    
class EndOfFileToken(BaseToken):
    pass

class EndOfLineToken(BaseToken):
    pass

class IndentToken(BaseToken):
    pass

class DedentToken(BaseToken):
    pass

class OpenParenthesisToken(BaseToken):
    pass

class CloseParenthesisToken(BaseToken):
    pass

class OpenBracketToken(BaseToken):
    pass

class CloseBracketToken(BaseToken):
    pass

class CommaToken(BaseToken):
    pass

class ColonToken(BaseToken):
    pass

class DotToken(BaseToken):
    pass

class ArrowToken(BaseToken):
    pass

class IdentifierToken(BaseToken):
    def __init__(self, identifier: str, line: int, column: int):
        super().__init__(line, column)
        self.identifier = identifier

    def __repr__(self):
        return f"IdentifierToken({self.identifier}) at {self.line}:{self.column}"

class AssignmentToken(BaseToken):
    pass

# region literals
class StringLiteralToken(BaseToken):
    def __init__(self, value: str, line: int, column: int):
        super().__init__(line, column)
        self.value = value

    def __repr__(self):
        return f'StringLiteralToken("{self.value}") at {self.line}:{self.column}'

class IntegerLiteralToken(BaseToken):
    def __init__(self, value: int, line: int, column: int):
        super().__init__(line, column)
        self.value = value

    def __repr__(self):
        return f"IntegerLiteralToken({self.value}) at {self.line}:{self.column}"

class CharLiteralToken(BaseToken):
    def __init__(self, value: str, line: int, column: int):
        super().__init__(line, column)
        self.value = value

    def __repr__(self):
        return f"CharLiteralToken('{self.value}' at {self.line}:{self.column})"
# endregion

# region operators
class PlusToken(BaseToken):
    pass

class MinusToken(BaseToken):
    pass

class AsteriskToken(BaseToken):
    pass

class SlashToken(BaseToken):
    pass

class PercentToken(BaseToken):
    pass

class EqualToken(BaseToken):
    pass

class NotEqualToken(BaseToken):
    pass

class LessThanToken(BaseToken):
    pass

class GreaterThanToken(BaseToken):
    pass

class LessOrEqualToken(BaseToken):
    pass

class GreaterOrEqualToken(BaseToken):
    pass

class AndToken(BaseToken):
    pass

class OrToken(BaseToken):
    pass
# endregion

# region keywords
class StructToken(BaseToken):
    pass

class UnionToken(BaseToken):
    pass

class FuncToken(BaseToken):
    pass

class ReturnToken(BaseToken):
    pass

class IfToken(BaseToken):
    pass

class ElseToken(BaseToken):
    pass

class ElifToken(BaseToken):
    pass

class WhileToken(BaseToken):
    pass

class LenToken(BaseToken):
    pass

class ImportToken(BaseToken):
    pass

class IsToken(BaseToken):
    pass

class ContinueToken(BaseToken):
    pass

class TrueToken(BaseToken):
    pass

class FalseToken(BaseToken):
    pass
# endregion
