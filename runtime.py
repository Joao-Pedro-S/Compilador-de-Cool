####################################################################################
# biblioteca de execução (runtime) escrita em Bril
#
# Bril não tem globais, strings, ponteiros para funções nem exceções, então o
# gerador usa a seguinte representação (todo valor Cool vira int/bool em Bril):
#
#   heap (ptr<int>, passado como 1º argumento de TODA função):
#       heap[0]            próxima posição livre (alocador por incremento)
#       heap[1]            capacidade do heap
#       heap[2 .. 2+N-1]   handles das N literais string (criadas em main)
#       heap[2+N ..]       objetos
#
#   objeto (handle = índice no heap; void = 0):
#       [h+0] tag da classe   [h+1] tamanho em palavras   [h+2 ...] atributos
#   string: [tag String][tamanho][comprimento][c0][c1]...
#   Int e Bool são valores crus (int/bool Bril); só viram objeto ("boxing")
#   quando são usados onde se espera Object.
####################################################################################
from bril import Funcao, INT, BOOL, CHAR, PTR

HDR = 2        # palavras de cabeçalho de um objeto (tag, tamanho)
LIT_BASE = 2   # primeira posição da tabela de literais no heap
DESBOXADOS = ("Int", "Bool")  # tipos cujo valor estático é cru (sem objeto)

# códigos impressos antes de abortar a execução
COD_ABORT = -1
COD_DESPACHO_VOID = -2
COD_CASE_VOID = -3
COD_CASE_SEM_RAMO = -4
COD_SUBSTR = -5
COD_MEMORIA = -6
COD_NEW_SELF = -7


