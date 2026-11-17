"""docs/04-api.md §3 — operações."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request

from .. import operacoes as ops
from ..auth import Usuario, pode_lancar, pode_ler
from ..escrita import executar

r = APIRouter(tags=["operações"])


@r.get("/operacoes")
def listar(request: Request, u: Usuario = Depends(pode_ler),
           estado: Optional[Literal["em_aberto", "parcial", "encerrada", "atrasada",
                                    "rascunho", "estornada"]] = None,
           fornecedor_id: Optional[int] = None,
           q: Optional[str] = Query(default=None, max_length=100),
           de: Optional[date] = None, ate: Optional[date] = None,
           pagina: int = Query(default=1, ge=1), por_pagina: int = Query(default=50, ge=1, le=200)):
    with request.app.state.banco.transacao() as cur:
        return ops.listar(cur, estado=estado, fornecedor_id=fornecedor_id, q=q, de=de, ate=ate,
                          pagina=pagina, por_pagina=por_pagina)


@r.get("/operacoes/{op_id}")
def obter(op_id: int, request: Request, u: Usuario = Depends(pode_ler)):
    with request.app.state.banco.transacao() as cur:
        return ops.obter(cur, op_id)


@r.post("/operacoes", status_code=201)
def criar(dados: ops.OperacaoNova, request: Request, u: Usuario = Depends(pode_lancar)):
    def fn(cur, arqs):
        return ops.obter(cur, ops.criar(cur, arqs, dados))
    return executar(request, u, "POST /operacoes", fn, status=201, idempotente=True)


@r.patch("/operacoes/{op_id}")
def alterar(op_id: int, dados: ops.OperacaoAlteracao, request: Request, u: Usuario = Depends(pode_lancar)):
    def fn(cur, arqs):
        avisos = ops.alterar(cur, arqs, op_id, dados)
        return {**ops.obter(cur, op_id), "avisos": avisos}
    return executar(request, u, f"PATCH /operacoes/{op_id}", fn)


@r.post("/operacoes/{op_id}/estorno")
def estornar(op_id: int, dados: ops.Estorno, request: Request, u: Usuario = Depends(pode_lancar)):
    def fn(cur, arqs):
        ops.estornar(cur, op_id, dados.motivo)
        return ops.obter(cur, op_id)
    return executar(request, u, f"POST /operacoes/{op_id}/estorno", fn)


@r.delete("/operacoes/{op_id}", status_code=204)
def excluir(op_id: int, request: Request, u: Usuario = Depends(pode_lancar),
            motivo: Optional[str] = Query(default=None, max_length=500)):
    def fn(cur, arqs):
        ops.excluir(cur, op_id, motivo)
        return None
    return executar(request, u, f"DELETE /operacoes/{op_id}", fn)
