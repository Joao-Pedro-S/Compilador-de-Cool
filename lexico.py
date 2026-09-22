##################################################################################
# uso:
#   instância de Lexico é inicializada com o caminho de um arquivo com código cool
#   função interpretar da instância retorna a lista de tokens do arquivo em ordem
# exemplo:
#   scanner = Lexico({caminho fonte})
#   tokens = scanner.interpretar()
#   for tok in tokens:
#   . . .
##################################################################################
from dataclasses import dataclass # usado para simplificar o token

KEYWORDS = {
    "class": "CLASS",
    "else": "ELSE",
    "fi": "FI",
    "if": "IF",
    "in": "IN",
    "inherits": "INHERITS",
    "isvoid": "ISVOID",
    "let": "LET",
    "loop": "LOOP",
    "pool": "POOL",
    "then": "THEN",
    "while": "WHILE",
    "case": "CASE",
    "esac": "ESAC",
    "new": "NEW",
    "of": "OF",
    "not": "NOT",
    #"true": "TRUE", # talvez tirar daqui
    #"false": "FALSE" # talvez tirar daqui
}
OP_MULTI = { #acabou não sendo usado diretamente
    "<-": "ASSIGN",
    "<=": "LE", # MENOR(lower) ou IGUAL(equal)
    "=>": "ARROW" # sintaxe de case, é só uma seta
}
OP_UNI = {
    "+": "PLUS",
    "-": "MINUS",
    "*": "TIMES",
    "/": "DIVIDE",
    "~": "NEGATIVE",
    "<": "LT", # MENOR QUE/LOWER THAN
    "=": "EQUALS",
    "(": "LPAREN",
    ")": "RPAREN",
    "{": "LBRACKET",
    "}": "RBRACKET",
    ":": "COLON",
    ";": "SEMI",
    ",": "COMMA",
    ".": "DOT",
    "@": "AT"
}

@dataclass
class Token:
    tipo: str
    lexema: str
    linha: int

    def __str__(self) -> str: # o que deve ser printado quando/se necessario
        return f"| {self.linha} {self.tipo} {self.lexema}"
        # printa algumas coisas com lexemas redundantes como "IF if",
        # mas a fim de evitar uma cadeia de ifs, permaneceu assim

# ANALISADOR LÉXICO

class Lexico:
    def __init__(self, fonte: str):
        self.src = fonte
        self.pos = 0
        self.linha = 1
        self.tamanho = len(fonte)
        self.tokens = []
    ## métodos de assistência
    # lê um caráter
    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < self.tamanho else ""

    # "come" um caráter
    def _advance(self):
        char = self.src[self.pos]
        self.pos += 1
        if char == "\n":
            self.linha += 1
        return char

    def _fim(self):
        return self.pos >= self.tamanho

    def _save(self, linha: int, tipo: str, lexema: str):
        self.tokens.append(Token(tipo, lexema, linha))
    ## métodos de tratamento
    # comentários
    def _pular_linha(self):
        while not self._fim() and self._peek() != "\n":
            self._advance()
    def _pular_bloco(self):
        inicio = self.linha
        # "comer" os caracteres (*
        self._advance()
        self._advance()
        # comentário pode ser aninhado
        profundidade = 1
        while profundidade > 0:
            if self._fim():
                self._save(inicio, "ERRO", "Comentario em fim de arquivo")
                return
            elif self._peek() == "(" and self._peek(1) == "*":
                self._advance()
                self._advance()
                profundidade += 1
            elif self._peek() == "*" and self._peek(1) == ")":
                self._advance()
                self._advance()
                profundidade -= 1
            else:
                self._advance()

    # strings
    def _ler_string(self):
        inicio = self.linha
        self._advance()
        chars = []
        while True:
            if self._fim():
                self._save(inicio, "ERRO", "String nao acaba em fim de arquivo")
                return

            ch = self._peek()

            if ch == '"': # fim de string
                self._advance()
                break

            if ch == "\n":
                self._advance()
                self._save(inicio, "ERRO", "String nao pode conter quebra de linha")
                return

            if ch == "\\":
                self._advance()
                if self._fim():
                    self._save(inicio, "ERRO", "String nao acaba em fim de arquivo")
                    return
                ch = self._advance()
                if ch == "n":
                    chars.append("\n")
                elif ch == "t":
                    chars.append("\t")
                elif ch == "b":
                    chars.append("\b")
                elif ch == "f":
                    chars.append("\f")
                elif ch == "\n":
                    chars.append("\n")
                elif ch == "\0":
                    self._save(inicio, "ERRO", "String nao pode conter null (\\0)")
                    return
                else:
                    chars.append(ch)
                continue
            if ch == "\0":
                self._advance()
                self._save(inicio, "ERRO", "String nao pode conter null (\\0)")
                return
            chars.append(ch)
            self._advance()
        # converte a lista de chars em uma única string para usar de lexema
        self._save(inicio, "STR_CONST", "".join(chars))

    # números
    def _ler_int(self):
        inicio = self.pos
        while not self._fim() and self._peek().isdigit():
            self._advance()
        lex = self.src[inicio:self.pos]
        self._save(self.linha, "INT_CONST", lex)

    # keywords
    def _ler_identificador(self):
        inicio = self.pos
        while not self._fim() and self._peek().isalnum() or self._peek() == "_":
            self._advance()
        lex = self.src[inicio:self.pos]
        #converte o lex todo em minúsculo pelo bem de ser case insensitive
        lexm = lex.lower()
        if lexm in KEYWORDS:
            self._save(self.linha, KEYWORDS[lexm], lex)

        elif lexm == "true" and lex[0] == "t":
            self._save(self.linha, "TRUE", lex)

        elif lexm == "false" and lex[0] == "f":
            self._save(self.linha, "FALSE", lex)

        elif lex[0].isupper():
            self._save(self.linha, "TIPO", lex) # tipo deve começar maiúsculo
        else:
            self._save(self.linha, "ID", lex) # objeto

    # operadores de múltiplos caracteres
    def _ler_op_multi(self):
        if self._peek() == "<":
            if self._peek(1) == "-":
                self._advance()
                self._advance()
                self._save(self.linha, "ASSIGN", "<-")
                return True
            if self._peek(1) == "=":
                self._advance()
                self._advance()
                self._save(self.linha, "LE", "<=")
                return True
        if self._peek() == "=" and self._peek(1) == ">":
            self._advance()
            self._advance()
            self._save(self.linha, "ARROW", "=>")
            return True
        return False

    ## PRINCIPAL
    def interpretar(self):
        while not self._fim():
            char = self._peek()
            if char in " \t\r\f\v\n":
                self._advance()
                continue
            if char == "-" and self._peek(1) == "-":
                self._pular_linha()
                continue
            if char == "(" and self._peek(1) == "*":
                self._pular_bloco()
                continue
            if char == "*" and self._peek(1) == ")":
                self._save(self.linha, "ERRO", "*) encontrado sem bloco de comentario")
                continue
            if char == '"':
                self._ler_string()
                continue
            if char.isdigit():
                self._ler_int()
                continue
            if char.isalpha() or char == "_":
                self._ler_identificador()
                continue
            if self._ler_op_multi():
                continue
            if char in OP_UNI:
                self._advance()
                self._save(self.linha, OP_UNI[char], char)
                continue

            # caráter desconhecido
            self._save(self.linha, "DESCONHECIDO", char)
            self._advance()

        self._save(self.linha, "EOF", "eof")
        return self.tokens