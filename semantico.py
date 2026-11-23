from dataclasses import dataclass

from sintatico import (
    Atributo, Atribuicao, Bloco, Caso, Classe,
    Despacho, Enquanto, IsVoid, Let, Metodo,
    No, Novo, Objeto, OpBin, OpUn, Se,
)

SELF = "SELF_TYPE"
BASICOS = ("Int", "String", "Bool") # pra comparações
NAO_HERDAVEIS = ("Int", "String", "Bool", SELF)

## estrutura de erros

@dataclass
class ErroSemantico(Exception):
    def __init__(self, linha, mensagem):
        self.linha = linha
        self.mensagem = mensagem
        super().__init__(str(self))

    def __str__(self):
        return f"| linha {self.linha}: Erro semântico: {self.mensagem}"

## tabelas

@dataclass
class Assinatura:
    nome: str
    formais: list[tuple[str, str]]  # (nome, tipo)
    retorno: str
    classe: str                     # onde foi definido
    linha: int

class InfoClasse:
    def __init__(self, nome: str, pai: str | None, linha: int, basica: bool = False):
        self.nome = nome
        self.pai = pai
        self.linha = linha
        self.basica = basica
        self.atributos = {}         # atributos proprios: nome -> tipo
        self.todos_atributos = {}   # proprios + herdados
        self.metodos = {}           # metodos proprios: nome -> Assinatura

### analisador semantico

