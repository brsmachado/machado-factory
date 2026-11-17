# API — Caixa Factory

FastAPI + psycopg 3, SQL direto sobre as views do banco (sem ORM). Implementa
[docs/04-api.md](../docs/04-api.md) inteira, mais o robô de
[docs/06-robo.md](../docs/06-robo.md). Base: `/api/v1`.
Documentação interativa em `/api/v1/docs`. A tela (`CAIXA-FACTORY/web/`) é
servida pela própria API em `/`, no mesmo endereço, com CSP que só aceita script
do próprio servidor.

```
api/
  main.py                 uvicorn main:app (docs/08-deploy.md §4)
  caixa_api/
    app.py                monta as rotas
    config.py             lê o .env
    db.py                 pool, transação, quem agiu, lock de dinheiro
    auth.py               login, sessões, papéis, token do robô
    erros.py              formato único de erro e tradução das regras do banco
    fmt.py                dinheiro e taxa como string, nunca float
    idempotencia.py       Idempotency-Key
    escrita.py            transação + idempotência + arquivos num lugar só
    operacoes.py          validações do lançamento, edição, estorno
    documentos.py         nome dos arquivos, tipo real, renomear junto com a transação
    cli.py                criar usuário, trocar senha, criar usuário do robô
    robo/                 o robô (um só, no Telegram)
      extracao.py         leitura de pedido e comprovante com o Claude (saída estruturada)
      rascunhos.py        casar pedido com PIX (A-04), conferências C1..C8, corrigir, aprovar
      aviso.py            aviso das 9h: vencimentos + dinheiro parado (sem repetir todo dia)
      telegram.py         o bot: fotos, botões, comandos; só fala com o seu chat
      servico.py          o que o robô faz, usado pela API e pelo Telegram
    rotas/                um arquivo por seção da especificação
  testes/                 pytest contra PostgreSQL de verdade
```

## Rodar

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql://caixa:SENHA@localhost/caixa_factory
export DOCUMENTOS_DIR=/opt/caixa-factory/documentos ROBO_TOKEN=$(openssl rand -hex 32)
../banco/aplicar.sh                                    # inclui a 006 (sessões e idempotência)
venv/bin/python -m caixa_api.cli criar-usuario --nome "Bruno" --email voce@exemplo --papel admin
venv/bin/python -m caixa_api.cli criar-robo
venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Na VPS, `/opt/caixa-factory/app` é esta pasta `api/` (o serviço systemd de
08-deploy já chama `uvicorn main:app` nela).

## Testes

```bash
venv/bin/pip install -r requirements-dev.txt
PGHOST=localhost PGUSER=postgres venv/bin/python -m pytest testes
```

Cria um banco-modelo com as migrações, a carga real de 19/10/2026 e quatro
usuários; cada teste roda numa cópia nova dele. 77 testes: os números de
conferência pela API, cada validação na ordem da especificação, idempotência,
recebimento em lote (tudo ou nada), documentos (nome, tipo real, duplicado,
renomear e desfazer), CSV contra a planilha atual, login e permissões, e o
robô com os casos reais (A-01 da SB, A-02, A-04 das duas compras da Brislu, o
aviso de 26/10) usando um leitor e um Telegram falsos — sem rede.

## Papéis

| Quem | Pode |
|---|---|
| `leitura` | só GET |
| `operador` | lançar, editar, receber, estornar, movimentar caixa, fornecedores, documentos |
| `admin` | o mesmo que operador (usuários e parâmetros são pela linha de comando, por ora) |
| robô (`ROBO_TOKEN`) | ler, mandar documentos (`/robo/ingestao`) e disparar o aviso (`/robo/conciliacao`). Não aprova rascunho, não grava operação, não recebe, não estorna |

Login: `POST /api/v1/auth/entrar {"email","senha"}` devolve um token Bearer
(12 h, `SESSAO_HORAS`). O banco guarda só o sha256 do token. Senha com scrypt.

## Decisões e diferenças em relação à especificação

- **RN-03 na edição.** A especificação diz que o disponível é
  `caixa + valor_pago_atual − recebido_desta_operacao`. O que a operação já
  recebeu continua no caixa depois da edição, então subtrair de novo bloqueia
  edições que são possíveis. A API usa `caixa + valor_pago_atual`, que é
  exatamente o que o banco confere (caixa ≥ 0 depois da mudança). Há teste
  mostrando o limite exato.
- **`DELETE /operacoes/:id` é lógico**: marca `estornada` com motivo
  "Excluída" (princípio 3: nada se apaga). Só funciona sem recebimento.
- **`DELETE /movimentos/:id`** olha a linha do tempo inteira: um aporte só sai
  se, sem ele, o caixa não ficar negativo em nenhum dia a partir da data dele.
  Por isso os dois aportes reais não podem ser apagados (o dinheiro deles já
  foi usado). Tirar uma retirada sempre pode.
- **Recebimento no futuro é recusado** (lança quando o dinheiro entrar).
- **Documento enviado sem operação** recebe `SEM-PEDIDO` no nome e é renomeado
  para a convenção quando for vinculado. Se a transação falhar, o arquivo fica
  como estava.
- **CSV de operações:** igual à planilha atual coluna por coluna, menos
  "Lucro por mes" das duas compras da Brislu de 16/09 (planilha: 1.208,25 e
  929,68; fórmula: 1.208,03 e 929,53). Nenhuma variação da fórmula reproduz o
  número da planilha; vale a fórmula.
- `GET /operacoes` sem filtro mostra só as confirmadas; `estado=rascunho` e
  `estado=estornada` mostram as outras. `atrasada` é filtro pela flag (pode
  somar com `parcial`).

## O robô

Um só, no Telegram (decisão de 17/11/2026 — controle de uma pessoa só):

1. Você manda a foto do pedido e a do comprovante, em qualquer ordem. O Claude
   (`claude-opus-5-5`, saída estruturada, todo campo pode vir nulo) transcreve;
   o robô casa as duas metades por valor, depois data, depois fornecedor, e
   nunca chuta: se ficar na dúvida, oferece o botão "Juntar".
2. Roda as conferências C1..C8 e responde com o rascunho, o lucro e as
   pendências. No caso da SB (A-01) oferece os dois botões: "Usar itens" e
   "Usar total".
3. **Aprovar** é clique seu e passa por todas as validações do lançamento
   manual. A operação fica com `origem = 'robo'`, e o log registra você como
   quem aprovou.
4. Dias úteis às 9h: o que vence hoje e o que está atrasado, com botão "Recebi"
   em cada duplicata, mais o alerta de dinheiro parado (limite e dias em
   `parametro`; repete só a cada 7 dias ou se o valor mudar mais de 20%).

A mesma foto duas vezes não é lida de novo (sha256). Mensagens de outros chats
são ignoradas. Falha de leitura (rede, recusa) vira mensagem para você e não
grava nada. Recusa do classificador de segurança: a API tenta de novo em outro
modelo (`fallbacks: "default"`).

Rodar: `python -m caixa_api.robo telegram` (serviço) e `python -m caixa_api.robo
aviso` (cron). Instalação em [docs/08-deploy.md §7](../docs/08-deploy.md).
Variáveis: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_USUARIO_EMAIL`,
`ANTHROPIC_API_KEY`.

## Falta

- Limite de tentativas de login: fica no Nginx (`limit_req`, 10 por minuto, já no `deploy/instalar.sh`).
- Testar a leitura com fotos reais: os testes usam um leitor falso; a primeira
  semana de uso real é que calibra o prompt (ver docs/06-robo.md).
