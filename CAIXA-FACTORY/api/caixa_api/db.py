"""Conexão com o PostgreSQL (psycopg 3, sem ORM).

Cada requisição que grava roda numa transação só. No início dela a API faz
`set_config('caixa.usuario_id', ...)` para a trigger de auditoria saber quem
agiu (docs/02-modelo-dados.md §3). As triggers deferred (soma das duplicatas,
caixa) disparam no commit; o erro delas sobe como psycopg.Error e vira o
código certo em erros.py.
"""
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# chave do advisory lock que serializa tudo o que mexe em dinheiro: com 50 a
# 100 operações por ano, fila única é mais simples e mais segura que qualquer
# esquema de concorrência fina
LOCK_DINHEIRO = 7_310_001


def criar_pool(url: str, fuso: str) -> ConnectionPool:
    def _configurar(conn: psycopg.Connection):
        # datas de negócio no fuso de São Paulo: current_date do banco = "hoje" do usuário
        conn.execute("select set_config('timezone', %s, false)", (fuso,))
        conn.execute("set search_path to caixa, public")
        conn.commit()

    pool = ConnectionPool(url, min_size=1, max_size=8, configure=_configurar,
                          kwargs={"row_factory": dict_row}, open=False)
    pool.open(wait=True, timeout=10)
    return pool


class Banco:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    @contextmanager
    def transacao(self, usuario_id: Optional[int] = None, dinheiro: bool = False) -> Iterator[psycopg.Cursor]:
        with self.pool.connection() as conn:
            with conn.transaction():
                cur = conn.cursor()
                if usuario_id is not None:
                    cur.execute("select set_config('caixa.usuario_id', %s, true)", (str(usuario_id),))
                if dinheiro:
                    cur.execute("select pg_advisory_xact_lock(%s)", (LOCK_DINHEIRO,))
                yield cur

    def um(self, sql: str, params=None) -> Optional[dict]:
        with self.transacao() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def todos(self, sql: str, params=None) -> list[dict]:
        with self.transacao() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
