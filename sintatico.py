#########################################################
#uso:
#   inicializa o parser recebendo uma lista de tokens:
#       parser = Sintatico(tokens)
#   usa a função analisar para criar a árvore sintática:
#        ast = parser.analisar()
#   mostrar_ast(ast) imprime a árvore criada
#
#   exemplo:
#    if parser.erros:
#        for e in parser.erros: print(e) #erros encontrados podem ser listados
#    else:
#        print(sintatico.mostrar_ast(ast))
#########################################################
from dataclasses import dataclass, fields

COMPARADORES = ("LT", "LE", "EQUALS") #será usado para verificar expressões

@dataclass
class No: #Nó. Herdado por todas as outras classes usadas
    linha: int

@dataclass
class Programa(No):
    Classes: list[Classe]

@dataclass
class Classe(No):
    nome: str
    herda: str | None #opcional, usado para denotar herança de classes
    features: list[str]

@dataclass
class Metodo(No):
    nome: str
    formais: list[Formal]
    tipo: str
    corpo: No

@dataclass
class Formal(No):
    nome: str
    tipo: str

@dataclass
class Atributo(No):
    nome: str
    tipo: str
    init: No | None # Atr <- expr

# EXPRESSÕES

@dataclass
class Atribuicao(No):
    nome: str
    valor: No

@dataclass
class Despacho(No): #Dispatch, página 10 no manual
    objeto: No | None
    tipo_estatico: str | None
    metodo: str
    argumentos: list[No]

@dataclass
class Se(No):
    condicao: No
    entao: No
    senao: No

@dataclass
class Enquanto(No):
    condicao: No
    corpo: No

@dataclass
class Bloco(No):
    expressoes: list[No]

@dataclass
class Ligacao(No):
    nome: str
    tipo: str
    init: No | None

@dataclass
class Let(No):
    ligacoes: list[Ligacao]
    corpo: No

@dataclass
class Ramo(No): # ramo dentro de um case (x : T => e)
    nome: str
    tipo: str
    corpo: No

@dataclass
class Caso(No): # case
    expressao: No
    ramos: list[Ramo]

@dataclass
class Novo(No):
    tipo: str

@dataclass
class IsVoid(No):
    expressao: No

@dataclass
class OpBin(No): # operação entre 2 expressões
    op: str
    esquerda: No
    direita: No

@dataclass
class OpUn(No): # operação que afeta apenas 1 expressão
    op: str
    expressao: No

@dataclass
class Objeto(No):
    nome: str

@dataclass
class ConstInt(No):
    valor: int

@dataclass
class ConstString(No):
    valor: str

@dataclass
class ConstBool(No):
    valor: bool

## estrutura de erros

class ErroSintatico(Exception):
    def __init__(self, linha: int, mensagem: str, lexema: str = ""):
        self.linha = linha
        self.mensagem = mensagem
        self.lexema = lexema
        super().__init__(str(self))

    def __str__(self):
        encontrado = f" (encontrado '{self.lexema}')" if self.lexema else ""
        return f"| linha {self.linha}: {self.mensagem}{encontrado}"

### analisador sintático

