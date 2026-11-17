"""Monta a aplicação: /api/v1/... (docs/04-api.md)."""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, FastAPI

from . import erros
from .config import Config
from .db import Banco, criar_pool
from .robo import criar_robo
from .rotas import (documentos, duplicatas, exportar, fornecedores, movimentos, operacoes, paineis,
                    robo, sistema)

PREFIXO = "/api/v1"


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
    for m in (sistema, paineis, operacoes, duplicatas, movimentos, fornecedores, documentos, exportar, robo):
        api.include_router(m.r)
    app.include_router(api)
    return app