class Semantico:
    def __init__(self, ast):
        self.ast = ast
        self.erros = []
        self.classes = {}           # nome -> InfoClasse
        self.nos = {}               # nome -> Classe (apenas classes do usuario aceitas)
        self.classe_atual = None
        self.escopos = []           # pilha de dicts nome -> tipo
        self._criar_basicas()

    def _erro(self, linha, mensagem):
        self.erros.append(ErroSemantico(linha, mensagem))

    def _criar_basicas(self):
        basicas = {
            "Object": (None, [
                ("abort", [], "Object"),
                ("type_name", [], "String"),
                ("copy", [], SELF),
            ]),
            "IO": ("Object", [
                ("out_string", [("x", "String")], SELF),
                ("out_int", [("x", "Int")], SELF),
                ("in_string", [], "String"),
                ("in_int", [], "Int"),
            ]),
            "Int": ("Object", []),
            "Bool": ("Object", []),
            "String": ("Object", [
                ("length", [], "Int"),
                ("concat", [("s", "String")], "String"),
                ("substr", [("i", "Int"), ("l", "Int")], "String"),
            ]),
        }
        for nome, (pai, metodos) in basicas.items():
            info = InfoClasse(nome, pai, 0, basica=True)
            for m, formais, ret in metodos:
                info.metodos[m] = Assinatura(m, formais, ret, nome, 0)
            self.classes[nome] = info

    # métodos auxiliares
    def _profundidade(self, nome: str) -> int:
        d = 0
        while self.classes[nome].pai is not None:
            nome = self.classes[nome].pai
            d += 1
        return d

    def _ancestrais(self, nome: str) -> list[str]:
        cadeia = []
        while nome is not None:
            cadeia.append(nome)
            nome = self.classes[nome].pai
        return cadeia

    def _tipo_existe(self, tipo: str) -> bool:
        return tipo == SELF or tipo in self.classes

    def _buscar_metodo(self, classe: str, metodo: str):
        while classe is not None:
            info = self.classes[classe]
            if metodo in info.metodos:
                return info.metodos[metodo]
            classe = info.pai
        return None

    ## principal
    def analisar(self):
        self._registrar_classes()
        self._validar_heranca()
        for nome in sorted(self.nos, key=self._profundidade):  #processa parentes primeiro
            self._coletar_features(nome)
        self._verificar_main()
        for nome, no in self.nos.items():
            self._checar_classe(no)
        self.erros.sort(key=lambda e: e.linha)
        return self.erros

    ## classes e heranca
    def _registrar_classes(self):
        for c in self.ast.Classes:
            if c.nome == SELF:
                self._erro(c.linha, "SELF_TYPE não pode ser nome de classe")
            elif c.nome in self.classes:
                if self.classes[c.nome].basica:
                    self._erro(c.linha, f"classe básica '{c.nome}' não pode ser redefinida")
                else:
                    self._erro(c.linha, f"classe '{c.nome}' já foi definida")
            else:
                self.classes[c.nome] = InfoClasse(c.nome, c.herda or "Object", c.linha)
                self.nos[c.nome] = c

    def _validar_heranca(self):
        for nome in self.nos:
            info = self.classes[nome]
            if info.pai in NAO_HERDAVEIS:
                self._erro(info.linha, f"classe '{nome}' não pode herdar de '{info.pai}'")
                info.pai = "Object" #evita outros erros
            elif info.pai not in self.classes:
                self._erro(info.linha, f"classe '{nome}' herda de '{info.pai}', que não existe")
                info.pai = "Object"
        #ciclos
        for nome in self.nos:
            visto = set()
            atual = nome
            while atual is not None and atual != "Object":
                if atual in visto:
                    self._erro(self.classes[atual].linha, f"herança cíclica envolvendo '{atual}'")
                    self.classes[atual].pai = "Object"  #quebra ciclo pra evitar problemas checando parentes no futuro
                    break
                visto.add(atual)
                atual = self.classes[atual].pai


    ## features
    def _coletar_features(self, nome: str):
        info = self.classes[nome]
        info.todos_atributos = dict(self.classes[info.pai].todos_atributos)
        for f in self.nos[nome].features:
            if isinstance(f, Atributo):
                self._declarar_atributo(info, f)
            elif isinstance(f, Metodo):
                self._declarar_metodo(info, f)

    def _declarar_atributo(self, info: InfoClasse, f: Atributo):
        if f.nome == "self":
            self._erro(f.linha, "'self' não pode ser nome de atributo")
            return
        tipo = f.tipo
        if not self._tipo_existe(tipo):
            self._erro(f.linha, f"atributo '{f.nome}' tem tipo '{tipo}', que não existe")
            tipo = "Object"
        if f.nome in info.atributos:
            self._erro(f.linha, f"atributo '{f.nome}' já foi definido em '{info.nome}'")
        elif f.nome in info.todos_atributos:
            self._erro(f.linha, f"atributo '{f.nome}' já existe em uma classe ancestral de '{info.nome}'")
        else:
            info.atributos[f.nome] = tipo
            info.todos_atributos[f.nome] = tipo

    def _declarar_metodo(self, info: InfoClasse, f: Metodo):
        formais = []
        nomes = set()
        for p in f.formais:
            tipo = p.tipo
            if p.nome == "self":
                self._erro(p.linha, "'self' não pode ser nome de parâmetro")
            elif p.nome in nomes:
                self._erro(p.linha, f"parâmetro '{p.nome}' repetido no método '{f.nome}'")
            nomes.add(p.nome)
            if tipo == SELF:
                self._erro(p.linha, f"parâmetro '{p.nome}' não pode ter tipo SELF_TYPE")
                tipo = "Object"
            elif tipo not in self.classes:
                self._erro(p.linha, f"parâmetro '{p.nome}' tem tipo '{tipo}', que não existe")
                tipo = "Object"
            formais.append((p.nome, tipo))

        retorno = f.tipo
        if not self._tipo_existe(retorno):
            self._erro(f.linha, f"método '{f.nome}' retorna '{retorno}', que não existe")
            retorno = "Object"

        if f.nome in info.metodos:
            self._erro(f.linha, f"método '{f.nome}' já foi definido em '{info.nome}'")
            return

        herdado = self._buscar_metodo(info.pai, f.nome)
        if herdado is not None:
            if [t for m, t in herdado.formais] != [t for m, t in formais]:
                self._erro(f.linha, f"override de '{f.nome}' com parâmetros diferentes de '{herdado.classe}'")
            elif herdado.retorno != retorno:
                self._erro(f.linha, f"override de '{f.nome}' com tipo de retorno diferente de '{herdado.classe}'")

        info.metodos[f.nome] = Assinatura(f.nome, formais, retorno, info.nome, f.linha)

    def _verificar_main(self):
        if "Main" not in self.nos:
            self._erro(self.ast.linha, "o programa precisa ter uma classe 'Main'")
            return
        sig = self._buscar_metodo("Main", "main")
        if sig is None:
            self._erro(self.classes["Main"].linha, "a classe 'Main' precisa ter um método 'main'")
        elif sig.formais:
            self._erro(sig.linha, "o método 'main' não pode ter parâmetros")

    ## verificacao de tipos

    def _conforma(self, a: str, b: str) -> bool:
        if b == SELF:
            return a == SELF
        if a == SELF:
            a = self.classe_atual
        return b in self._ancestrais(a)

    # menor ancestral comum/lowest upper bound
    def _lub(self, a: str, b: str) -> str:
        if a == b:
            return a
        if a == SELF:
            a = self.classe_atual
        if b == SELF:
            b = self.classe_atual
        anc = set(self._ancestrais(a))
        for x in self._ancestrais(b):
            if x in anc:
                return x
        return "Object"

    # escopos
    def _empilhar(self, nome: str | None = None, tipo: str | None = None):
        self.escopos.append({nome: tipo} if nome is not None else {})

    def _desempilhar(self, n: int = 1):
        for _ in range(n):
            self.escopos.pop()

    def _buscar_var(self, nome: str):
        for escopo in reversed(self.escopos): #busca de dentro pra fora
            if nome in escopo:
                return escopo[nome]
        return None

    def _checar_classe(self, no: Classe):
        info = self.classes[no.nome]
        self.classe_atual = no.nome
        self.escopos = [info.todos_atributos]
        for f in no.features:
            if isinstance(f, Atributo):
                self._checar_atributo(info, f)
            elif isinstance(f, Metodo):
                self._checar_metodo(f)

    def _checar_atributo(self, info: InfoClasse, f: Atributo):
        if f.init is None:
            return
        t = self._tipo_de(f.init)
        declarado = info.atributos.get(f.nome)
        if declarado is not None and not self._conforma(t, declarado):
            self._erro(f.linha, f"inicialização de '{f.nome}': '{t}' não conforma com '{declarado}'")

    def _checar_metodo(self, f: Metodo):
        escopo = {}
        for p in f.formais:
            if p.nome != "self":
                escopo[p.nome] = p.tipo if p.tipo in self.classes else "Object"
        ret = f.tipo if self._tipo_existe(f.tipo) else "Object"
        self.escopos.append(escopo)
        t = self._tipo_de(f.corpo)
        self.escopos.pop()
        if not self._conforma(t, ret):
            self._erro(f.linha, f"corpo do método '{f.nome}' tem tipo '{t}', que não conforma com '{ret}'")

    ## Expressoes: cada _t_X devolve o tipo da expressao
    def _tipo_de(self, no: No) -> str:
        metodo = getattr(self, f"_t_{type(no).__name__}", None)
        t = metodo(no) if metodo else "Object"
        no.tipo = t  # anota a AST
        return t

    def _exigir(self, tipo: str, esperado: str, linha: int, contexto: str):
        if tipo != esperado:
            self._erro(linha, f"{contexto} deve ser {esperado}, mas é '{tipo}'")

    def _t_ConstInt(self, no):
        return "Int"

    def _t_ConstString(self, no):
        return "String"

    def _t_ConstBool(self, no):
        return "Bool"

    def _t_Objeto(self, no: Objeto):
        if no.nome == "self":
            return SELF
        t = self._buscar_var(no.nome)
        if t is None:
            self._erro(no.linha, f"identificador '{no.nome}' não foi declarado")
            return "Object"
        return t

    def _t_Atribuicao(self, no: Atribuicao):
        t = self._tipo_de(no.valor)
        if no.nome == "self":
            self._erro(no.linha, "não é possível atribuir a 'self'")
            return t
        v = self._buscar_var(no.nome)
        if v is None:
            self._erro(no.linha, f"identificador '{no.nome}' não foi declarado")
        elif not self._conforma(t, v):
            self._erro(no.linha, f"atribuição a '{no.nome}': '{t}' não conforma com '{v}'")
        return t

    def _t_Despacho(self, no: Despacho):
        tipo = SELF if no.objeto is None else self._tipo_de(no.objeto)
        args = [self._tipo_de(a) for a in no.argumentos]
        busca = self.classe_atual if tipo == SELF else tipo

        if no.tipo_estatico is not None:
            if no.tipo_estatico == SELF or no.tipo_estatico not in self.classes:
                self._erro(no.linha, f"tipo estático '{no.tipo_estatico}' inválido no despacho")
            elif not self._conforma(tipo, no.tipo_estatico):
                self._erro(no.linha, f"despacho estático: '{tipo}' não conforma com '{no.tipo_estatico}'")
            else:
                busca = no.tipo_estatico

        sig = self._buscar_metodo(busca, no.metodo)
        if sig is None:
            self._erro(no.linha, f"método '{no.metodo}' não existe em '{busca}'")
            return "Object"
        if len(args) != len(sig.formais):
            self._erro(no.linha, f"método '{no.metodo}' espera {len(sig.formais)} argumento(s), recebeu {len(args)}")
        else:
            for i, (ta, (pn, pt)) in enumerate(zip(args, sig.formais), 1):
                if not self._conforma(ta, pt):
                    self._erro(no.linha, f"argumento {i} de '{no.metodo}': '{ta}' não conforma com '{pt}'")
        return tipo if sig.retorno == SELF else sig.retorno

    def _t_Se(self, no: Se):
        self._exigir(self._tipo_de(no.condicao), "Bool", no.linha, "condição do if")
        return self._lub(self._tipo_de(no.entao), self._tipo_de(no.senao))

    def _t_Enquanto(self, no: Enquanto):
        self._exigir(self._tipo_de(no.condicao), "Bool", no.linha, "condição do while")
        self._tipo_de(no.corpo)
        return "Object"

    def _t_Bloco(self, no: Bloco):
        t = "Object"
        for e in no.expressoes:
            t = self._tipo_de(e)
        return t

    def _t_Let(self, no: Let):
        for lig in no.ligacoes:
            # o init e avaliado antes da variavel entrar no escopo
            t_init = self._tipo_de(lig.init) if lig.init is not None else None
            tipo = lig.tipo
            if not self._tipo_existe(tipo):
                self._erro(lig.linha, f"variável '{lig.nome}' tem tipo '{tipo}', que não existe")
                tipo = "Object"
            if t_init is not None and not self._conforma(t_init, tipo):
                self._erro(lig.linha, f"inicialização de '{lig.nome}': '{t_init}' não conforma com '{tipo}'")
            if lig.nome == "self":
                self._erro(lig.linha, "'self' não pode ser variável de let")
                self._empilhar()
            else:
                self._empilhar(lig.nome, tipo)
        t = self._tipo_de(no.corpo)
        self._desempilhar(len(no.ligacoes))
        return t

    def _t_Caso(self, no: Caso):
        self._tipo_de(no.expressao)
        vistos = set()
        resultado = None
        for r in no.ramos:
            tr = r.tipo
            if tr == SELF:
                self._erro(r.linha, "ramo do case não pode ter tipo SELF_TYPE")
                tr = "Object"
            elif tr not in self.classes:
                self._erro(r.linha, f"ramo do case tem tipo '{tr}', que não existe")
                tr = "Object"
            elif tr in vistos:
                self._erro(r.linha, f"tipo '{tr}' repetido em ramos do case")
            vistos.add(tr)
            if r.nome == "self":
                self._erro(r.linha, "'self' não pode ser variável de ramo do case")
                self._empilhar()
            else:
                self._empilhar(r.nome, tr)
            t = self._tipo_de(r.corpo)
            self._desempilhar()
            resultado = t if resultado is None else self._lub(resultado, t)
        return resultado or "Object"

    def _t_Novo(self, no: Novo):
        if no.tipo == SELF:
            return SELF
        if no.tipo not in self.classes:
            self._erro(no.linha, f"'new {no.tipo}': tipo não existe")
            return "Object"
        return no.tipo

    def _t_IsVoid(self, no: IsVoid):
        self._tipo_de(no.expressao)
        return "Bool"

    def _t_OpUn(self, no: OpUn):
        t = self._tipo_de(no.expressao)
        if no.op == "not":
            self._exigir(t, "Bool", no.linha, "operando de 'not'")
            return "Bool"
        self._exigir(t, "Int", no.linha, "operando de '~'")
        return "Int"

    def _t_OpBin(self, no: OpBin):
        te = self._tipo_de(no.esquerda)
        td = self._tipo_de(no.direita)
        if no.op in ("+", "-", "*", "/"):
            self._exigir(te, "Int", no.linha, f"operando esquerdo de '{no.op}'")
            self._exigir(td, "Int", no.linha, f"operando direito de '{no.op}'")
            return "Int"
        if no.op in ("<", "<="):
            self._exigir(te, "Int", no.linha, f"operando esquerdo de '{no.op}'")
            self._exigir(td, "Int", no.linha, f"operando direito de '{no.op}'")
            return "Bool"
        # '=': Int, String e Bool so podem ser comparados com o mesmo tipo
        if (te in BASICOS or td in BASICOS) and te != td:
            self._erro(no.linha, f"comparação '=' entre tipos incompatíveis '{te}' e '{td}'")
        return "Bool"
