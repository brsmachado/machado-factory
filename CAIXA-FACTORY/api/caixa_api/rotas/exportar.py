"""docs/04-api.md §8 — CSV para a planilha e o contador.

O mesmo formato de CAIXA-MACHADO/registros/*.csv: separador `;`, decimal com
vírgula, datas DD/MM/AAAA, todos os campos entre aspas e BOM UTF-8 para o
Excel brasileiro abrir certo. Uma linha por duplicata.
"""
import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from .. import fmt
from ..auth import Usuario, pode_ler

r = APIRouter(tags=["exportação"])

COLUNAS_OPERACOES = [
    "Data compra", "Fornecedor", "NF/Pedido", "Valor cheio", "Valor pago", "Lucro total",
    "Retorno % s/ valor pago", "Desconto % s/ valor cheio", "Prazo (dias)", "% ao mes",
    "Lucro por mes", "Parcela", "Valor parcela", "Vencimento", "Recebida em", "Situacao", "Observacoes",
]


def _csv(cabecalho: list[str], linhas: list[list[str]], nome: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(cabecalho)
    w.writerows(linhas)
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@r.get("/exportar/operacoes.csv")
def operacoes_csv(request: Request, u: Usuario = Depends(pode_ler)):
    linhas = request.app.state.banco.todos("""
        select v.*, f.nome as fornecedor, d.sequencia, d.valor as valor_parcela, d.vencimento,
               d.recebida_em, v.qt_duplicatas
          from v_operacao v
          join fornecedor f on f.id = v.fornecedor_id
          join duplicata d on d.operacao_id = v.id
         order by v.data_pagamento desc, v.id desc, d.sequencia""")
    saida = []
    for l in linhas:
        doc = l["numero_pedido"] + (f" - NFe {l['numero_nf']}" if l["numero_nf"] else "")
        saida.append([
            fmt.br_data(l["data_pagamento"]), l["fornecedor"], doc,
            fmt.br_decimal(l["valor_cheio"]), fmt.br_decimal(l["valor_pago"]), fmt.br_decimal(l["lucro"]),
            fmt.br_decimal(l["retorno"] * 100), fmt.br_decimal(l["desconto"] * 100),
            fmt.br_decimal(l["prazo_medio"], 0), fmt.br_decimal(l["taxa_mes"] * 100),
            fmt.br_decimal(l["valor_pago"] * l["taxa_mes"]),
            f"{l['sequencia']}/{l['qt_duplicatas']}", fmt.br_decimal(l["valor_parcela"]),
            fmt.br_data(l["vencimento"]), fmt.br_data(l["recebida_em"]),
            "Recebida" if l["recebida_em"] else "Em aberto",
            l["observacoes"] or "",
        ])
    return _csv(COLUNAS_OPERACOES, saida, "operacoes.csv")


@r.get("/exportar/movimentos.csv")
def movimentos_csv(request: Request, u: Usuario = Depends(pode_ler)):
    linhas = request.app.state.banco.todos("select * from movimento_caixa order by data desc, id desc")
    saida = [[fmt.br_data(m["data"]), m["tipo"].capitalize(), fmt.br_decimal(m["valor"]), m["observacoes"] or ""]
             for m in linhas]
    return _csv(["Data", "Tipo", "Valor", "Observacoes"], saida, "movimentos.csv")
