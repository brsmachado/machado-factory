# 04 — API REST

Base: `https://<dominio>/api/v1`. Tudo em JSON, UTF-8.

## 1. Convenções

**Dinheiro** trafega como **string decimal** com duas casas: `"9336.00"`. Nunca
número JSON — `9336.00` vira `9336` e `0.1+0.2` vira `0.30000000000000004`. O
cliente converte para `Decimal`/`BigDecimal`, nunca para `float`.

**Datas de negócio** em `YYYY-MM-DD`, sem hora. **Timestamps** de auditoria em
ISO-8601 com fuso: `2026-10-19T16:35:48-03:00`.

**Percentuais** como fração decimal em string: `"0.041667"` para 4,1667%. A
formatação (`4,17%`) é responsabilidade da tela.

**Autenticação:** `Authorization: Bearer <token>`. Token de sessão para a tela,
token de serviço para o robô — com papel `operador`, nunca `admin`.

**Idempotência:** todo `POST` que cria dinheiro aceita o header
`Idempotency-Key: <uuid>`. Repetir a chamada com a mesma chave em até 24h devolve
a resposta original sem criar nada novo. Isso evita operação duplicada quando o
robô tenta de novo após timeout.

**Erros:**

```json
{
  "erro": {
    "codigo": "caixa_insuficiente",
    "mensagem": "Caixa insuficiente: você tem R$ 2.913,60 livre.",
    "detalhe": { "disponivel": "2913.60", "solicitado": "4107.84" }
  }
}
```

Códigos: `nao_autenticado` 401 · `sem_permissao` 403 · `nao_encontrado` 404 ·
`validacao` 422 · `caixa_insuficiente` 422 · `soma_duplicatas` 422 ·
`conflito` 409 · `erro_interno` 500.

---

## 2. Resumo e painéis

### `GET /resumo`

Alimenta os cartões do topo da tela.

```json
{
  "caixa": "111810.32",
  "aplicado": "42032.64",
  "capital": "153842.96",
  "a_receber": "43843.56",
  "lucro_realizado": "3842.96",
  "lucro_a_receber": "1810.92",
  "duplicatas_abertas": 4,
  "operacoes_abertas": 4,
  "rentabilidade": {
    "retorno": "0.037402",
    "prazo_medio_dias": "33.6",
    "taxa_mes": "0.032600",
    "taxa_ano": "0.478000",
    "lucro_mes_reais": "4965.73",
    "ocupacao": "0.273000",
    "rendimento_caixa_inteiro": "0.008900"
  }
}
```

### `GET /resultado-mensal?de=2026-08&ate=2026-12`

Alimenta o painel "Resultado por mês". `de`/`ate` opcionais — o padrão cobre do
primeiro movimento até o último vencimento.

```json
{
  "meses": [
    {
      "mes": "2026-10",
      "dias": 31,
      "estado": "fechado",
      "lucro": "2108.57",
      "aplicado_medio": "56379.73",
      "capital_medio": "150000.00",
      "parado_medio": "93620.27",
      "ocupacao": "0.376000",
      "taxa_mes": "0.036200",
      "taxa_sobre_total": "0.014100",
      "custo_do_parado": "3501.35"
    }
  ]
}
```

`estado`: `fechado` · `em_curso` · `projecao`.

### `GET /agenda?dias=45`

```json
{
  "duplicatas": [
    {
      "id": 12,
      "operacao_id": 5,
      "fornecedor": "Brislu Plásticos",
      "numero_pedido": "PC 03295-5/26",
      "sequencia": 2, "de": 2,
      "valor": "12975.90",
      "vencimento": "2026-10-26",
      "atrasada": false
    }
  ],
  "total": "43843.56"
}
```

---

## 3. Operações

### `GET /operacoes`

