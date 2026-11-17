"""Idempotency-Key (docs/04-api.md §1).

Repetir um POST que cria dinheiro com a mesma chave, em até 24h, devolve a
resposta original sem criar nada. A busca e a gravação rodam dentro da mesma
transação do lançamento, que já está serializada pelo lock de dinheiro — duas
chamadas simultâneas com a mesma chave não criam duas operações.
Só resposta de sucesso é guardada: se deu erro, a nova tentativa roda de novo.
"""
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from .erros import ErroAPI


def chave(request: Request) -> Optional[str]:
    k = request.headers.get("idempotency-key")
    if k is None:
        return None
    k = k.strip()
    if not (8 <= len(k) <= 200):
        raise ErroAPI("validacao", "Idempotency-Key precisa ter entre 8 e 200 caracteres")
    return k


def buscar(cur, k: Optional[str], usuario_id: int, rota: str) -> Optional[JSONResponse]:
    if not k:
        return None
    cur.execute("delete from idempotencia where criado_em < now() - interval '24 hours'")
    cur.execute("select rota, status, resposta from idempotencia where chave = %s and usuario_id = %s",
                (k, usuario_id))
    r = cur.fetchone()
    if not r:
        return None
    if r["rota"] != rota:
        raise ErroAPI("conflito", "Esta Idempotency-Key já foi usada em outra rota",
                      {"rota_original": r["rota"]})
    return JSONResponse(r["resposta"], status_code=r["status"], headers={"Idempotent-Replay": "true"})


def guardar(cur, k: Optional[str], usuario_id: int, rota: str, status: int, corpo) -> None:
    if not k:
        return
    cur.execute("insert into idempotencia (chave, usuario_id, rota, status, resposta) values (%s, %s, %s, %s, %s)",
                (k, usuario_id, rota, status, Jsonb(corpo)))
