"""Histórico: o log de auditoria (docs/05-telas.md, /historico). Só leitura."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from ..auth import Usuario, pode_ler

r = APIRouter(tags=["histórico"])

ENTIDADES = ("operacao", "duplicata", "movimento_caixa", "fornecedor", "documento", "usuario", "rascunho")


@r.get("/eventos")
def listar(request: Request, u: Usuario = Depends(pode_ler),
           entidade: Optional[str] = Query(default=None, pattern="^(" + "|".join(ENTIDADES) + ")$"),
           entidade_id: Optional[int] = None,
           antes_de: Optional[int] = Query(default=None, description="paginação: id do último evento já visto"),
           limite: int = Query(default=100, ge=1, le=500)):
    onde, p = ["true"], []
    if entidade:
        onde.append("e.entidade = %s"); p.append(entidade)
    if entidade_id:
        onde.append("e.entidade_id = %s"); p.append(entidade_id)
    if antes_de:
        onde.append("e.id < %s"); p.append(antes_de)
    linhas = request.app.state.banco.todos(
        "select e.*, us.nome as usuario_nome from evento e left join usuario us on us.id = e.usuario_id "
        "where " + " and ".join(onde) + " order by e.id desc limit %s", p + [limite])
    return {"itens": [{
        "id": e["id"], "em": e["em"].isoformat(), "entidade": e["entidade"], "entidade_id": e["entidade_id"],
        "acao": e["acao"], "usuario": e["usuario_nome"], "antes": e["antes"], "depois": e["depois"],
    } for e in linhas]}
