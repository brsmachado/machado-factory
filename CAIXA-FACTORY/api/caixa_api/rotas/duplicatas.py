"""docs/04-api.md §4 — recebimentos."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import fmt
from .. import operacoes as ops
from ..auth import Usuario, pode_lancar
from ..erros import ErroAPI
from ..escrita import executar

r = APIRouter(tags=["recebimentos"])


class Recebimento(BaseModel):
    data: Optional[date] = None          # padrão: hoje (America/Sao_Paulo)


class ItemLote(BaseModel):
    id: int
    data: Optional[date] = None


class Lote(BaseModel):
    itens: list[ItemLote] = Field(min_length=1, max_length=200)


def _travar(cur, dup_id: int) -> dict:
    cur.execute("""select d.id, d.operacao_id, d.sequencia, d.valor, d.vencimento, d.recebida_em,
                          o.situacao, o.data_pagamento, o.numero_pedido, current_date as hoje
                     from duplicata d join operacao o on o.id = d.operacao_id
                    where d.id = %s for update of d, o""", (dup_id,))
    d = cur.fetchone()
    if not d:
        raise ErroAPI("nao_encontrado", f"Duplicata {dup_id} não existe")
    if d["situacao"] == "estornada":
        raise ErroAPI("conflito", f"A operação {d['numero_pedido']} está estornada")
    if d["situacao"] == "rascunho":
        raise ErroAPI("conflito", f"A operação {d['numero_pedido']} ainda é rascunho: confirme antes de receber")
    return d


def _receber(cur, dup_id: int, data: Optional[date]) -> dict:
    d = _travar(cur, dup_id)
    data = data or d["hoje"]
    if d["recebida_em"]:
        raise ErroAPI("conflito", f"Duplicata {d['sequencia']} do {d['numero_pedido']} já foi recebida em "
                                  f"{fmt.br_data(d['recebida_em'])}",
                      {"duplicata_id": dup_id, "recebida_em": fmt.data_iso(d["recebida_em"])})
    if data < d["data_pagamento"]:      # RN-04
        raise ErroAPI("validacao", f"Recebimento em {fmt.br_data(data)} é anterior ao pagamento em "
                                   f"{fmt.br_data(d['data_pagamento'])}", {"duplicata_id": dup_id})
    if data > d["hoje"]:
        raise ErroAPI("validacao", f"Recebimento em {fmt.br_data(data)} está no futuro: lance quando o "
                                   "dinheiro entrar", {"duplicata_id": dup_id})
    cur.execute("update duplicata set recebida_em = %s where id = %s", (data, dup_id))
    return d


@r.post("/duplicatas/receber-lote")
def receber_lote(dados: Lote, request: Request, u: Usuario = Depends(pode_lancar)):
    ids = [i.id for i in dados.itens]
    if len(ids) != len(set(ids)):
        raise ErroAPI("validacao", "A mesma duplicata aparece duas vezes no lote")

    def fn(cur, arqs):
        ops_ids = []
        for i in dados.itens:       # tudo numa transação: ou todas entram, ou nenhuma
            ops_ids.append(_receber(cur, i.id, i.data)["operacao_id"])
        return {"recebidas": ids,
                "operacoes": [ops.obter(cur, o) for o in dict.fromkeys(ops_ids)]}
    return executar(request, u, "POST /duplicatas/receber-lote", fn, idempotente=True)


@r.post("/duplicatas/{dup_id}/receber")
def receber(dup_id: int, request: Request, dados: Optional[Recebimento] = None,
            u: Usuario = Depends(pode_lancar)):
    def fn(cur, arqs):
        d = _receber(cur, dup_id, dados.data if dados else None)
        return ops.obter(cur, d["operacao_id"])
    return executar(request, u, f"POST /duplicatas/{dup_id}/receber", fn, idempotente=True)


@r.delete("/duplicatas/{dup_id}/receber")
def desfazer(dup_id: int, request: Request, u: Usuario = Depends(pode_lancar)):
    """O valor sai do caixa, a duplicata volta a aberta; o log grava 'desfez'."""
    def fn(cur, arqs):
        d = _travar(cur, dup_id)
        if not d["recebida_em"]:
            raise ErroAPI("conflito", f"Duplicata {d['sequencia']} do {d['numero_pedido']} não está recebida")
        cur.execute("update duplicata set recebida_em = null where id = %s", (dup_id,))
        return ops.obter(cur, d["operacao_id"])
    return executar(request, u, f"DELETE /duplicatas/{dup_id}/receber", fn)
