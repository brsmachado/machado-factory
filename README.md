# MACHADO-FACTORY

Sistemas da Machado Embalagens.

| Pasta | O que é |
|---|---|
| [CAIXA-FACTORY/](CAIXA-FACTORY/) | Especificação técnica do Caixa Factory (docs em `docs/`, página única em `caixa-factory-docs.html`) |
| [CAIXA-FACTORY/banco/](CAIXA-FACTORY/banco/) | Banco PostgreSQL: migrações, carga inicial e testes |
| [CAIXA-FACTORY/api/](CAIXA-FACTORY/api/) | API REST (FastAPI): lançamentos, recebimentos, caixa, documentos, CSV |
| [CAIXA-MACHADO/](CAIXA-MACHADO/) | Sistema em uso hoje (`sistema/caixa-machado.html`) e registros em CSV |

Para regenerar a página da documentação depois de editar os `.md`:

```bash
pip install markdown
python3 CAIXA-FACTORY/docs/gerar-pagina.py
```

Os comprovantes de PIX e pedidos (`CAIXA-MACHADO/operacoes/`) não vão para o git.
