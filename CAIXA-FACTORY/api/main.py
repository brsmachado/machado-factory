"""Ponto de entrada do uvicorn: `uvicorn main:app` (docs/08-deploy.md §4)."""
from caixa_api.app import criar_app

app = criar_app()