Filtros: `estado` (`em_aberto|parcial|encerrada|atrasada|rascunho|estornada`),
`fornecedor_id`, `q` (busca em pedido, NF e observações), `de`, `ate`,
`pagina`, `por_pagina` (padrão 50).

```json
{
  "itens": [
    {
      "id": 7,
      "fornecedor": { "id": 2, "nome": "SB Indústria e Comércio de Papel" },
      "numero_pedido": "PC 03273-2/26",
      "numero_nf": "12893",
      "data_pedido": "2026-10-16",
      "data_pagamento": "2026-10-19",
      "valor_pago": "4107.84",
      "valor_cheio": "4279.00",
      "lucro": "171.16",
      "retorno": "0.041667",
      "desconto": "0.040000",
      "prazo_medio_dias": "27.0",
      "taxa_mes": "0.046402",
      "lucro_mes_reais": "190.61",
      "estado": "em_aberto",
      "observacoes": "Papel acoplado mono 32×37 · 110 un",
      "duplicatas": [
        { "id": 11, "sequencia": 1, "valor": "4279.00",
          "vencimento": "2026-11-15", "recebida_em": null }
      ],
      "documentos": [
        { "id": 20, "tipo": "pedido_compra",
          "nome_arquivo": "2026-10-16_PC-03273-2-26_pedido-compra.png" }
      ]
    }
  ],
  "total": 7, "pagina": 1
}
```

### `POST /operacoes`

```json
{
  "fornecedor_id": 2,
  "numero_pedido": "PC 03273-2/26",
  "numero_nf": "12893",
  "data_pedido": "2026-10-16",
  "data_pagamento": "2026-10-19",
  "valor_pago": "4107.84",
  "valor_cheio": "4279.00",
  "observacoes": "Papel acoplado mono 32×37 · 110 un",
  "duplicatas": [
    { "valor": "4279.00", "vencimento": "2026-11-15" }
  ],
  "documento_ids": [20, 21]
}
```

Validações, nesta ordem, parando na primeira falha:

1. fornecedor existe e está ativo
2. `valor_pago > 0`, `valor_cheio > 0`
3. `valor_cheio >= valor_pago` → `validacao`
4. pelo menos uma duplicata, todas com valor > 0 e vencimento preenchido
5. `Σ duplicatas == valor_cheio` → `soma_duplicatas`
6. cada `vencimento >= data_pagamento` e `<= data_pagamento + 365d` → `validacao`
   (ver A-02)
7. `valor_pago <= caixa_disponivel` → `caixa_insuficiente`

A sequência das duplicatas é atribuída pelo servidor, ordenando por vencimento.

`201 Created` com o objeto completo.

### `PATCH /operacoes/:id`

Campos alteráveis: todos, inclusive a lista de duplicatas (substituição
completa). Duplicata já recebida não pode ter o valor alterado — só o
vencimento, e com aviso. Na revalidação do caixa, o disponível é
`caixa + valor_pago_atual − recebido_desta_operacao` (RN-03).

### `POST /operacoes/:id/estorno`

```json
{ "motivo": "Pedido cancelado pelo fornecedor" }
```

Marca `situacao = 'estornada'`, registra em `evento`. A operação sai de todos os
cálculos. Não apaga nada. `409 conflito` se já estiver estornada.

### `DELETE /operacoes/:id`

Só funciona em `rascunho` ou em operação confirmada sem nenhum recebimento.
Caso contrário `409 conflito` com a mensagem apontando o estorno.

---

## 4. Recebimentos

### `POST /duplicatas/:id/receber`

```json
{ "data": "2026-10-26" }
```

`data` opcional; o padrão é hoje. Valida RN-04. `409` se já recebida.

### `DELETE /duplicatas/:id/receber`

Desfaz. O valor sai do caixa, a duplicata volta a aberta, o lucro realizado
diminui. Fica registrado em `evento` com ação `desfez`.

### `POST /duplicatas/receber-lote`

Para o caso comum de várias duplicatas caindo juntas:

