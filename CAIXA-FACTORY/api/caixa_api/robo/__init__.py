"""O robô do Caixa Factory: um só, no Telegram (docs/06-robo.md)."""
from typing import Optional

from .servico import Robo


def criar_robo(banco, cfg, extrator=None, telegram=None) -> Robo:
    """Monta o robô com o leitor de documentos (Claude) e o cliente do Telegram do .env."""
    if extrator is None:
        from .extracao import ExtratorClaude
        extrator = ExtratorClaude(modelo=cfg.modelo_leitura)
    if telegram is None and cfg.telegram_token:
        from .telegram import ClienteTelegram
        telegram = ClienteTelegram(cfg.telegram_token, cfg.telegram_api)
    return Robo(banco, cfg, extrator, telegram)
