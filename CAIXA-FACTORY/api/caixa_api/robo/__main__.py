"""Linha de comando do robô.

    python -m caixa_api.robo telegram          # o robô no ar (serviço systemd)
    python -m caixa_api.robo aviso             # o aviso do dia (cron, dias úteis às 9h)
    python -m caixa_api.robo aviso --mostrar   # só mostra, não manda
"""
import argparse
import logging
import sys

from ..config import Config
from ..db import Banco, criar_pool
from . import criar_robo


def main(argv=None):
    p = argparse.ArgumentParser(prog="caixa_api.robo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("telegram")
    a = sub.add_parser("aviso")
    a.add_argument("--mostrar", action="store_true", help="imprime o aviso em vez de mandar")
    a.add_argument("--forcar", action="store_true", help="manda mesmo num dia sem nada a dizer")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = Config.do_ambiente()
    banco = Banco(criar_pool(cfg.database_url, cfg.fuso))
    robo = criar_robo(banco, cfg)
    if args.cmd == "aviso":
        res = robo.aviso(enviar=not args.mostrar, forcar=args.forcar)
        if args.mostrar or not res["enviado"]:
            print(res["texto"])
            if not res["enviado"] and not args.mostrar:
                print("\n(não enviado: dia sem nada a dizer, ou Telegram não configurado)", file=sys.stderr)
    else:
        if not (cfg.telegram_token and cfg.telegram_chat_id and cfg.telegram_usuario_email):
            sys.exit("Configure TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID e TELEGRAM_USUARIO_EMAIL no .env")
        from .telegram import BotTelegram
        BotTelegram(robo, robo.telegram).rodar()


if __name__ == "__main__":
    main()