class Sintatico:
    def __init__(self, tokens):
        self.erros = [] # conterá lista de erros (classe ErroSintatico)
        self.tokens = []
        for tok in tokens:
            if tok.tipo == "ERRO":
                self.erros.append(ErroSintatico(tok.linha, f"Erro léxico: {tok.lexema}"))
            elif tok.tipo == "DESCONHCIDO":
                self.erros.append(ErroSintatico(tok.linha, f"Erro léxico: caractere desconhecido '{tok.lexema}'"))
            else:
                self.tokens.append(tok)
        self.pos = 0
        self.profundidade = 0

    # métodos auxiliares

    def _peek(self, offset: int = 0):
        i = self.pos + offset
        return self.tokens[i]

    def _tipo(self):
        return self._peek().tipo

    def _fim(self):
        return self._tipo() == "EOF"

    def _advance(self):
        tok = self._peek()
        if not self._fim():
            self.pos += 1
        if tok.tipo == "LBRACKET":
            self.profundidade += 1
        elif tok.tipo == "RBRACKET":
            self.profundidade -= 1
        return tok

    def _checar(self, *tipos):
        return self._tipo() in tipos

    def _aceitar(self, *tipos):
        if self._checar(*tipos):
            return self._advance()
        return None

    def _esperado(self, tipo: str, contexto: str = ""):
        if self._checar(tipo):
            return self._advance()
        raise self._erro(f'Esperado {tipo} {contexto}.')

    def _erro(self, mensagem: str):
        tok = self._peek()
        return ErroSintatico(tok.linha, mensagem, tok.lexema)

    ## Recuperação de erros
    def _sincronizar_feature(self, base: int):
        # pula a feature atual para continuar a analise
        while not self._fim():
            if self.profundidade == base:
                if self._checar("SEMI"):
                    self._advance()
                    return
                if self._checar("RBRACKET"):
                    return
            self._advance()

    def _sincronizar_classe(self):
        # pula a classe atual para continuar a analise
        while not self._fim() and not self._checar("CLASS"):
            self._advance()
        self.profundidade = 0

    ## Principal
    def analisar(self):
        linha = self._peek().linha
        classes = []
        while not self._fim():
            if not self._checar("CLASS"):
                self.erros.append(self._erro("Esperado 'class' no inicio do programa!"))
                self._sincronizar_classe()
                continue
            try:
                classes.append(self._classe())
                self._esperado("SEMI", 'após o fim da classe')
            except ErroSintatico as e:
                self.erros.append(e)
                self._sincronizar_classe()
        if not classes and not self.erros:
            self.erros.append(self._erro("Programa vazio!"))
        return Programa(linha, classes)

    def _classe(self):
        linha = self._esperado("CLASS").linha
        nome = self._esperado("TIPO", "como nome da classe").lexema
        pai = None
        if self._aceitar("INHERITS"):
            pai = self._esperado("TIPO", "após 'inherits'").lexema
        self._esperado("LBRACKET", "abrindo o corpo da classe")
        base = self.profundidade
        features = []
        while not self._fim() and not self._checar("RBRACKET"):
            try:
                features.append(self._feature())
                self._esperado("SEMI", "após a feature")
            except ErroSintatico as e:
                self.erros.append(e)
                self._sincronizar_feature(base)
        self._esperado("RBRACKET", "fechando o corpo da classe")
        return Classe(linha, nome, pai, features)

    def _feature(self):
        tok = self._esperado("ID", "como nome de metodo ou atributo")
        #método
        if self._aceitar("LPAREN"):
            formais = []
            if not self._checar("RPAREN"):
                formais.append(self._formal())
                while self._aceitar("COMMA"):
                    formais.append(self._formal())
            self._esperado("RPAREN", "fechando os parametros")
            self._esperado("COLON", "antes do tipo de retorno")
            tipo = self._esperado("TIPO", "como tipo de retorno").lexema
            self._esperado("LBRACKET", "abrindo o corpo do metodo")
            corpo = self._expressao()
            self._esperado("RBRACKET", "fechando o corpo do metodo")
            return Metodo(tok.linha, tok.lexema, formais, tipo, corpo)
        #atributo
        self._esperado("COLON", "após o nome do atributo")
        tipo = self._esperado("TIPO", "como tipo do atributo").lexema
        init = self._expressao() if self._aceitar("ASSIGN") else None
        return Atributo(tok.linha, tok.lexema, tipo, init)

    def _formal(self):
        tok = self._esperado("ID", "como nome do parametro")
        self._esperado("COLON", "após o nome do parametro")
        tipo = self._esperado("TIPO", "como tipo do parametro").lexema
        return Formal(tok.linha, tok.lexema, tipo)

    ## Expressões
    # > atribuição > not > comparação > adição > multiplicação > vazio > negação > dispatch > constantes/composições >

    def _expressao(self):
        if self._checar("ID") and self._peek(1).tipo == "ASSIGN":
            tok = self._advance()
            self._advance()
            return Atribuicao(tok.linha, tok.lexema, self._expressao())
        return self._nao()

    def _nao(self):
        tok = self._aceitar("NOT")
        if tok:
            return OpUn(tok.linha, "not", self._nao())
        return self._comparacao()

    def _comparacao(self):
        esq = self._aditiva() # chama aditiva primeiro, pois _aceitar() avança o token
        tok = self._aceitar(*COMPARADORES)
        if not tok:
            return esq # se não houver comparação, segue para a aditiva
        no = OpBin(tok.linha, tok.lexema, esq, self._aditiva()) # expr comparador expr
        if self._checar(*COMPARADORES):
            raise self._erro("comparações não são associativas, faltam parênteses")
        return no

    def _aditiva(self):
        no = self._multiplicativa()
        while True:
            tok = self._aceitar("PLUS", "MINUS")
            if not tok:
                return no
            no = OpBin(tok.linha, tok.lexema, no, self._multiplicativa())

    def _multiplicativa(self):
        no = self._vazio()
        while True:
            tok = self._aceitar("TIMES", "DIVIDE")
            if not tok:
                return no
            no = OpBin(tok.linha, tok.lexema, no, self._vazio())

    def _vazio(self):
        tok = self._aceitar("ISVOID")
        if tok:
            return IsVoid(tok.linha, self._vazio())
        return self._negacao()

    def _negacao(self):
        tok = self._aceitar("NEGATIVE")
        if tok:
            return OpUn(tok.linha, "~", self._negacao())
        return self._despacho()

    def _despacho(self):
        no = self._primaria()
        while self._checar("DOT", "AT"):
            tok = self._advance()
            tipo_estatico = None
            if tok.tipo == "AT":
                tipo_estatico = self._esperado("TIPO", "apos '@'").lexema
                self._esperado("DOT", "apos o tipo estatico")
            metodo = self._esperado("ID", "como nome do metodo chamado")
            self._esperado("LPAREN", "abrindo os argumentos")
            args = self._argumentos()
            self._esperado("RPAREN", "fechando os argumentos")
            no = Despacho(tok.linha, no, tipo_estatico, metodo.lexema, args)
        return no

    def _argumentos(self):
        args = []
        if not self._checar("RPAREN"):
            args.append(self._expressao())
            while self._aceitar("COMMA"):
                args.append(self._expressao())
        return args

    def _primaria(self):
        tok = self._peek()

        if tok.tipo == "ID":
            self._advance()
            # chamada implicita em self: ID ( args )
            if self._aceitar("LPAREN"):
                args = self._argumentos()
                self._esperado("RPAREN", "fechando os argumentos")
                return Despacho(tok.linha, None, None, tok.lexema, args)
            return Objeto(tok.linha, tok.lexema)

        if tok.tipo == "INT_CONST":
            self._advance()
            return ConstInt(tok.linha, tok.lexema)

        if tok.tipo == "STR_CONST":
            self._advance()
            return ConstString(tok.linha, tok.lexema)

        if tok.tipo in ("TRUE", "FALSE"):
            self._advance()
            return ConstBool(tok.linha, tok.tipo == "TRUE")

        if tok.tipo == "LPAREN":
            self._advance()
            no = self._expressao()
            self._esperado("RPAREN", "fechando a expressão entre parênteses")
            return no

        if tok.tipo == "LBRACKET":
            return self._bloco()

        if tok.tipo == "IF":
            return self._se()

        if tok.tipo == "WHILE":
            return self._enquanto()

        if tok.tipo == "LET":
            return self._let()

        if tok.tipo == "CASE":
            return self._caso()

        if tok.tipo == "NEW":
            self._advance()
            tipo = self._esperado("TIPO", "após 'new'").lexema
            return Novo(tok.linha, tipo)

        raise self._erro("esperado uma expressão")

    # Composições
    def _bloco(self):
        linha = self._esperado("LBRACKET").linha
        expressoes = [self._expressao()]
        self._esperado("SEMI", "após a expressão do bloco")
        while not self._checar("RBRACKET") and not self._fim():
            expressoes.append(self._expressao())
            self._esperado("SEMI", "após a expressão do bloco")
        self._esperado("RBRACKET", "fechando o bloco")
        return Bloco(linha, expressoes)

    def _se(self):
        linha = self._esperado("IF").linha
        condicao = self._expressao()
        self._esperado("THEN", "após a condição do if")
        entao = self._expressao()
        self._esperado("ELSE", "todo if precisa de else")
        senao = self._expressao()
        self._esperado("FI", "fechando o if")
        return Se(linha, condicao, entao, senao)

    def _enquanto(self):
        linha = self._esperado("WHILE").linha
        condicao = self._expressao()
        self._esperado("LOOP", "após a condição do while")
        corpo = self._expressao()
        self._esperado("POOL", "fechando o while")
        return Enquanto(linha, condicao, corpo)

    def _let(self):
        linha = self._esperado("LET").linha
        ligacoes = [self._ligacao()]
        while self._aceitar("COMMA"):
            ligacoes.append(self._ligacao())
        self._esperado("IN", "após as declarações do let")
        # o corpo do let se estende o maximo possivel para a direita
        corpo = self._expressao()
        return Let(linha, ligacoes, corpo)

    def _ligacao(self):
        tok = self._esperado("ID", "como nome da variável do let")
        self._esperado("COLON", "após o nome da variável")
        tipo = self._esperado("TIPO", "como tipo da variável").lexema
        init = self._expressao() if self._aceitar("ASSIGN") else None
        return Ligacao(tok.linha, tok.lexema, tipo, init)

    def _caso(self):
        linha = self._esperado("CASE").linha
        expressao = self._expressao()
        self._esperado("OF", "após a expressão do case")
        ramos = [self._ramo()]
        while not self._checar("ESAC") and not self._fim():
            ramos.append(self._ramo())
        self._esperado("ESAC", "fechando o case")
        return Caso(linha, expressao, ramos)

    def _ramo(self):
        tok = self._esperado("ID", "como variável do ramo do case")
        self._esperado("COLON", "após a variável do ramo")
        tipo = self._esperado("TIPO", "como tipo do ramo").lexema
        self._esperado("ARROW", "após o tipo do ramo")
        corpo = self._expressao()
        self._esperado("SEMI", "após o corpo do ramo")
        return Ramo(tok.linha, tok.lexema, tipo, corpo)

### métodos para impressão

def mostrar_ast(no):
    saida = []
    nivel = 0
    _mostrar(no, nivel, saida)
    return "\n".join(saida)

def _mostrar(no, nivel: int, saida: list[str]):
    ident = "  " * nivel
    if isinstance(no, No):
        saida.append(f"{ident}{type(no).__name__} [linha {no.linha}]")
        for campo in fields(no):
            if campo.name == "linha":
                continue
            valor = getattr(no, campo.name)
            if isinstance(valor, (No, list)):
                if isinstance(valor, list) and not valor:
                    saida.append(f"{ident}  {campo.name}: (vazio)")
                    continue
                saida.append(f"{ident}  {campo.name}:")
                _mostrar(valor, nivel + 2, saida)
            elif valor is None:
                saida.append(f"{ident}  {campo.name}: -")
            else:
                saida.append(f"{ident}  {campo.name}: {valor}")
    elif isinstance(no, list):
        for item in no:
            _mostrar(item, nivel, saida)