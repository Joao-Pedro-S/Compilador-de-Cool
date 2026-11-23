####################################################################################
# uso:
#   gerador de código intermediário: AST anotada do Cool -> Bril
#   (a análise semântica precisa ter rodado antes e sem erros, pois ela anota
#   cada expressão da AST com seu tipo estático em `no.tipo`)
#
#   sem = Semantico(ast)
#   if not sem.analisar():
#       gen = GeradorBril(ast, sem)
#       prog = gen.gerar()          # ProgramaBril
#       print(prog.texto())         # formato textual (bril2json lê isso)
#       print(prog.json())          # JSON (brili / brilirs leem isso)
#       for a in gen.avisos: ...    # limitações encontradas (ex.: IO.in_int)
#
# opções:
#   tamanho_heap  palavras do heap (todos os objetos vivem nele; não há GC)
#   usar_char     out_string usa a extensão `char` (senão imprime códigos)
#   checagens     insere os erros de execução do Cool (despacho em void etc.)
#
# convenções (veja runtime.py para o layout do heap):
#   função de método:  @Classe.metodo(heap: ptr<int>, self: int, args...)
#   Int -> int, Bool -> bool, qualquer outro tipo -> int (handle no heap)
#   variável Cool x -> v.x (v.x.1, v.x.2... se houver sombreamento); temporários t.N
####################################################################################
from dataclasses import fields

from sintatico import Atributo, Atribuicao, Metodo, No, Objeto
from semantico import SELF
from bril import Funcao, ProgramaBril, INT, BOOL, PTR
from runtime import (
    RuntimeBril, HDR, LIT_BASE, DESBOXADOS, COD_CASE_SEM_RAMO,
)

ARITMETICA = {"+": "add", "-": "sub", "*": "mul", "/": "div"}


class ErroGeracao(Exception):
    pass


