####################################################################################
# uso:
#   python compilador.py programa.cl                 # imprime Bril textual
#   python compilador.py programa.cl -o saida.bril   # salva em arquivo
#   python compilador.py programa.cl --json -o s.json
#   python compilador.py programa.cl --json | brili  # executa direto
#
# opções: --heap N (palavras), --sem-char, --sem-checagens
####################################################################################
import argparse
import sys

from lexico import Lexico
from sintatico import Sintatico
from semantico import Semantico
from gerador import GeradorBril


def compilar(fonte: str, **opcoes):
    """Roda todas as fases. Devolve (programa_bril, avisos) ou levanta SystemExit(1)."""
    tokens = Lexico(fonte).interpretar()
    parser = Sintatico(tokens)
    ast = parser.analisar()
    if parser.erros:
        for e in parser.erros:
            print(e, file=sys.stderr)
        raise SystemExit(1)

    sem = Semantico(ast)
    erros = sem.analisar()
    if erros:
        for e in erros:
            print(e, file=sys.stderr)
        raise SystemExit(1)

    gen = GeradorBril(ast, sem, **opcoes)
    return gen.gerar(), gen.avisos


def main():
    ap = argparse.ArgumentParser(description="Compilador Cool -> Bril")
    ap.add_argument("arquivo")
    ap.add_argument("-o", "--saida")
    ap.add_argument("--json", action="store_true", help="emite JSON em vez de texto")
    ap.add_argument("--heap", type=int, default=1 << 20, help="tamanho do heap em palavras")
    ap.add_argument("--sem-char", action="store_true", help="out_string imprime códigos em vez de chars")
    ap.add_argument("--sem-checagens", action="store_true", help="omite erros de execução do Cool")
    a = ap.parse_args()

    with open(a.arquivo, encoding="utf-8") as fh:
        fonte = fh.read()

    prog, avisos = compilar(fonte, tamanho_heap=a.heap, usar_char=not a.sem_char,
                            checagens=not a.sem_checagens)
    for av in avisos:
        print(f"aviso: {av}", file=sys.stderr)

    saida = prog.json() if a.json else prog.texto()
    if a.saida:
        with open(a.saida, "w", encoding="utf-8") as fh:
            fh.write(saida)
    else:
        print(saida)


if __name__ == "__main__":
    main()