class RuntimeBril:
    """Mixin com as funções de apoio. Usa atributos do GeradorBril."""

    def _tabela_rt(self):
        return {
            "__alloc": self._rt_alloc,
            "__abort": self._rt_abort,
            "__chk_despacho": lambda: self._rt_chk("__chk_despacho", COD_DESPACHO_VOID),
            "__chk_case": lambda: self._rt_chk("__chk_case", COD_CASE_VOID),
            "__str_alloc": self._rt_str_alloc,
            "__str_vazia": self._rt_str_vazia,
            "__str_eq": self._rt_str_eq,
            "__b2i": self._rt_b2i,
            "__box_int": self._rt_box_int,
            "__box_bool": self._rt_box_bool,
            "__unbox_int": self._rt_unbox_int,
            "__unbox_bool": self._rt_unbox_bool,
            "__new_self": self._rt_new_self,
            "Object.abort": self._rt_object_abort,
            "Object.type_name": self._rt_type_name,
            "Object.copy": self._rt_copy,
            "IO.out_string": self._rt_out_string,
            "IO.out_int": self._rt_out_int,
            "IO.in_string": self._rt_in_string,
            "IO.in_int": self._rt_in_int,
            "String.length": self._rt_length,
            "String.concat": self._rt_concat,
            "String.substr": self._rt_substr,
        }

    # chama uma função do runtime registrando que ela precisa ser emitida
    def _cr(self, f: Funcao, nome: str, args: list[str], tipo=None):
        self._rt(nome)
        return f.call(nome, args, tipo)

    ## ---- auxiliares de emissão

    def _hdr_store(self, f: Funcao, p: str, tag: int, tamanho: str):
        f.store(p, f.const(INT, tag))
        f.store(f.ptradd(p, f.const(INT, 1)), tamanho)

    # copia n palavras de origem[ini_o + i] para destino[ini_d + i]
    def _loop_copia(self, f: Funcao, origem, ini_o, destino, ini_d, n):
        um = f.const(INT, 1)
        i = f.const(INT, 0)
        cond, corpo, fim = f.rotulo("copia.cond"), f.rotulo("copia.corpo"), f.rotulo("copia.fim")
        f.label(cond)
        f.br(f.op("lt", BOOL, [i, n]), corpo, fim)
        f.label(corpo)
        so = f.op("add", INT, [ini_o, i])
        v = f.load(f.ptradd(origem, so))
        do = f.op("add", INT, [ini_d, i])
        f.store(f.ptradd(destino, do), v)
        f.op("add", INT, [i, um], dest=i)
        f.jmp(cond)
        f.label(fim)

    ## ---- memória e erros

    def _rt_alloc(self):
        f = Funcao("__alloc", [("heap", PTR), ("n", INT)], INT)
        um = f.const(INT, 1)
        cur = f.load("heap")
        novo = f.op("add", INT, [cur, "n"])
        cap = f.load(f.ptradd("heap", um))
        f.br(f.op("le", BOOL, [novo, cap]), "ok", "oom")
        f.label("oom")
        self._cr(f, "__abort", [f.const(INT, COD_MEMORIA)])
        f.ret(cur)
        f.label("ok")
        f.store("heap", novo)
        f.ret(cur)
        return f

    # Bril não tem "exit": imprime um código e provoca um erro de execução
    # (divisão por zero), que é o jeito de interromper o programa.
    def _rt_abort(self):
        f = Funcao("__abort", [("code", INT)])
        f.print_(["code"])
        f.op("div", INT, [f.const(INT, 1), f.const(INT, 0)])
        f.ret()
        return f

    def _rt_chk(self, nome: str, codigo: int):
        f = Funcao(nome, [("obj", INT)])
        f.br(f.op("eq", BOOL, ["obj", f.const(INT, 0)]), "falha", "ok")
        f.label("falha")
        self._cr(f, "__abort", [f.const(INT, codigo)])
        f.label("ok")
        f.ret()
        return f

    ## ---- boxing

    def _rt_b2i(self):
        f = Funcao("__b2i", [("b", BOOL)], INT)
        f.br("b", "v", "f")
        f.label("v")
        f.ret(f.const(INT, 1))
        f.label("f")
        f.ret(f.const(INT, 0))
        return f

    def _rt_box(self, nome, tipo_arg, classe, conv):
        f = Funcao(nome, [("heap", PTR), ("v", tipo_arg)], INT)
        tres = f.const(INT, 3)
        h = self._cr(f, "__alloc", ["heap", tres], INT)
        p = f.ptradd("heap", h)
        self._hdr_store(f, p, self.tag[classe], tres)
        val = self._cr(f, "__b2i", ["v"], INT) if conv else "v"
        f.store(f.ptradd(p, f.const(INT, 2)), val)
        f.ret(h)
        return f

    def _rt_box_int(self):
        return self._rt_box("__box_int", INT, "Int", False)

    def _rt_box_bool(self):
        return self._rt_box("__box_bool", BOOL, "Bool", True)

    def _rt_unbox_int(self):
        f = Funcao("__unbox_int", [("heap", PTR), ("h", INT)], INT)
        p = f.ptradd("heap", "h")
        f.ret(f.load(f.ptradd(p, f.const(INT, 2))))
        return f

    def _rt_unbox_bool(self):
        f = Funcao("__unbox_bool", [("heap", PTR), ("h", INT)], BOOL)
        p = f.ptradd("heap", "h")
        v = f.load(f.ptradd(p, f.const(INT, 2)))
        f.ret(f.op("eq", BOOL, [v, f.const(INT, 1)]))
        return f

    ## ---- strings: [tag][tamanho][comprimento][chars...]

    def _rt_str_alloc(self):
        f = Funcao("__str_alloc", [("heap", PTR), ("len", INT)], INT)
        tres = f.const(INT, 3)
        n = f.op("add", INT, ["len", tres])
        h = self._cr(f, "__alloc", ["heap", n], INT)
        p = f.ptradd("heap", h)
        self._hdr_store(f, p, self.tag["String"], n)
        f.store(f.ptradd(p, f.const(INT, 2)), "len")
        f.ret(h)
        return f

    def _rt_str_vazia(self):
        f = Funcao("__str_vazia", [("heap", PTR)], INT)
        h = self._cr(f, "__str_alloc", ["heap", f.const(INT, 0)], INT)
        f.ret(h)
        return f

    def _rt_str_eq(self):
        f = Funcao("__str_eq", [("heap", PTR), ("a", INT), ("b", INT)], BOOL)
        dois, tres, um = f.const(INT, 2), f.const(INT, 3), f.const(INT, 1)
        pa, pb = f.ptradd("heap", "a"), f.ptradd("heap", "b")
        la = f.load(f.ptradd(pa, dois))
        lb = f.load(f.ptradd(pb, dois))
        f.br(f.op("eq", BOOL, [la, lb]), "cmp", "diff")
        f.label("cmp")
        i = f.const(INT, 0)
        f.label("cond")
        f.br(f.op("lt", BOOL, [i, la]), "corpo", "igual")
        f.label("corpo")
        off = f.op("add", INT, [i, tres])
        x = f.load(f.ptradd(pa, off))
        y = f.load(f.ptradd(pb, off))
        f.br(f.op("eq", BOOL, [x, y]), "prox", "diff")
        f.label("prox")
        f.op("add", INT, [i, um], dest=i)
        f.jmp("cond")
        f.label("igual")
        f.ret(f.const(BOOL, True))
        f.label("diff")
        f.ret(f.const(BOOL, False))
        return f

    def _rt_length(self):
        f = Funcao("String.length", [("heap", PTR), ("self", INT)], INT)
        p = f.ptradd("heap", "self")
        f.ret(f.load(f.ptradd(p, f.const(INT, 2))))
        return f

    def _rt_concat(self):
        f = Funcao("String.concat", [("heap", PTR), ("self", INT), ("s", INT)], INT)
        dois, tres = f.const(INT, 2), f.const(INT, 3)
        pa, pb = f.ptradd("heap", "self"), f.ptradd("heap", "s")
        la = f.load(f.ptradd(pa, dois))
        lb = f.load(f.ptradd(pb, dois))
        total = f.op("add", INT, [la, lb])
        h = self._cr(f, "__str_alloc", ["heap", total], INT)
        ph = f.ptradd("heap", h)
        self._loop_copia(f, pa, tres, ph, tres, la)
        ini = f.op("add", INT, [la, tres])
        self._loop_copia(f, pb, tres, ph, ini, lb)
        f.ret(h)
        return f

    def _rt_substr(self):
        f = Funcao("String.substr", [("heap", PTR), ("self", INT), ("i", INT), ("l", INT)], INT)
        dois, tres, zero = f.const(INT, 2), f.const(INT, 3), f.const(INT, 0)
        pa = f.ptradd("heap", "self")
        tam = f.load(f.ptradd(pa, dois))
        ruim = f.op("or", BOOL, [f.op("lt", BOOL, ["i", zero]), f.op("lt", BOOL, ["l", zero])])
        fim = f.op("add", INT, ["i", "l"])
        ruim = f.op("or", BOOL, [ruim, f.op("gt", BOOL, [fim, tam])])
        f.br(ruim, "falha", "ok")
        f.label("falha")
        self._cr(f, "__abort", [f.const(INT, COD_SUBSTR)])
        f.ret("self")
        f.label("ok")
        h = self._cr(f, "__str_alloc", ["heap", "l"], INT)
        ph = f.ptradd("heap", h)
        ini = f.op("add", INT, ["i", tres])
        self._loop_copia(f, pa, ini, ph, tres, "l")
        f.ret(h)
        return f

    ## ---- Object

    def _rt_object_abort(self):
        f = Funcao("Object.abort", [("heap", PTR), ("self", INT)], INT)
        self._cr(f, "__abort", [f.const(INT, COD_ABORT)])
        f.ret("self")
        return f

    def _rt_type_name(self):
        f = Funcao("Object.type_name", [("heap", PTR), ("self", INT)], INT)
        tag = f.load(f.ptradd("heap", "self"))
        for nome, t in self.tag.items():
            sim, nao = f.rotulo("tn.sim"), f.rotulo("tn.nao")
            f.br(f.op("eq", BOOL, [tag, f.const(INT, t)]), sim, nao)
            f.label(sim)
            f.ret(self._carregar_lit(f, nome))
            f.label(nao)
        f.ret(self._carregar_lit(f, "Object"))
        return f

    def _rt_copy(self):
        f = Funcao("Object.copy", [("heap", PTR), ("self", INT)], INT)
        p = f.ptradd("heap", "self")
        tam = f.load(f.ptradd(p, f.const(INT, 1)))
        n = self._cr(f, "__alloc", ["heap", tam], INT)
        q = f.ptradd("heap", n)
        zero = f.const(INT, 0)
        self._loop_copia(f, p, zero, q, zero, tam)
        f.ret(n)
        return f

    # new SELF_TYPE: escolhe o construtor pela tag do objeto self
    def _rt_new_self(self):
        f = Funcao("__new_self", [("heap", PTR), ("self", INT)], INT)
        tag = f.load(f.ptradd("heap", "self"))
        for nome, t in self.tag.items():
            if nome in DESBOXADOS or nome == "String":
                continue
            sim, nao = f.rotulo("ns.sim"), f.rotulo("ns.nao")
            f.br(f.op("eq", BOOL, [tag, f.const(INT, t)]), sim, nao)
            f.label(sim)
            f.ret(f.call(self._req_new(nome), ["heap"], INT))
            f.label(nao)
        self._cr(f, "__abort", [f.const(INT, COD_NEW_SELF)])
        f.ret(f.const(INT, 0))
        return f

    ## ---- IO

    # LIMITAÇÃO: `print` do Bril sempre termina a linha, então não existe como
    # escrever texto sem quebra de linha. Cada caractere sai em uma linha própria.
    def _rt_out_string(self):
        f = Funcao("IO.out_string", [("heap", PTR), ("self", INT), ("x", INT)], INT)
        um, tres = f.const(INT, 1), f.const(INT, 3)
        p = f.ptradd("heap", "x")
        tam = f.load(f.ptradd(p, f.const(INT, 2)))
        i = f.const(INT, 0)
        f.label("cond")
        f.br(f.op("lt", BOOL, [i, tam]), "corpo", "fim")
        f.label("corpo")
        ch = f.load(f.ptradd(p, f.op("add", INT, [i, tres])))
        if self.usar_char:
            ch = f.op("int2char", CHAR, [ch])
        f.print_([ch])
        f.op("add", INT, [i, um], dest=i)
        f.jmp("cond")
        f.label("fim")
        f.ret("self")
        return f

    def _rt_out_int(self):
        f = Funcao("IO.out_int", [("heap", PTR), ("self", INT), ("x", INT)], INT)
        f.print_(["x"])
        f.ret("self")
        return f

    # Bril não tem entrada padrão (só argumentos de main): stubs
    def _rt_in_int(self):
        self.avisos.append("IO.in_int: Bril não tem entrada de dados; sempre retorna 0")
        f = Funcao("IO.in_int", [("heap", PTR), ("self", INT)], INT)
        f.ret(f.const(INT, 0))
        return f

    def _rt_in_string(self):
        self.avisos.append("IO.in_string: Bril não tem entrada de dados; sempre retorna \"\"")
        f = Funcao("IO.in_string", [("heap", PTR), ("self", INT)], INT)
        f.ret(self._cr(f, "__str_vazia", ["heap"], INT))
        return f
