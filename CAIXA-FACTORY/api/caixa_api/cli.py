"""Administração pela linha de comando.

    python -m caixa_api.cli criar-usuario --nome "Bruno" --email bruno@... --papel admin
    python -m caixa_api.cli senha --email bruno@...
    python -m caixa_api.cli criar-robo            # usuário do ROBO_EMAIL, papel operador

A senha é pedida no terminal (não aparece na tela nem no histórico do shell).
"""
import argparse
import getpass
import os
import secrets
import sys

import psycopg

from .auth import hash_senha


def _conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL não definido")
    return psycopg.connect(url)


def _senha() -> str:
    s1 = getpass.getpass("Senha: ")
    if len(s1) < 10:
        sys.exit("A senha precisa ter pelo menos 10 caracteres")
    if getpass.getpass("Repita: ") != s1:
        sys.exit("As senhas não conferem")
    return s1


def main(argv=None):
    p = argparse.ArgumentParser(prog="caixa_api.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar-usuario")
    c.add_argument("--nome", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--papel", choices=["admin", "operador", "leitura"], default="operador")
    s = sub.add_parser("senha")
    s.add_argument("--email", required=True)
    sub.add_parser("criar-robo")
    a = p.parse_args(argv)

    with _conn() as conn:
        if a.cmd == "criar-usuario":
            conn.execute("insert into caixa.usuario (nome, email, senha_hash, papel) values (%s, %s, %s, %s)",
                         (a.nome, a.email.strip().lower(), hash_senha(_senha()), a.papel))
            print(f"usuário {a.email} criado com papel {a.papel}")
        elif a.cmd == "senha":
            n = conn.execute("update caixa.usuario set senha_hash = %s where lower(email) = lower(%s)",
                             (hash_senha(_senha()), a.email)).rowcount
            print("senha trocada" if n else "usuário não encontrado")
        elif a.cmd == "criar-robo":
            email = os.environ.get("ROBO_EMAIL", "robo@caixa.local")
            # senha aleatória e descartada: o robô entra só pelo ROBO_TOKEN
            conn.execute("insert into caixa.usuario (nome, email, senha_hash, papel) values "
                         "('Robô', %s, %s, 'operador') on conflict (email) do nothing",
                         (email, hash_senha(secrets.token_urlsafe(32))))
            print(f"usuário do robô: {email} (papel operador)")


if __name__ == "__main__":
    main()
