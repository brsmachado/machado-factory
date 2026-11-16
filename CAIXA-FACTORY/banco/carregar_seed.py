#!/usr/bin/env python3
"""Gera o SQL de carga inicial a partir do seed JSON (docs/07-migracao.md, seções 2 e 4).

    python3 carregar_seed.py | psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1

Ou com outro arquivo:

    python3 carregar_seed.py ../docs/seed/estado-AAAA-MM-DD.json | psql ...

A carga é uma transação só. Ela se recusa a rodar num banco que já tenha
operações ou movimentos, e termina conferindo v_caixa contra o bloco
"conferencia" do JSON: um centavo de diferença desfaz tudo.
Só usa a biblioteca padrão.
"""
import json
import pathlib
import sys
from decimal import Decimal

BASE = pathlib.Path(__file__).resolve().parent
PADRAO = BASE.parent / "docs" / "seed" / "estado-2026-10-19.json"


def lit(v):
    """Literal SQL seguro para str / número / None."""
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert(tabela, linhas, colunas):
    if not linhas:
        return ""
    vals = ",\n  ".join(
        "(" + ", ".join(lit(l.get(c)) for c in colunas) + ")" for l in linhas
    )
    return f"insert into caixa.{tabela} ({', '.join(colunas)}) values\n  {vals};\n"


def main():
    arq = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else PADRAO
    seed = json.loads(arq.read_text(encoding="utf-8"))

    # valores em reais: string decimal com 2 casas, nunca float (princípio 1)
    for grupo, campos in (("movimentos_caixa", ["valor"]),
                          ("operacoes", ["valor_pago", "valor_cheio"]),
                          ("duplicatas", ["valor"])):
        for l in seed[grupo]:
            for c in campos:
                if not isinstance(l[c], str):
                    sys.exit(f"{grupo} id {l['id']}: {c} precisa ser string decimal, veio {l[c]!r}")
                Decimal(l[c])

    out = [f"-- carga gerada de {arq.name}\nbegin;\n",
           """do $$ begin
  if exists (select 1 from caixa.operacao) or exists (select 1 from caixa.movimento_caixa) then
    raise exception 'O banco já tem dados: a carga inicial só roda em banco vazio';
  end if;
end $$;
"""]
    out.append(insert("fornecedor", seed["fornecedores"], ["id", "nome", "cnpj", "chave_pix"]))
    out.append(insert("movimento_caixa", seed["movimentos_caixa"],
                      ["id", "tipo", "data", "valor", "observacoes"]))
    out.append(insert("operacao", seed["operacoes"],
                      ["id", "fornecedor_id", "numero_pedido", "numero_nf", "data_pedido",
                       "data_pagamento", "valor_pago", "valor_cheio", "situacao", "origem",
                       "observacoes"]))
    out.append(insert("duplicata", seed["duplicatas"],
                      ["id", "operacao_id", "sequencia", "valor", "vencimento", "recebida_em"]))

    # o erro clássico: esquecer de reposicionar as sequences
    for t in ("fornecedor", "operacao", "duplicata", "movimento_caixa"):
        out.append(f"select setval('caixa.{t}_id_seq', (select coalesce(max(id), 1) from caixa.{t}));\n")

    # dispara agora as triggers deferred (soma das duplicatas, caixa) para o erro
    # aparecer antes da conferência
    out.append("set constraints all immediate;\n")

    conf = seed.get("conferencia", {})
    checks = [f"  if (select {k} from caixa.v_caixa) <> {Decimal(v)} then\n"
              f"    raise exception 'Conferência falhou em {k}: esperado {v}, veio %', "
              f"(select {k} from caixa.v_caixa);\n  end if;"
              for k, v in conf.items() if k != "identidade"]
    checks.append("  if not (select (caixa + aplicado) = (aportes - retiradas + lucro_realizado)"
                  " from caixa.v_caixa) then\n"
                  "    raise exception 'Identidade caixa + aplicado = aportes - retiradas + lucro_realizado não fecha';\n"
                  "  end if;")
    out.append("do $$ begin\n" + "\n".join(checks) + "\nend $$;\n")
    out.append("commit;\n")
    out.append("select 'carga conferida: ' || count(*) || ' operações' from caixa.operacao;\n")
    sys.stdout.write("\n".join(s for s in out if s))


if __name__ == "__main__":
    main()
