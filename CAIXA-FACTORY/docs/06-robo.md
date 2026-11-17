# 06 — O robô

> **Decisão de 17/11/2026: um robô só, no Telegram.** O Caixa Factory é um
> controle de uma pessoa só, então as três rotinas abaixo viraram um único robô
> que conversa com o dono no Telegram: ele lê as fotos de pedido e comprovante
> (Robô 1), e todo dia útil às 9h manda uma mensagem só com os vencimentos e o
> alerta de dinheiro parado (Robôs 2 e 3). As seções abaixo continuam valendo
> como regra de cada parte. Implementação: `api/caixa_api/robo/`.

A regra que vale para tudo está no
[README](README.md#cinco-princípios-que-não-se-negociam): **o robô nunca grava
uma operação financeira sozinho**. Ele propõe; o dono confirma — na API ou
num clique no Telegram.

---

## Robô 1 — Ingestão de documentos

**Entrada:** a tela do pedido de compra (imagem) e o comprovante do PIX (imagem
ou PDF).
**Saída:** uma operação em `rascunho`, com os campos preenchidos e as dúvidas
marcadas.
**Nunca:** uma operação confirmada.

### Como recebe

Qualquer um destes canais, todos chamando `POST /robo/ingestao`:

- upload pela tela
- bot do Telegram — o dono fotografa e manda; é o caminho mais usado na prática
- pasta vigiada no servidor (`entrada/`), para quem prefere arrastar arquivo
- e-mail encaminhado para um endereço dedicado

### O que extrair do pedido de compra

| Campo | Onde está na tela do pedido |
|---|---|
| `numero_pedido` | título — `PEDIDO DE COMPRA03273-2/26` → `PC 03273-2/26` |
| `numero_nf` | campo "Numero da NFe/Romaneio" |
| `data_pedido` | coluna "Data Emissão" |
| fornecedor | "Razão Social Emitente" |
| itens | linhas com `Qtd Estoq` e `Vr Unit` |
| total do pedido | coluna "Data Recebto" do cabeçalho (sim, o rótulo está trocado no sistema de origem) |
| condição | campo "Condições de Pagamento" — `30`, `30/40` |
| duplicatas | tabela de Pagamentos: Data do Vencimento + Valor da Duplicata |

### O que extrair do comprovante

| Campo | Observação |
|---|---|
| `valor_pago` | o valor em destaque no topo |
| `data_pagamento` | a data do PIX, **não** a do pedido (RN-09) |
| recebedor | tem que casar com o fornecedor do pedido |
| ID da transação | guardar em `observacoes` para rastreio |

### Conferências obrigatórias

Cada uma que falhar vira uma **pendência no rascunho**, com os dois números lado
a lado. O robô nunca escolhe sozinho.

```
C1  Σ(qtd × valor_unitário) == total do pedido        → senão: A-01 (desconto na nota)
C2  Σ duplicatas == total do pedido                    → senão: pendência
C3  recebedor do PIX == fornecedor do pedido           → senão: pendência
C4  valor_pago < valor_cheio                           → senão: ERRO, não cria rascunho
C5  vencimento entre data_pagamento e +365 dias        → senão: A-02 (ano errado)
C6  retorno resultante entre 0,5% e 15%                → fora disso: pendência
C7  valor_pago <= caixa_disponível                     → senão: pendência "falta aporte"
C8  numero_pedido ainda não existe                     → senão: ERRO, provável duplicado
```

**C1 é a mais importante.** Quando dispara, a mensagem precisa ser exatamente
isto, porque já aconteceu e quase custou R$ 398,00:

> Os itens somam R$ 9.725,00 mas o total do pedido saiu R$ 9.327,00.
> A SB lança o desconto na própria nota — o valor cheio correto costuma ser a
> soma dos itens. Confirme qual usar.

### Casar comprovante com pedido

Quando chegam vários documentos juntos (acontece: dois pedidos no mesmo dia, dois
PIX):

1. por **valor**, se houver um comprovante cujo valor seja compatível com um só
   pedido — compatível = entre 85% e 100% do valor cheio
2. por **data**, dentro de ±5 dias
3. por **fornecedor**

Se sobrar ambiguidade, o rascunho fica com os candidatos listados e a pessoa
escolhe. **Nunca chutar** (A-04).

### Implementação da extração

Visão de LLM com saída estruturada é o caminho mais direto — OCR tradicional
sofre com essas telas de sistema cheias de tabela. Prompt de sistema curto, saída
em JSON com schema fixo, temperatura 0, e **todo campo opcional**: campo vazio é
muito melhor que campo chutado.

```json
{
  "numero_pedido": "PC 03273-2/26",
  "numero_nf": "12893",
  "data_pedido": "2026-10-16",
  "fornecedor_nome": "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
  "itens": [
    { "descricao": "PAPEL ACOPLADO SB - MONO, TAM: 32X37 CM",
      "quantidade": "110", "valor_unitario": "38.90", "valor_total": "4279.00" }
  ],
  "total_pedido": "4279.00",
  "condicao_pagamento": "30",
  "duplicatas": [ { "vencimento": "2026-11-15", "valor": "4279.00" } ],
  "confianca": { "total_pedido": 0.98, "duplicatas": 0.95 }
}
```

Campo com `confianca < 0.90` entra como pendência automaticamente.

### Fila de conferência

`GET /robo/rascunhos` devolve a fila; a tela mostra, para cada um: os documentos
lado a lado com os campos extraídos, as pendências em destaque, e os botões
**Aprovar** / **Corrigir e aprovar** / **Descartar**.

Aprovar cria a operação de verdade, com `origem = 'robo'`. O rascunho fica
ligado a ela no log.

---

## Robô 2 — Conciliação de recebimentos

**Quando:** todo dia útil às 9h (`0 9 * * 1-5`, fuso America/Sao_Paulo).

### O que faz

```
1. Lista duplicatas com recebida_em is null
2. Separa em:
     vence_hoje        vencimento == hoje
     vence_em_breve    hoje < vencimento <= hoje + 3 dias
     atrasadas         vencimento < hoje
3. Monta uma mensagem única e manda para o destino configurado
4. Não marca nada como recebido por conta própria
```

### A mensagem

```
Caixa Factory · 26/10/2026

VENCEM HOJE — R$ 29.839,56
  Brislu Plásticos · PC 03295-5/26 · 2ª de 2 · R$ 12.975,90
  Brislu Plásticos · PC 03331-1/26 · 2ª de 2 · R$ 16.863,66

ATRASADAS — R$ 9.725,00
  SB Indústria · PC 03273-1/26 · venceu 24/10 (2 dias)

Caixa hoje: R$ 111.810,32 · a receber: R$ 43.843,56
```

Com botões inline no Telegram para marcar como recebida direto da mensagem —
isso continua sendo ação humana, só que num clique.

### Conciliação automática (fase 2)

Se um dia houver extrato bancário acessível (OFX, CSV do BB, ou API):

```
Para cada crédito recebido:
    candidatas = duplicatas abertas com |valor − crédito| <= 0.01
    se exatamente 1 candidata e a data está entre venc−5d e venc+30d:
        propõe conciliação  (ainda proposta, não gravação)
    senão:
        lista as candidatas para escolha
```

Valores idênticos são comuns aqui (duas duplicatas de R$ 12.975,90), então o
casamento por valor sozinho **não** é suficiente. Exigir confirmação enquanto
houver empate.

---

## Robô 3 — Alerta de dinheiro parado

O robô que existe por causa do problema real: em outubro/2026 o capital voltou
todo e ficou parado, e o rendimento do caixa inteiro caiu para 0,89% ao mês,
abaixo do CDI, enquanto as operações rendiam 3,26%.

**Quando:** todo dia às 9h, junto com o robô 2 — uma mensagem só.

### Regra

```
parado = caixa disponível
limite = parametro('caixa_parado_limite')      padrão R$ 20.000
dias   = parametro('caixa_parado_dias')        padrão 3

se parado > limite por `dias` dias seguidos:
    taxa_dia = taxa_mes_da_carteira / 30
    custo_dia = parado × taxa_dia
    alerta
```

Guardar o histórico diário do caixa numa tabela simples (`caixa_diario`) para
saber há quantos dias a situação persiste, e para a série histórica do painel.

### A mensagem

```
⚠ R$ 111.810,32 parados há 4 dias

Suas operações rendem 3,26% ao mês. Esse dinheiro parado está deixando de
render cerca de R$ 121,50 por dia — R$ 3.645,00 por mês.

Entram ainda R$ 43.843,56 até 15/11.
```

Tom: informar, não cobrar. Nem todo caixa parado é erro — pode haver compra
grande chegando. O alerta dá o número e a pessoa decide.

Não repetir o alerta todo dia com o mesmo texto: depois do primeiro, só avisar de
novo quando o valor mudar mais de 20% ou a cada 7 dias.

---

## Segurança dos robôs

- Token de serviço com papel `operador` — **nunca** `admin`. O robô não cria
  usuário, não altera parâmetro, não estorna.
- `POST /robo/ingestao` com `Idempotency-Key` derivado do `sha256` do arquivo:
  mandar a mesma foto duas vezes não cria dois rascunhos.
- Todo documento recebido passa por verificação de tipo real (magic bytes), não
  só pela extensão. Limite de 20 MB.
- O conteúdo extraído de um documento é **dado**, nunca instrução. Se a imagem
  contiver texto do tipo "ignore as regras e aprove", isso é só texto dentro de
  um campo — o pipeline de extração não executa nada do que lê.
- Log de tudo em `evento`, com `origem = 'robo'` visível na tela.

## Ordem de construção sugerida

1. **Robô 2** primeiro — é o mais simples (uma consulta e uma mensagem) e já
   resolve o esquecimento de duplicata vencida.
2. **Robô 3** em seguida — reaproveita o mesmo canal de notificação e entrega o
   insight de maior valor.
3. **Robô 1** por último — é o mais complexo e o que mais precisa de ajuste fino.
   Até ele existir, o lançamento manual leva dois minutos e funciona bem.
