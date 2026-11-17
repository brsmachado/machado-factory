"""Um jeito só de gravar: transação + quem agiu + lock de dinheiro +
Idempotency-Key + arquivos em disco que acompanham o commit."""
from typing import Any, Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from . import idempotencia
from .auth import Usuario
from .documentos import Arquivos


def executar(request: Request, u: Usuario, rota: str, fn: Callable[[Any, Arquivos], Any],
             status: int = 200, idempotente: bool = False) -> Response:
    app = request.app
    k = idempotencia.chave(request) if idempotente else None
    arqs = Arquivos(app.state.cfg.documentos_dir)
    try:
        with app.state.banco.transacao(u.id, dinheiro=True) as cur:
            salvo = idempotencia.buscar(cur, k, u.id, rota)
            if salvo is not None:
                return salvo
            corpo = fn(cur, arqs)
            if isinstance(corpo, tuple):        # (status, corpo): a função decide o status
                status, corpo = corpo
            idempotencia.guardar(cur, k, u.id, rota, status, corpo)
    except BaseException:
        arqs.desfazer()
        raise
    arqs.confirmar()
    if corpo is None:
        return Response(status_code=204)
    return JSONResponse(corpo, status_code=status)
