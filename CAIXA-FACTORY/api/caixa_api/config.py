"""Configuração lida do ambiente (o .env de docs/08-deploy.md §4)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_url: str
    documentos_dir: Path
    web_dir: Path = Path(__file__).resolve().parents[2] / "web"   # CAIXA-FACTORY/web
    robo_token: str = ""
    robo_email: str = "robo@caixa.local"
    sessao_horas: int = 12
    max_upload_bytes: int = 20 * 1024 * 1024        # docs/06-robo.md: limite de 20 MB
    telegram_token: str = ""
    telegram_chat_id: str = ""                       # o robô só conversa com este chat
    telegram_usuario_email: str = ""                 # o dono: cliques no Telegram agem como ele
    telegram_api: str = "https://api.telegram.org"
    modelo_leitura: str = "claude-opus-5-5"
    versao: str = "1.1.0"
    fuso: str = "America/Sao_Paulo"
    extras: dict = field(default_factory=dict)

    @classmethod
    def do_ambiente(cls) -> "Config":
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL não definido (ver docs/08-deploy.md §4)")
        return cls(
            database_url=url,
            documentos_dir=Path(os.environ.get("DOCUMENTOS_DIR", "./documentos")).resolve(),
            web_dir=Path(os.environ.get("WEB_DIR", str(Path(__file__).resolve().parents[2] / "web"))).resolve(),
            robo_token=os.environ.get("ROBO_TOKEN", ""),
            robo_email=os.environ.get("ROBO_EMAIL", "robo@caixa.local"),
            sessao_horas=int(os.environ.get("SESSAO_HORAS", "12")),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            telegram_usuario_email=os.environ.get("TELEGRAM_USUARIO_EMAIL", ""),
            modelo_leitura=os.environ.get("MODELO_LEITURA", "claude-opus-5-5"),
        )
