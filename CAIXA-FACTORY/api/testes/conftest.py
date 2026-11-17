"""Testes contra PostgreSQL de verdade.

Uma vez por rodada: cria o banco-modelo `caixa_api_modelo` com as migrações,
a carga de 19/10/2026, quatro usuários e uma sessão de cada. Cada teste
recebe uma cópia nova (`create database ... template ...`, rápido), então os
testes não se enxergam.

Variáveis: PGHOST, PGPORT, PGUSER (precisa poder criar banco).
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[2]          # CAIXA-FACTORY/
sys.path.insert(0, str(RAIZ / "api"))

from caixa_api.app import criar_app        # noqa: E402
from caixa_api.auth import hash_senha, hash_token  # noqa: E402
from caixa_api.config import Config        # noqa: E402

MODELO = "caixa_api_modelo"
TOKENS = {"admin": "tok-admin-0000000000", "operador": "tok-operador-00000000",
          "leitura": "tok-leitura-000000000"}
ROBO_TOKEN = "tok-robo-de-teste-000000000000"
SENHA = "senha-de-teste-123"


def _url(db: str) -> str:
    return psycopg.conninfo.make_conninfo(dbname=db)


def _admin():
    return psycopg.connect(_url("postgres"), autocommit=True)


@pytest.fixture(scope="session")
def modelo():
    with _admin() as c:
        c.execute(f"drop database if exists {MODELO}")
        c.execute(f"create database {MODELO}")
    env = {**os.environ, "PGDATABASE": MODELO}
    env.pop("DATABASE_URL", None)
    subprocess.run([str(RAIZ / "banco" / "aplicar.sh")], env=env, check=True, capture_output=True)
    seed = subprocess.run([sys.executable, str(RAIZ / "banco" / "carregar_seed.py")],
                          check=True, capture_output=True, text=True).stdout
    with psycopg.connect(_url(MODELO), autocommit=True) as c:
        c.execute(seed)
        h = hash_senha(SENHA)
        for papel, tok in TOKENS.items():
            uid = c.execute("insert into caixa.usuario (nome, email, senha_hash, papel) values (%s, %s, %s, %s) "
                            "returning id", (papel.capitalize(), f"{papel}@teste.invalid", h, papel)).fetchone()[0]
            c.execute("insert into caixa.sessao (token_hash, usuario_id, expira_em) "
                      "values (%s, %s, now() + interval '10 years')", (hash_token(tok), uid))
        c.execute("insert into caixa.usuario (nome, email, senha_hash, papel) values "
                  "('Robô', 'robo@caixa.local', 'x', 'operador')")
    yield MODELO
    with _admin() as c:
        c.execute(f"drop database if exists {MODELO}")


@pytest.fixture
def banco(modelo):
    nome = f"caixa_api_t_{uuid.uuid4().hex[:10]}"
    with _admin() as c:
        c.execute(f"create database {nome} template {modelo}")
    yield nome
    with _admin() as c:
        c.execute(f"drop database if exists {nome} with (force)")


@pytest.fixture
def docs_dir(tmp_path):
    return tmp_path / "documentos"


@pytest.fixture
def app(banco, docs_dir):
    cfg = Config(database_url=_url(banco), documentos_dir=docs_dir, robo_token=ROBO_TOKEN)
    return criar_app(cfg)


class Cliente:
    """TestClient com atalhos por papel: api.get(url, como='leitura')."""

    def __init__(self, tc: TestClient):
        self.tc = tc

    def _h(self, como, extra=None):
        h = {}
        if como == "robo":
            h["Authorization"] = f"Bearer {ROBO_TOKEN}"
        elif como:
            h["Authorization"] = f"Bearer {TOKENS[como]}"
        h.update(extra or {})
        return h

    def get(self, url, como="operador", **kw):
        return self.tc.get("/api/v1" + url, headers=self._h(como, kw.pop("headers", None)), **kw)

    def post(self, url, como="operador", **kw):
        return self.tc.post("/api/v1" + url, headers=self._h(como, kw.pop("headers", None)), **kw)

    def patch(self, url, como="operador", **kw):
        return self.tc.patch("/api/v1" + url, headers=self._h(como, kw.pop("headers", None)), **kw)

    def delete(self, url, como="operador", **kw):
        return self.tc.delete("/api/v1" + url, headers=self._h(como, kw.pop("headers", None)), **kw)


@pytest.fixture
def api(app):
    with TestClient(app) as tc:
        yield Cliente(tc)


@pytest.fixture
def sql(banco):
    """Conexão direta para conferir o que foi gravado."""
    with psycopg.connect(_url(banco), autocommit=True) as c:
        c.execute("set search_path to caixa, public")
        yield c