```json
{ "itens": [ { "id": 8, "data": "2026-10-26" }, { "id": 9, "data": "2026-10-26" } ] }
```

Tudo numa transação: ou todas entram, ou nenhuma.

---

## 5. Caixa

### `GET /movimentos` · `POST /movimentos`

```json
{ "tipo": "aporte", "data": "2026-09-16", "valor": "50000.00",
  "observacoes": "Aporte para as compras da Brislu de setembro" }
```

Retirada valida RN-05 contra o caixa disponível.

### `DELETE /movimentos/:id`

Permitido só se o caixa continuar não-negativo em toda a linha do tempo depois
da remoção. Senão `422`.

---

## 6. Fornecedores

`GET /fornecedores` · `POST /fornecedores` · `PATCH /fornecedores/:id`

```json
{ "nome": "SB Indústria e Comércio de Papel", "cnpj": "26107828000137",
  "chave_pix": "sbindustria33@gmail.com", "desconto_padrao": "0.0400",
  "prazo_padrao": "30",
  "observacoes": "Lança o desconto na própria nota — conferir soma dos itens (A-01)" }
```

O campo `observacoes` do fornecedor aparece como aviso na tela de lançamento.
É onde mora a memória institucional das armadilhas.

---

## 7. Documentos

### `POST /documentos` — `multipart/form-data`

Campos: `arquivo`, `tipo`, `operacao_id` (opcional), `data_doc` (opcional).

O servidor calcula o `sha256`; se já existir, devolve `200` com o documento
existente em vez de duplicar. Renomeia conforme a convenção:

```
AAAA-MM-DD_PC-<pedido com - no lugar de / e espaço>_<tipo>.<ext>
2026-10-19_PC-03273-2-26_comprovante-pix.pdf
```

Grava em `operacoes/AAAA-MM/` relativo à raiz de documentos.

### `GET /documentos/:id/arquivo`

Devolve o binário com `Content-Disposition: inline`.

---

## 8. Exportação

### `GET /exportar/operacoes.csv`

Uma linha **por duplicata**, com os dados da operação repetidos — é o formato que
a planilha e o contador já usam. Separador `;`, decimal com vírgula, BOM UTF-8
para o Excel brasileiro abrir certo.

Colunas, nesta ordem:

```
Data compra;Fornecedor;NF/Pedido;Valor cheio;Valor pago;Lucro total;
Retorno % s/ valor pago;Desconto % s/ valor cheio;Prazo (dias);% ao mes;
Lucro por mes;Parcela;Valor parcela;Vencimento;Recebida em;Situacao;Observacoes
```

### `GET /exportar/movimentos.csv`

```
Data;Tipo;Valor;Observacoes
```

---

## 9. Endpoints do robô

Descritos em detalhe em [06-robo.md](06-robo.md).

| Método | Rota | O que faz |
|---|---|---|
| `POST` | `/robo/ingestao` | Recebe documentos, devolve rascunho de operação |
| `GET` | `/robo/rascunhos` | Fila de rascunhos aguardando conferência |
| `POST` | `/robo/rascunhos/:id/aprovar` | Confirma, opcionalmente com correções |
| `POST` | `/robo/rascunhos/:id/descartar` | Arquiva sem criar operação |
| `POST` | `/robo/conciliacao` | Roda a varredura de vencimentos (cron) |
| `GET` | `/robo/alertas` | Alertas abertos |
| `POST` | `/robo/alertas/:id/baixar` | Marca como lido |

---

## 10. Saúde

### `GET /saude`

```json
{ "ok": true, "versao": "1.0.3", "banco": "ok",
  "integridade": { "identidade_caixa": "ok" } }
```

`integridade.identidade_caixa` roda a asserção
`caixa + aplicado == aportes − retiradas + lucro_realizado`. Se falhar, o sistema
está com os números errados e isso precisa aparecer no monitoramento, não só nos
testes.
