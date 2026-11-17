"""Monta a aplicação: /api/v1/... (docs/04-api.md)."""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import erros
from .config import Config
from .db import Banco, criar_pool
from .robo import criar_robo
from .rotas import (documentos, duplicatas, eventos, exportar, fornecedores, movimentos, operacoes, paineis,
                    robo, sistema)

PREFIXO = "/api/v1"

# A tela: script só do próprio servidor (barra XSS), fontes do Google, nada de
# moldura de outro site. style 'unsafe-inline' porque as barras usam style="width:".
CSP_TELA = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")


def criar_app(cfg: Optional[Config] = None, extrator=None, telegram=None) -> FastAPI:
    """`extrator` e `telegram` só são passados nos testes; em produção vêm do .env."""
    cfg = cfg or Config.do_ambiente()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        cfg.documentos_dir.mkdir(parents=True, exist_ok=True)
        pool = criar_pool(cfg.database_url, cfg.fuso)
        app.state.banco = Banco(pool)
        app.state.robo = criar_robo(app.state.banco, cfg, extrator, telegram)
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(title="Caixa Factory", version=cfg.versao, lifespan=ciclo,
                  docs_url=f"{PREFIXO}/docs", openapi_url=f"{PREFIXO}/openapi.json", redoc_url=None)
    app.state.cfg = cfg
    app.state.log = logging.getLogger("caixa_api")
    erros.instalar(app)

    api = APIRouter(prefix=PREFIXO)
    for m in (sistema, paineis, operacoes, duplicatas, movimentos, fornecedores, documentos, exportar, robo, eventos):
        api.include_router(m.r)
    app.include_router(api)

    @app.middleware("http")
    async def cabecalhos(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith("/api/"):
            resp.headers.setdefault("Content-Security-Policy", CSP_TELA)
            resp.headers.setdefault("Cache-Control", "no-cache")
        return resp

    if cfg.web_dir.is_dir():           # a tela (docs/05-telas.md), no mesmo endereço da API
        app.mount("/", StaticFiles(directory=cfg.web_dir, html=True), name="tela")
    return app
