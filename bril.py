####################################################################################
# uso:
#   representação de Bril (https://capra.cs.cornell.edu/bril/) e construtor de funções
#
#   f = Funcao("soma", [("a", INT), ("b", INT)], INT)
#   r = f.op("add", INT, ["a", "b"])
#   f.ret(r)
#
#   prog = ProgramaBril([f])
#   prog.json()    # string JSON (entrada do brili / brilirs)
#   prog.texto()   # formato textual (entrada do bril2json)
####################################################################################
import json

INT = "int"
BOOL = "bool"
CHAR = "char"
PTR = {"ptr": "int"}  # extensão de memória: ponteiro para int


def tipo_texto(t) -> str:
    if isinstance(t, dict):
        return f"ptr<{tipo_texto(t['ptr'])}>"
    return t


class Funcao:
    """Construtor de uma função Bril. Cada método de emissão devolve o nome do destino."""

    def __init__(self, nome: str, args: list[tuple[str, object]], tipo=None):
        self.nome = nome
        self.args = args        # [(nome, tipo)]
        self.tipo = tipo        # None = função sem retorno
        self.instrs = []
        self._ntemp = 0
        self._nrot = 0

    # nomes novos
    def temp(self) -> str:
        self._ntemp += 1
        return f"t.{self._ntemp}"

    def rotulo(self, base: str) -> str:
        self._nrot += 1
        return f"{base}.{self._nrot}"

    def _emit(self, d: dict):
        self.instrs.append(d)

    # instruções com valor
    def const(self, tipo, valor, dest=None) -> str:
        dest = dest or self.temp()
        self._emit({"op": "const", "dest": dest, "type": tipo, "value": valor})
        return dest

    def op(self, op: str, tipo, args: list[str], dest=None) -> str:
        dest = dest or self.temp()
        self._emit({"op": op, "dest": dest, "type": tipo, "args": list(args)})
        return dest

    def id(self, tipo, src: str, dest=None) -> str:
        return self.op("id", tipo, [src], dest)

    def call(self, func: str, args: list[str], tipo=None, dest=None):
        d = {"op": "call", "funcs": [func], "args": list(args)}
        if tipo is not None:
            dest = dest or self.temp()
            d["dest"] = dest
            d["type"] = tipo
        self._emit(d)
        return dest if tipo is not None else None

    # memória
    def alloc(self, n: str, dest=None) -> str:
        return self.op("alloc", PTR, [n], dest)

    def load(self, p: str, dest=None) -> str:
        return self.op("load", INT, [p], dest)

    def store(self, p: str, v: str):
        self._emit({"op": "store", "args": [p, v]})

    def ptradd(self, p: str, off: str, dest=None) -> str:
        return self.op("ptradd", PTR, [p, off], dest)

    def free(self, p: str):
        self._emit({"op": "free", "args": [p]})

    # controle
    def label(self, nome: str):
        self._emit({"label": nome})

    def jmp(self, nome: str):
        self._emit({"op": "jmp", "labels": [nome]})

    def br(self, cond: str, verdadeiro: str, falso: str):
        self._emit({"op": "br", "args": [cond], "labels": [verdadeiro, falso]})

    def ret(self, v=None):
        self._emit({"op": "ret", "args": [v] if v is not None else []})

    def print_(self, args: list[str]):
        self._emit({"op": "print", "args": list(args)})

    # saída
    def dict(self) -> dict:
        d = {"name": self.nome}
        if self.args:
            d["args"] = [{"name": n, "type": t} for n, t in self.args]
        if self.tipo is not None:
            d["type"] = self.tipo
        d["instrs"] = self.instrs
        return d

    def texto(self) -> str:
        args = ", ".join(f"{n}: {tipo_texto(t)}" for n, t in self.args)
        cab = f"@{self.nome}"
        if self.args:
            cab += f"({args})"
        if self.tipo is not None:
            cab += f": {tipo_texto(self.tipo)}"
        linhas = [cab + " {"]
        for i in self.instrs:
            linhas.append(_instr_texto(i))
        linhas.append("}")
        return "\n".join(linhas)


def _instr_texto(i: dict) -> str:
    if "label" in i:
        return f".{i['label']}:"
    op = i["op"]
    partes = [op]
    partes += [f"@{f}" for f in i.get("funcs", [])]
    partes += i.get("args", [])
    partes += [f".{l}" for l in i.get("labels", [])]
    if op == "const":
        v = i["value"]
        corpo = f"const {str(v).lower() if isinstance(v, bool) else v}"
    else:
        corpo = " ".join(partes)
    if "dest" in i:
        return f"  {i['dest']}: {tipo_texto(i['type'])} = {corpo};"
    return f"  {corpo};"


class ProgramaBril:
    def __init__(self, funcoes: list[Funcao]):
        self.funcoes = funcoes

    def dict(self) -> dict:
        return {"functions": [f.dict() for f in self.funcoes]}

    def json(self, indent=None) -> str:
        return json.dumps(self.dict(), indent=indent)

    def texto(self) -> str:
        return "\n\n".join(f.texto() for f in self.funcoes) + "\n"
