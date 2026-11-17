"""Formato único de erro (docs/04-api.md §1) e tradução dos erros do banco.

As regras de negócio estão no banco como triggers com nome de constraint;
aqui cada nome vira o código de erro da API.
"""
from typing import Any, Optional

import psycopg
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

STATUS = {
    "nao_autenticado": 401,
    "sem_permissao": 403,
    "nao_encontrado": 404,
    "validacao": 422,
    "caixa_insuficiente": 422,
    "soma_duplicatas": 422,
    "conflito": 409,
    "erro_interno": 500,
}


class ErroAPI(Exception):
    def __init__(self, codigo: str, mensagem: str, detalhe: Optional[dict] = None,
                 status: Optional[int] = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhe = detalhe
        self.status = status or STATUS[codigo]


def corpo(codigo: str, mensagem: str, detalhe: Any = None) -> dict:
    e = {"codigo": codigo, "mensagem": mensagem}
    if detalhe is not None:
        e["detalhe"] = detalhe
    return {"erro": e}


def resposta(e: ErroAPI) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if e.status == 401 else None
    return JSONResponse(corpo(e.codigo, e.mensagem, e.detalhe), status_code=e.status, headers=headers)


# nome da constraint / trigger no banco -> código da API
_POR_CONSTRAINT = {
    "rn01_soma_duplicatas": "soma_duplicatas",
    "rn03_caixa_suficiente": "caixa_insuficiente",
    "rn05_retirada_limitada": "caixa_insuficiente",
    "rn04_recebimento_apos_pagamento": "validacao",
    "rn06_sem_exclusao_com_recebimento": "conflito",
    "operacao_estornada_congelada": "conflito",
    "ciclo_de_vida": "conflito",
    "pedido_unico_por_fornecedor": "conflito",
}

_MSG_CONSTRAINT = {
    "pedido_unico_por_fornecedor": "Já existe operação com este número de pedido para este fornecedor",
    "pago_nao_passa_do_cheio": "O valor pago não pode passar do valor cheio",
    "vencimento_plausivel": "Vencimento com ano implausível — confira o ano impresso no pedido (A-02)",
    "estorno_completo": "Estorno precisa de motivo",
    "fornecedor_cnpj_key": "Já existe fornecedor com este CNPJ",
    "usuario_email_key": "Já existe usuário com este e-mail",
}


def do_banco(exc: psycopg.Error) -> ErroAPI:
    diag = exc.diag
    nome = diag.constraint_name or ""
    msg = diag.message_primary or "Erro no banco"
    if nome in _POR_CONSTRAINT:
        return ErroAPI(_POR_CONSTRAINT[nome], _MSG_CONSTRAINT.get(nome, msg), {"regra": nome})
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return ErroAPI("conflito", _MSG_CONSTRAINT.get(nome, "Registro duplicado"), {"regra": nome})
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return ErroAPI("validacao", "Referência a registro que não existe", {"regra": nome})
    if isinstance(exc, (psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation,
                        psycopg.errors.InvalidTextRepresentation,
                        psycopg.errors.NumericValueOutOfRange)):
        return ErroAPI("validacao", _MSG_CONSTRAINT.get(nome, msg), {"regra": nome} if nome else None)
    if isinstance(exc, psycopg.errors.RestrictViolation):
        return ErroAPI("conflito", msg, {"regra": nome} if nome else None)
    return ErroAPI("erro_interno", "Erro interno no banco de dados")


def instalar(app):
    @app.exception_handler(ErroAPI)
    async def _erro_api(request: Request, e: ErroAPI):
        return resposta(e)

    @app.exception_handler(psycopg.Error)
    async def _erro_banco(request: Request, e: psycopg.Error):
        erro = do_banco(e)
        if erro.codigo == "erro_interno":
            request.app.state.log.exception("erro no banco", exc_info=e)
        return resposta(erro)

    @app.exception_handler(RequestValidationError)
    async def _erro_validacao(request: Request, e: RequestValidationError):
        campos = []
        for err in e.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            m = str(err.get("msg", "inválido")).removeprefix("Value error, ")
            campos.append({"campo": ".".join(loc), "mensagem": m})
        primeira = campos[0] if campos else {"campo": "", "mensagem": "inválido"}
        txt = f"{primeira['campo']}: {primeira['mensagem']}" if primeira["campo"] else primeira["mensagem"]
        return JSONResponse(corpo("validacao", txt, {"campos": campos}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _erro_http(request: Request, e: StarletteHTTPException):
        codigo = {401: "nao_autenticado", 403: "sem_permissao", 404: "nao_encontrado",
                  405: "validacao", 409: "conflito"}.get(e.status_code, "erro_interno")
        msg = "Rota não encontrada" if e.status_code == 404 else str(e.detail)
        return JSONResponse(corpo(codigo, msg), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _erro_geral(request: Request, e: Exception):
        request.app.state.log.exception("erro não tratado", exc_info=e)
        return JSONResponse(corpo("erro_interno", "Erro interno"), status_code=500)
