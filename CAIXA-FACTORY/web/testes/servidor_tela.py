"""Servidor de teste da tela: dados reais de 19/10, leitor de documentos falso."""
import os, sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "api"))
import psycopg, uvicorn
from caixa_api.app import criar_app
from caixa_api.auth import hash_senha
from caixa_api.config import Config
from caixa_api.robo.extracao import normalizar

URL = os.environ.get("DATABASE_URL", "postgresql:///caixa_tela")
with psycopg.connect(URL, autocommit=True) as c:
    c.execute("insert into caixa.usuario (nome,email,senha_hash,papel) values ('Bruno','dono@teste.invalid',%s,'admin') on conflict do nothing", (hash_senha("senha-de-teste-123"),))
    c.execute("insert into caixa.usuario (nome,email,senha_hash,papel) values ('Robô','robo@caixa.local','x','operador') on conflict do nothing")
    c.execute("update caixa.fornecedor set observacoes='Lança o desconto na própria nota — conferir soma dos itens (A-01)' where id=2")

class Leitor:
    """Qualquer PNG enviado vira o pedido da SB com desconto na nota; qualquer PDF, o PIX."""
    def extrair(self, conteudo, mime):
        if mime == "application/pdf":
            return normalizar({"tipo_documento": "comprovante_pix", "pedido": None, "confianca": {"valor_pago": 0.99},
                "comprovante": {"valor": "9336.00", "data_pagamento": "2026-11-12", "recebedor_nome": "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
                                "recebedor_documento": None, "id_transacao": "E123"}})
        return normalizar({"tipo_documento": "pedido_compra", "comprovante": None, "confianca": {"total_pedido": 0.98},
            "pedido": {"numero_pedido": "PEDIDO DE COMPRA03610-1/26", "numero_nf": "13100", "data_pedido": "2026-11-10",
                       "fornecedor_nome": "SB INDUSTRIA E COMERCIO DE PAPEL LTDA", "fornecedor_cnpj": None,
                       "itens": [{"descricao": "PAPEL ACOPLADO", "quantidade": "250", "valor_unitario": "38.90", "valor_total": "9725.00"}],
                       "total_pedido": "9327.00", "condicao_pagamento": "30",
                       "duplicatas": [{"vencimento": "2026-12-12", "valor": "9327.00"}]}})

cfg = Config(database_url=URL, documentos_dir=pathlib.Path(os.environ.get("DOCUMENTOS_DIR", "/tmp/caixa-docs-tela")))
uvicorn.run(criar_app(cfg, extrator=Leitor()), host="127.0.0.1", port=8777, log_level="warning")
