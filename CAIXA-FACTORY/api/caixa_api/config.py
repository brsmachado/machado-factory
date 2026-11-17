"""Configuração lida do ambiente (o .env de docs/08-deploy.md §4)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_url: str
    documentos_dir: Path
    robo_token: str = ""
    robo_email: str = "robo@caixa.local"
    sessao_horas: int = 12
    max_upload_bytes: int = 20 * 1024 * 1024        # docs/06-robo.md: limite de 20 MB
    versao: str = "1.0.0"
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
            robo_token=os.environ.get("ROBO_TOKEN", ""),
            robo_email=os.environ.get("ROBO_EMAIL", "robo@caixa.local"),
            sessao_horas=int(os.environ.get("SESSAO_HORAS", "12")),
        )
