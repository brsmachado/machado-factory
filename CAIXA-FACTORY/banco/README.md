# Banco de dados — Caixa Factory

PostgreSQL 15+ (testado no 16). Implementa [docs/02-modelo-dados.md](../docs/02-modelo-dados.md)
e as fórmulas de [docs/03-formulas.md](../docs/03-formulas.md).

```
banco/
  migracoes/
    001_tabelas.sql            tabelas, constraints, parâmetros
    002_integridade.sql        RN-01, RN-03, RN-04, RN-05, RN-06, ciclo de vida
    003_auditoria.sql          log automático em evento (só cresce)
    004_views.sql              v_operacao, v_caixa, v_carteira, v_agenda
    005_resultado_mensal.sql   resultado_mes() e resultado_mensal() — competência
    006_api.sql                sessões de login, Idempotency-Key, sequência deferrable
    007_robo.sql               rascunhos do robô, caixa diário, alertas
  aplicar.sh                   aplica as migrações que faltam
  carregar_seed.py             carga inicial a partir de docs/seed/*.json
  testes/
    testes.sql                 conferência + todas as regras
    rodar.sh                   banco descartável → migra → carrega → testa → apaga
```

## Uso

Criar o banco na VPS: [docs/08-deploy.md §3](../docs/08-deploy.md). Depois:

```bash
export DATABASE_URL=postgresql://caixa:SENHA@localhost/caixa_factory
./aplicar.sh
python3 carregar_seed.py | psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1
```

A carga só roda em banco vazio, é uma transação só e termina conferindo
`v_caixa` contra o bloco `conferencia` do seed — um centavo de diferença desfaz tudo.

`aplicar.sh` pode rodar quantas vezes quiser: só aplica o que falta. Migração
já aplicada **não se edita** (o script recusa): mudança nova é arquivo novo,
`006_...sql`.

Testes (precisa de um usuário que possa criar banco):

```bash
PGHOST=localhost PGUSER=postgres ./testes/rodar.sh
# todos os testes passaram
```

## Consultas que a API vai usar

| Endpoint (docs/04-api.md) | SQL |
|---|---|
| `GET /resumo` | `select * from caixa.v_caixa, caixa.v_carteira` |
| `GET /resultado-mensal` | `select * from caixa.resultado_mensal(:de, :ate)` |
| `GET /agenda?dias=45` | `select * from caixa.v_agenda where vencimento <= current_date + :dias` |
| operações | `select * from caixa.v_operacao` |
| caixa livre para RN-03 | `select caixa.caixa_disponivel()` |

Em toda transação que grava: `set local caixa.usuario_id = '<id>'`, para o log
saber quem agiu.

## O que o banco garante sozinho

Mesmo que a aplicação tenha bug, estas regras não passam:

| Regra | Como |
|---|---|
| RN-01 soma das duplicatas = valor cheio | constraint trigger deferred, na duplicata **e** na operação (pega também confirmada sem duplicata, mudança de `valor_cheio` e confirmação de rascunho incompleto) |
| RN-02 pago ≤ cheio | `check` |
| RN-03 não se compra sem caixa | caixa nunca fica negativo depois de compra ou edição de compra; a mensagem diz quanto há livre |
| RN-04 recebimento ≥ pagamento | trigger na duplicata e na mudança de `data_pagamento` |
| RN-05 retirada ≤ caixa | mesmo teste do caixa, para retirada e para aporte apagado |
| RN-06 o que foi recebido não se apaga | trigger na operação e na duplicata |
| A-02 ano absurdo no vencimento | `check` 2026–2099 (a checagem fina é da aplicação) |
| Ciclo de vida | confirmada não volta a rascunho; estornada fica congelada; estorno exige data e motivo |
| Auditoria | todo insert/update/delete vira `evento` com antes/depois; `evento` não aceita update, delete nem truncate; `senha_hash` nunca vai para o log |

Desfazer recebimento **não** é barrado, mesmo que o caixa fique negativo: é
correção de lançamento, e tem que ser possível. A tela mostra o buraco.

## Diferenças em relação ao texto da especificação

- `v_operacao.recebido` já sai sem nulo; a coluna auxiliar `recebido_` não existe.
- O log grava a ação em português (`criou`, `alterou`, `recebeu`, `desfez`,
  `confirmou`, `estornou`, `excluiu`) em vez de `insert`/`update`/`delete`.
- Auditoria também em `fornecedor`, `documento` e `usuario`.
- Novas views `v_carteira` (rentabilidade de `GET /resumo`) e `v_agenda`.

## Conferido nos dados reais de 19/10/2026

Todos os números de conferência de 03-formulas e 07-migracao batem no centavo:
posição do caixa, identidade, os dois exemplos por operação e os quatro meses
de resultado (ago–nov).

**Atenção:** o JSON de exemplo de `GET /resumo` em `docs/04-api.md` traz
`retorno 0.037402` e `prazo_medio_dias 33.6`, que não saem da fórmula de
03-formulas §3 nem de nenhuma variação dela. A fórmula dá `0.037395` e
`34.29`. O banco segue a fórmula; os números que vão para a tela
(`taxa_mes 3,26%`, `lucro_mes R$ 4.965,73`, `ocupação 27,3%`,
`rendimento do caixa inteiro 0,89%`) batem com o exemplo.
