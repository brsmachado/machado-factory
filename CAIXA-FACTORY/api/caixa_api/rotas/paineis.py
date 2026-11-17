"""docs/04-api.md §2 — resumo, resultado mensal e agenda.

Os números vêm das views do banco (implementação de referência das fórmulas).
"""
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from .. import fmt
from ..auth import Usuario, pode_ler
from ..erros import ErroAPI

r = APIRouter(tags=["painéis"])


@r.get("/resumo")
def resumo(request: Request, u: Usuario = Depends(pode_ler)):
    c = request.app.state.banco.um("select * from v_caixa, v_carteira")
    return {
        "caixa": fmt.dinheiro(c["caixa"]),
        "aplicado": fmt.dinheiro(c["aplicado"]),
        "capital": fmt.dinheiro(c["capital"]),
        "a_receber": fmt.dinheiro(c["a_receber"]),
        "lucro_realizado": fmt.dinheiro(c["lucro_realizado"]),
        "lucro_a_receber": fmt.dinheiro(c["lucro_a_receber"]),
        "aportes": fmt.dinheiro(c["aportes"]),
        "retiradas": fmt.dinheiro(c["retiradas"]),
        "duplicatas_abertas": c["duplicatas_abertas"],
        "operacoes_abertas": c["operacoes_abertas"],
        "rentabilidade": {
            "retorno": fmt.taxa(c["retorno"]),
            "prazo_medio_dias": fmt.dias(c["prazo_medio_dias"]),
            "taxa_mes": fmt.taxa(c["taxa_mes"]),
            "taxa_ano": fmt.taxa(c["taxa_ano"]),
            "lucro_mes_reais": fmt.dinheiro(c["lucro_mes_reais"]),
            "ocupacao": fmt.taxa(c["ocupacao"]),
            "rendimento_caixa_inteiro": fmt.taxa(c["rendimento_caixa_inteiro"]),
        },
    }


_RE_MES = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _mes(v: Optional[str], campo: str) -> Optional[date]:
    if v is None:
        return None
    m = _RE_MES.match(v)
    if not m:
        raise ErroAPI("validacao", f"{campo}: use AAAA-MM, ex.: 2026-08", {"campo": campo})
    return date(int(m[1]), int(m[2]), 1)


@r.get("/resultado-mensal")
def resultado_mensal(request: Request, u: Usuario = Depends(pode_ler),
                     de: Optional[str] = None, ate: Optional[str] = None):
    d, a = _mes(de, "de"), _mes(ate, "ate")
    if d and a and d > a:
        raise ErroAPI("validacao", "de precisa ser antes de ate")
    if d and a and (a.year - d.year) * 12 + a.month - d.month > 120:
        raise ErroAPI("validacao", "No máximo 10 anos por consulta")
    linhas = request.app.state.banco.todos("select * from resultado_mensal(%s, %s)", (d, a))
    return {"meses": [{
        "mes": m["mes"], "dias": m["dias"], "estado": m["estado"],
        "lucro": fmt.dinheiro(m["lucro"]),
        "aplicado_medio": fmt.dinheiro(m["aplicado_medio"]),
        "capital_medio": fmt.dinheiro(m["capital_medio"]),
        "parado_medio": fmt.dinheiro(m["parado_medio"]),
        "ocupacao": fmt.taxa(m["ocupacao"]),
        "taxa_mes": fmt.taxa(m["taxa_mes"]),
        "taxa_sobre_total": fmt.taxa(m["taxa_sobre_total"]),
        "custo_do_parado": fmt.dinheiro(m["custo_do_parado"]),
    } for m in linhas]}


@r.get("/agenda")
def agenda(request: Request, u: Usuario = Depends(pode_ler),
           dias: Optional[int] = Query(default=None, ge=0, le=3650)):
    """Duplicatas em aberto que vencem até hoje + `dias` (as atrasadas sempre entram)."""
    banco = request.app.state.banco
    if dias is None:
        p = banco.um("select valor from parametro where chave = 'dias_agenda'")
        dias = int(p["valor"]) if p else 45
    linhas = banco.todos("select * from v_agenda where vencimento <= current_date + %s", (dias,))
    return {
        "dias": dias,
        "duplicatas": [{
            "id": d["id"], "operacao_id": d["operacao_id"], "fornecedor": d["fornecedor"],
            "numero_pedido": d["numero_pedido"], "sequencia": d["sequencia"], "de": d["de"],
            "valor": fmt.dinheiro(d["valor"]), "vencimento": fmt.data_iso(d["vencimento"]),
            "dias_para_vencer": d["dias_para_vencer"], "atrasada": d["atrasada"],
        } for d in linhas],
        "total": fmt.dinheiro(sum((d["valor"] for d in linhas), Decimal(0))),
    }
