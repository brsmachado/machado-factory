"""docs/04-api.md §5 — aportes e retiradas."""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from .. import fmt
from ..auth import Usuario, pode_lancar, pode_ler
from ..erros import ErroAPI
from ..escrita import executar

r = APIRouter(tags=["caixa"])


class MovimentoNovo(BaseModel):
    tipo: Literal["aporte", "retirada"]
    data: date
    valor: fmt.Dinheiro
    observacoes: Optional[str] = Field(default=None, max_length=1000)


def _json(m: dict) -> dict:
    return {"id": m["id"], "tipo": m["tipo"], "data": fmt.data_iso(m["data"]),
            "valor": fmt.dinheiro(m["valor"]), "observacoes": m["observacoes"],
            "criado_em": m["criado_em"].isoformat()}


@r.get("/movimentos")
def listar(request: Request, u: Usuario = Depends(pode_ler),
           tipo: Optional[Literal["aporte", "retirada"]] = None,
           de: Optional[date] = None, ate: Optional[date] = None):
    onde, p = ["true"], []
    if tipo:
        onde.append("tipo = %s"); p.append(tipo)
    if de:
        onde.append("data >= %s"); p.append(de)
    if ate:
        onde.append("data <= %s"); p.append(ate)
    linhas = request.app.state.banco.todos(
        "select * from movimento_caixa where " + " and ".join(onde) + " order by data desc, id desc", p)
    return {"itens": [_json(m) for m in linhas]}


@r.post("/movimentos", status_code=201)
def criar(dados: MovimentoNovo, request: Request, u: Usuario = Depends(pode_lancar)):
    if dados.valor <= 0:
        raise ErroAPI("validacao", "O valor precisa ser maior que zero")

    def fn(cur, arqs):
        if dados.tipo == "retirada":      # RN-05: o capital na rua não se saca
            cur.execute("select caixa.caixa_disponivel() as c")
            disp = cur.fetchone()["c"]
            if dados.valor > disp:
                raise ErroAPI("caixa_insuficiente",
                              f"Caixa insuficiente: você tem {fmt.brl(max(disp, Decimal(0)))} livre. "
                              "O dinheiro aplicado em duplicatas só pode sair depois que voltar.",
                              {"disponivel": fmt.dinheiro(disp), "solicitado": fmt.dinheiro(dados.valor)})
        cur.execute("""insert into movimento_caixa (tipo, data, valor, observacoes, criado_por)
                       values (%s, %s, %s, %s, nullif(current_setting('caixa.usuario_id', true), '')::bigint)
                       returning *""", (dados.tipo, dados.data, dados.valor, dados.observacoes))
        return _json(cur.fetchone())
    return executar(request, u, "POST /movimentos", fn, status=201, idempotente=True)


def _saldos(cur) -> list[tuple[date, Decimal]]:
    """Caixa no fim de cada dia em que algo aconteceu: movimentos, PIX das
    compras confirmadas e duplicatas recebidas."""
    cur.execute("""
        select dia, sum(delta) as delta from (
          select data as dia, case tipo when 'aporte' then valor else -valor end as delta from movimento_caixa
          union all
          select data_pagamento, -valor_pago from operacao where situacao = 'confirmada'
          union all
          select d.recebida_em, d.valor from duplicata d join operacao o on o.id = d.operacao_id
           where o.situacao = 'confirmada' and d.recebida_em is not null
        ) x group by dia order by dia""")
    saldo, out = Decimal(0), []
    for l in cur.fetchall():
        saldo += l["delta"]
        out.append((l["dia"], saldo))
    return out


@r.delete("/movimentos/{mov_id}", status_code=204)
def excluir(mov_id: int, request: Request, u: Usuario = Depends(pode_lancar)):
    """Só se o caixa continuar não-negativo em toda a linha do tempo depois da
    remoção. Tirar uma retirada só aumenta o caixa; tirar um aporte reduz o
    saldo de todos os dias a partir da data dele."""
    def fn(cur, arqs):
        cur.execute("select * from movimento_caixa where id = %s for update", (mov_id,))
        m = cur.fetchone()
        if not m:
            raise ErroAPI("nao_encontrado", f"Movimento {mov_id} não existe")
        if m["tipo"] == "aporte":
            for dia, saldo in _saldos(cur):
                if dia >= m["data"] and saldo - m["valor"] < 0:
                    raise ErroAPI(
                        "caixa_insuficiente",
                        f"Sem este aporte o caixa ficaria em {fmt.brl(saldo - m['valor'])} em "
                        f"{fmt.br_data(dia)}: o dinheiro dele já foi usado em compras.",
                        {"data": fmt.data_iso(dia), "saldo_sem_aporte": fmt.dinheiro(saldo - m["valor"])})
        cur.execute("delete from movimento_caixa where id = %s", (mov_id,))
        return None
    return executar(request, u, f"DELETE /movimentos/{mov_id}", fn)