class GeradorBril(RuntimeBril):
    def __init__(self, ast, semantico, tamanho_heap: int = 1 << 20,
                 usar_char: bool = True, checagens: bool = True):
        if semantico.erros:
            raise ErroGeracao("a análise semântica encontrou erros; não é possível gerar código")
        self.ast = ast
        self.sem = semantico
        self.classes = semantico.classes
        self.nos = semantico.nos
        self.tamanho_heap = tamanho_heap
        self.usar_char = usar_char
        self.checagens = checagens
        self.avisos = []

        self.literais = {}       # texto -> índice na tabela de literais
        self.pedidos = {}        # função auxiliar pedida: nome -> gerador
        self.feitos = {}         # nome -> Funcao já gerada
        self.funcoes_usuario = []
        self.RT = self._tabela_rt()
        self._init_cache = {}

        # estado da função em geração
        self.fb = None
        self.escopos = []
        self.contagem = {}
        self.classe_atual = None

        self._preparar_classes()

    ## ---------------------------------------------------------------- classes

    # tags em pré-ordem: C é ancestral de X  <=>  tag[C] <= tag[X] <= tag_max[C]
    def _preparar_classes(self):
        filhos = {n: [] for n in self.classes}
        for n, info in self.classes.items():
            if info.pai is not None:
                filhos[info.pai].append(n)
        self.tag, self.tag_max, self.profundidade = {}, {}, {}

        def dfs(n, d):
            self.tag[n] = len(self.tag)
            self.profundidade[n] = d
            for f in filhos[n]:
                dfs(f, d + 1)
            self.tag_max[n] = len(self.tag) - 1

        dfs("Object", 0)

    def _subarvore(self, classe: str):
        lo, hi = self.tag[classe], self.tag_max[classe]
        return [c for c in self.classes if lo <= self.tag[c] <= hi]

    def _instancia_de(self, f: Funcao, tag: str, classe: str) -> str:
        lo, hi = self.tag[classe], self.tag_max[classe]
        if lo == hi:
            return f.op("eq", BOOL, [tag, f.const(INT, lo)])
        a = f.op("ge", BOOL, [tag, f.const(INT, lo)])
        b = f.op("le", BOOL, [tag, f.const(INT, hi)])
        return f.op("and", BOOL, [a, b])

    def _precisa_init(self, classe: str) -> bool:
        info = self.classes[classe]
        if info.basica:
            return False
        if classe not in self._init_cache:
            proprio = any(isinstance(ft, Atributo) and ft.init is not None
                          for ft in self.nos[classe].features)
            self._init_cache[classe] = proprio or self._precisa_init(info.pai)
        return self._init_cache[classe]

    ## ------------------------------------------------- funções sob demanda

    def _pedir(self, nome: str, gerador):
        if nome not in self.pedidos:
            self.pedidos[nome] = gerador

    def _rt(self, nome: str) -> str:
        self._pedir(nome, self.RT[nome])
        return nome

    def _req_new(self, classe: str) -> str:
        nome = f"{classe}.__new"
        self._pedir(nome, lambda: self._gerar_new(classe))
        return nome

    def _req_init(self, classe: str) -> str:
        nome = f"{classe}.__init"
        self._pedir(nome, lambda: self._gerar_init(classe))
        return nome

    # nome da função que implementa o método (basicas vêm do runtime)
    def _funcao_impl(self, classe: str, metodo: str) -> str:
        nome = f"{classe}.{metodo}"
        if self.classes[classe].basica:
            self._rt(nome)
        return nome

    def _processar_pedidos(self):
        while True:
            pendentes = [n for n in self.pedidos if n not in self.feitos]
            if not pendentes:
                return
            for n in pendentes:
                estado = (self.fb, self.escopos, self.contagem, self.classe_atual)
                self.feitos[n] = self.pedidos[n]()
                self.fb, self.escopos, self.contagem, self.classe_atual = estado

    ## ------------------------------------------------------------ principal

    def gerar(self) -> ProgramaBril:
        for no in self.nos.values():
            for ft in no.features:
                if isinstance(ft, Metodo):
                    self.funcoes_usuario.append(self._gerar_metodo(no.nome, ft))
        # dependências de main antes de fechar a tabela de literais
        self._req_new("Main")
        self._rt("__alloc")
        self._rt("__str_alloc")
        self._processar_pedidos()
        n_lit = len(self.literais)
        main = self._gerar_main()
        self._processar_pedidos()
        if len(self.literais) != n_lit:
            raise ErroGeracao("erro interno: literal criada depois de fechar a tabela")
        funcs = [main] + self.funcoes_usuario + list(self.feitos.values())
        return ProgramaBril(funcs)

    # @main: cria o heap, as literais, o objeto Main e chama Main.main
    def _gerar_main(self) -> Funcao:
        f = Funcao("main", [])
        n_lit = len(self.literais)
        inicio = LIT_BASE + n_lit
        if inicio >= self.tamanho_heap:
            raise ErroGeracao("tamanho_heap pequeno demais para as literais do programa")
        f.alloc(f.const(INT, self.tamanho_heap), dest="heap")
        f.store("heap", f.const(INT, inicio))                       # heap[0]
        f.store(f.ptradd("heap", f.const(INT, 1)), f.const(INT, self.tamanho_heap))  # heap[1]
        for texto, idx in self.literais.items():
            h = f.call("__str_alloc", ["heap", f.const(INT, len(texto))], INT)
            base = f.ptradd("heap", h)
            for i, ch in enumerate(texto):
                q = f.ptradd(base, f.const(INT, 3 + i))
                f.store(q, f.const(INT, ord(ch)))
            f.store(f.ptradd("heap", f.const(INT, LIT_BASE + idx)), h)
        obj = f.call("Main.__new", ["heap"], INT)
        sig = self.sem._buscar_metodo("Main", "main")
        f.call(self._funcao_impl(sig.classe, "main"), ["heap", obj], self._bril(sig.retorno))
        f.free("heap")
        f.ret()
        return f

    ## ---------------------------------------------------- tipos e coerções

    @staticmethod
    def _bril(tipo: str):
        return BOOL if tipo == "Bool" else INT

    def _boxear(self, v: str, t: str) -> str:
        nome = "__box_int" if t == "Int" else "__box_bool"
        return self._cr(self.fb, nome, ["heap", v], INT)

    def _desboxear(self, v: str, t: str) -> str:
        nome = "__unbox_int" if t == "Int" else "__unbox_bool"
        return self._cr(self.fb, nome, ["heap", v], self._bril(t))

    # converte o valor `v` (tipo estático `de`) para a representação de `para`
    # Int/Bool só mudam de representação ao entrar/sair de um tipo-objeto
    def _coagir(self, v: str, de: str, para: str) -> str:
        if de in DESBOXADOS and para not in DESBOXADOS:
            return self._boxear(v, de)
        if para in DESBOXADOS and de not in DESBOXADOS:
            return self._desboxear(v, para)
        return v

    # valor inicial (representação normal) de uma variável sem init
    def _valor_padrao(self, tipo: str) -> str:
        f = self.fb
        if tipo == "Bool":
            return f.const(BOOL, False)
        if tipo == "String":
            return self._cr(f, "__str_vazia", ["heap"], INT)
        return f.const(INT, 0)

    ## ---------------------------------------------------- escopo e variáveis

    def _iniciar_funcao(self, f: Funcao, classe: str, tem_self: bool = True):
        self.fb = f
        self.classe_atual = classe
        self.contagem = {}
        atributos = self.classes[classe].todos_atributos
        self.escopos = [{n: ("attr", HDR + i, t) for i, (n, t) in enumerate(atributos.items())}]
        if tem_self and atributos:
            f.ptradd("heap", "self", dest="selfp")   # base dos atributos do objeto

    def _nova_var(self, nome: str) -> str:
        n = self.contagem.get(nome, 0)
        self.contagem[nome] = n + 1
        return f"v.{nome}" if n == 0 else f"v.{nome}.{n}"

    def _buscar(self, nome: str):
        for escopo in reversed(self.escopos):
            if nome in escopo:
                return escopo[nome]
        return None

    def _ler_attr(self, off: int, tipo: str) -> str:
        f = self.fb
        v = f.load(f.ptradd("selfp", f.const(INT, off)))
        if tipo == "Bool":
            v = f.op("eq", BOOL, [v, f.const(INT, 1)])
        return v

    def _guardar_attr(self, off: int, tipo: str, v: str):
        f = self.fb
        if tipo == "Bool":
            v = self._cr(f, "__b2i", [v], INT)
        f.store(f.ptradd("selfp", f.const(INT, off)), v)

    ## ------------------------------------------------- métodos e construtores

    def _gerar_metodo(self, classe: str, no: Metodo) -> Funcao:
        sig = self.classes[classe].metodos[no.nome]
        args = [("heap", PTR), ("self", INT)]
        args += [(f"v.{n}", self._bril(t)) for n, t in sig.formais]
        f = Funcao(f"{classe}.{no.nome}", args, self._bril(sig.retorno))
        self._iniciar_funcao(f, classe)
        formais = {}
        for n, t in sig.formais:
            self.contagem[n] = 1
            formais[n] = ("var", f"v.{n}", t)
        self.escopos.append(formais)
        v = self._gerar(no.corpo)
        f.ret(self._coagir(v, no.corpo.tipo, sig.retorno))
        return f

    # C.__new: aloca, grava cabeçalho, atributos com valor padrão e roda os init
    def _gerar_new(self, classe: str) -> Funcao:
        f = Funcao(f"{classe}.__new", [("heap", PTR)], INT)
        self.fb = f
        atributos = list(self.classes[classe].todos_atributos.items())
        n = f.const(INT, HDR + len(atributos))
        h = self._cr(f, "__alloc", ["heap", n], INT)
        p = f.ptradd("heap", h)
        self._hdr_store(f, p, self.tag[classe], n)
        for i, (_, t) in enumerate(atributos):
            if t == "String":
                v = self._cr(f, "__str_vazia", ["heap"], INT)
            else:
                v = f.const(INT, 0)   # Int 0, Bool false e void são todos 0
            f.store(f.ptradd(p, f.const(INT, HDR + i)), v)
        if self._precisa_init(classe):
            f.call(self._req_init(classe), ["heap", h])
        f.ret(h)
        return f

    # C.__init: inicializadores dos atributos, na ordem do texto (pai primeiro)
    def _gerar_init(self, classe: str) -> Funcao:
        info = self.classes[classe]
        f = Funcao(f"{classe}.__init", [("heap", PTR), ("self", INT)])
        self._iniciar_funcao(f, classe)
        if self._precisa_init(info.pai):
            f.call(self._req_init(info.pai), ["heap", "self"])
        indices = list(info.todos_atributos)
        for ft in self.nos[classe].features:
            if isinstance(ft, Atributo) and ft.init is not None:
                v = self._gerar(ft.init)
                v = self._coagir(v, ft.init.tipo, ft.tipo)
                self._guardar_attr(HDR + indices.index(ft.nome), ft.tipo, v)
        f.ret()
        return f

    ## ------------------------------------------------------------ literais

    def _lit(self, texto: str) -> int:
        if texto not in self.literais:
            self.literais[texto] = len(self.literais)
        return self.literais[texto]

    def _carregar_lit(self, f: Funcao, texto: str) -> str:
        idx = self._lit(texto)
        return f.load(f.ptradd("heap", f.const(INT, LIT_BASE + idx)))

    ## ---------------------------------------------------------- expressões
    # cada _g_X devolve o nome da variável Bril com o valor, na representação
    # do tipo estático `no.tipo` (anotado pela análise semântica)

    def _gerar(self, no: No) -> str:
        return getattr(self, f"_g_{type(no).__name__}")(no)

    def _tem_atrib(self, no) -> bool:
        if isinstance(no, Atribuicao):
            return True
        if isinstance(no, No):
            return any(self._tem_atrib(getattr(no, c.name)) for c in fields(no) if c.name != "linha")
        if isinstance(no, list):
            return any(self._tem_atrib(x) for x in no)
        return False

    # gera operandos em ordem. Variáveis locais são "congeladas" (id) quando um
    # operando posterior pode atribuí-las: (x + (x <- 5)) usa o x antigo à esquerda
    def _gerar_seq(self, nos: list) -> list:
        vals = []
        for i, n in enumerate(nos):
            v = self._gerar(n)
            if v.startswith("v.") and any(self._tem_atrib(m) for m in nos[i + 1:]):
                v = self.fb.id(self._bril(n.tipo), v)
            vals.append(v)
        return vals

    def _g_ConstInt(self, no):
        return self.fb.const(INT, int(no.valor))

    def _g_ConstBool(self, no):
        return self.fb.const(BOOL, bool(no.valor))

    def _g_ConstString(self, no):
        return self._carregar_lit(self.fb, no.valor)

    def _g_Objeto(self, no):
        if no.nome == "self":
            return "self"
        ent = self._buscar(no.nome)
        if ent[0] == "var":
            return ent[1]
        return self._ler_attr(ent[1], ent[2])

    def _g_Atribuicao(self, no):
        v = self._gerar(no.valor)
        ent = self._buscar(no.nome)
        c = self._coagir(v, no.valor.tipo, ent[2])
        if ent[0] == "var":
            self.fb.id(self._bril(ent[2]), c, dest=ent[1])
        else:
            self._guardar_attr(ent[1], ent[2], c)
        return v

    def _g_Se(self, no):
        f = self.fb
        cond = self._gerar(no.condicao)
        r = f.temp()
        l_entao, l_senao, l_fim = f.rotulo("if.entao"), f.rotulo("if.senao"), f.rotulo("if.fim")
        f.br(cond, l_entao, l_senao)
        for rotulo, ramo in ((l_entao, no.entao), (l_senao, no.senao)):
            f.label(rotulo)
            v = self._coagir(self._gerar(ramo), ramo.tipo, no.tipo)
            f.id(self._bril(no.tipo), v, dest=r)
            f.jmp(l_fim)
        f.label(l_fim)
        return r

    def _g_Enquanto(self, no):
        f = self.fb
        l_cond, l_corpo, l_fim = f.rotulo("while.cond"), f.rotulo("while.corpo"), f.rotulo("while.fim")
        f.label(l_cond)
        f.br(self._gerar(no.condicao), l_corpo, l_fim)
        f.label(l_corpo)
        self._gerar(no.corpo)
        f.jmp(l_cond)
        f.label(l_fim)
        return f.const(INT, 0)   # o while devolve void

    def _g_Bloco(self, no):
        v = None
        for e in no.expressoes:
            v = self._gerar(e)
        return v

    def _g_Let(self, no):
        for lig in no.ligacoes:
            if lig.init is not None:
                v = self._coagir(self._gerar(lig.init), lig.init.tipo, lig.tipo)
            else:
                v = self._valor_padrao(lig.tipo)
            nome = self._nova_var(lig.nome)
            self.fb.id(self._bril(lig.tipo), v, dest=nome)
            self.escopos.append({lig.nome: ("var", nome, lig.tipo)})
        v = self._gerar(no.corpo)
        del self.escopos[len(self.escopos) - len(no.ligacoes):]
        return v

    # o ramo escolhido é o do tipo mais específico que conforma com a tag
    # em tempo de execução: testa do mais profundo para o mais raso
    def _g_Caso(self, no):
        f = self.fb
        v = self._coagir(self._gerar(no.expressao), no.expressao.tipo, "Object")
        if self.checagens:
            self._cr(f, "__chk_case", [v])
        tag = f.load(f.ptradd("heap", v))
        r = f.temp()
        l_fim = f.rotulo("case.fim")
        for rm in sorted(no.ramos, key=lambda x: -self.profundidade[x.tipo]):
            l_ramo, l_prox = f.rotulo("case.ramo"), f.rotulo("case.prox")
            f.br(self._instancia_de(f, tag, rm.tipo), l_ramo, l_prox)
            f.label(l_ramo)
            val = self._desboxear(v, rm.tipo) if rm.tipo in DESBOXADOS else v
            nome = self._nova_var(rm.nome)
            f.id(self._bril(rm.tipo), val, dest=nome)
            self.escopos.append({rm.nome: ("var", nome, rm.tipo)})
            b = self._coagir(self._gerar(rm.corpo), rm.corpo.tipo, no.tipo)
            self.escopos.pop()
            f.id(self._bril(no.tipo), b, dest=r)
            f.jmp(l_fim)
            f.label(l_prox)
        self._cr(f, "__abort", [f.const(INT, COD_CASE_SEM_RAMO)])
        f.label(l_fim)
        return r

    def _g_Novo(self, no):
        f = self.fb
        t = no.tipo
        if t == SELF:
            return self._cr(f, "__new_self", ["heap", "self"], INT)
        if t == "Int":
            return f.const(INT, 0)
        if t == "Bool":
            return f.const(BOOL, False)
        if t == "String":
            return self._cr(f, "__str_vazia", ["heap"], INT)
        return f.call(self._req_new(t), ["heap"], INT)

    def _g_IsVoid(self, no):
        f = self.fb
        v = self._gerar(no.expressao)
        if no.expressao.tipo in ("Int", "Bool", "String"):
            return f.const(BOOL, False)
        return f.op("eq", BOOL, [v, f.const(INT, 0)])

    def _g_OpUn(self, no):
        f = self.fb
        v = self._gerar(no.expressao)
        if no.op == "not":
            return f.op("not", BOOL, [v])
        return f.op("sub", INT, [f.const(INT, 0), v])

    def _g_OpBin(self, no):
        f = self.fb
        a, b = self._gerar_seq([no.esquerda, no.direita])
        if no.op in ARITMETICA:
            return f.op(ARITMETICA[no.op], INT, [a, b])
        if no.op == "<":
            return f.op("lt", BOOL, [a, b])
        if no.op == "<=":
            return f.op("le", BOOL, [a, b])
        te, td = no.esquerda.tipo, no.direita.tipo
        if te == "Bool" and td == "Bool":      # Bril só tem eq para int
            x = f.op("and", BOOL, [a, b])
            y = f.op("and", BOOL, [f.op("not", BOOL, [a]), f.op("not", BOOL, [b])])
            return f.op("or", BOOL, [x, y])
        if te == "String" and td == "String":
            return self._cr(f, "__str_eq", ["heap", a, b], BOOL)
        return f.op("eq", BOOL, [a, b])         # Int com Int, ou igualdade de ponteiros

    ## ------------------------------------------------------------ despacho

    # despacho dinâmico: Bril não tem ponteiro de função, então escolhemos a
    # implementação pela tag. Sem sobrescritas na subárvore vira chamada direta.
    def _funcao_despacho(self, tipo: str, metodo: str) -> str:
        impl = self.sem._buscar_metodo(tipo, metodo).classe
        sobrescritas = [c for c in self._subarvore(tipo)
                        if c != tipo and metodo in self.classes[c].metodos]
        if not sobrescritas:
            return self._funcao_impl(impl, metodo)
        nome = f"__despacho.{tipo}.{metodo}"
        self._pedir(nome, lambda: self._gerar_despachante(nome, tipo, metodo, impl, sobrescritas))
        return nome

    def _gerar_despachante(self, nome, tipo, metodo, impl, sobrescritas) -> Funcao:
        sig = self.sem._buscar_metodo(tipo, metodo)
        args = [("heap", PTR), ("self", INT)]
        args += [(f"a{i}", self._bril(t)) for i, (_, t) in enumerate(sig.formais)]
        nomes = [n for n, _ in args]
        tipo_ret = self._bril(sig.retorno)
        f = Funcao(nome, args, tipo_ret)
        tag = f.load(f.ptradd("heap", "self"))
        for c in sorted(sobrescritas, key=lambda x: -self.profundidade[x]):
            l_sim, l_nao = f.rotulo("ov"), f.rotulo("prox")
            f.br(self._instancia_de(f, tag, c), l_sim, l_nao)
            f.label(l_sim)
            f.ret(f.call(self._funcao_impl(c, metodo), nomes, tipo_ret))
            f.label(l_nao)
        f.ret(f.call(self._funcao_impl(impl, metodo), nomes, tipo_ret))
        return f

    # Segue o manual do Cool: argumentos da esquerda para a direita e só depois o receptor.
    def _g_Despacho(self, no):
        f = self.fb
        t_rec = SELF if no.objeto is None else no.objeto.tipo
        busca = self.classe_atual if t_rec == SELF else t_rec
        if no.tipo_estatico is not None:
            busca = no.tipo_estatico
        sig = self.sem._buscar_metodo(busca, no.metodo)

        ordem = list(no.argumentos) + ([no.objeto] if no.objeto is not None else [])
        vals = self._gerar_seq(ordem)
        args = [self._coagir(v, a.tipo, pt)
                for v, a, (_, pt) in zip(vals, no.argumentos, sig.formais)]

        if no.objeto is None:
            rec = "self"
        else:
            rec = vals[-1]
            if t_rec in DESBOXADOS:             # 5.copy(), true.type_name()
                rec = self._boxear(rec, t_rec)
            elif self.checagens and not (isinstance(no.objeto, Objeto) and no.objeto.nome == "self"):
                self._cr(f, "__chk_despacho", [rec])

        if no.tipo_estatico is not None:
            func = self._funcao_impl(sig.classe, no.metodo)
        else:
            func = self._funcao_despacho(busca, no.metodo)
        r = f.call(func, ["heap", rec] + args, self._bril(sig.retorno))
        de = "Object" if sig.retorno == SELF else sig.retorno
        return self._coagir(r, de, no.tipo)
