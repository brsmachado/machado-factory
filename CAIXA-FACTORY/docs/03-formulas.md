# 03 — Fórmulas

Todas as fórmulas deste documento estão conferidas contra os dados reais de
19/10/2026 ([seed/estado-2026-10-19.json](seed/estado-2026-10-19.json)). Use os
exemplos como casos de teste.

Notação: `pago` = `operacao.valor_pago`, `face` = `operacao.valor_cheio`.

---

## 1. Por operação

```
face      = Σ duplicata.valor
recebido  = Σ duplicata.valor  onde recebida_em is not null
aberto    = face − recebido
lucro     = face − pago

retorno   = lucro / pago          ← a taxa do investidor (sempre esta na tela)
desconto  = lucro / face          ← a taxa do fornecedor (secundária)
```

### Prazo médio

Ponderado pelo valor de cada duplicata. A data de fim é o **recebimento real**
quando existe, senão o vencimento previsto:

```
fim(d)      = d.recebida_em ?? d.vencimento
dias(d)     = max(1, fim(d) − operacao.data_pagamento)      em dias corridos
prazo_medio = Σ (d.valor × dias(d)) / face
```

### Taxas equivalentes

Juros compostos, base 30 dias para o mês e 365 para o ano:

```
taxa_mes = (1 + retorno)^(30  / prazo_medio) − 1
taxa_ano = (1 + retorno)^(365 / prazo_medio) − 1
lucro_mes_em_reais = pago × taxa_mes
```

### Exemplo conferido — PC 03282-2/26 (Brislu)

```
pago  = 63.321,60
duplicatas: 32.640,00 em 26/09  e  32.640,00 em 06/10
data_pagamento = 27/08/2026

face     = 65.280,00
lucro    = 65.280,00 − 63.321,60 = 1.958,40
retorno  = 1.958,40 / 63.321,60  = 0,030928  → 3,09%
desconto = 1.958,40 / 65.280,00  = 0,030000  → 3,00%

dias(1)  = 26/09 − 27/08 = 30
dias(2)  = 06/10 − 27/08 = 40
prazo    = (32.640×30 + 32.640×40) / 65.280 = 35,0 dias

taxa_mes = 1,030928^(30/35) − 1 = 0,026452 → 2,65%
taxa_ano = 1,030928^(365/35) − 1 = 0,3738  → 37,4%
lucro_mes = 63.321,60 × 0,026452 = 1.674,96
```

### Exemplo conferido — PC 03273-2/26 (SB), prazo curto

```
pago = 4.107,84 · duplicata única 4.279,00 em 15/11 · pagamento 19/10

lucro    = 171,16
retorno  = 171,16 / 4.107,84 = 0,041667 → 4,17%
desconto = 171,16 / 4.279,00 = 0,040000 → 4,00%
prazo    = 15/11 − 19/10 = 27 dias
taxa_mes = 1,041667^(30/27) − 1 = 0,046402 → 4,64%
```

Repare: mesmo desconto de 4% da operação anterior da SB, mas 27 dias em vez de
30 — e a taxa mensal sobe de 4,17% para 4,64%. **Prazo curto vale tanto quanto
desconto alto**, e o sistema precisa deixar isso visível.

---

## 2. Posição do caixa

```
aportes    = Σ movimento_caixa.valor  onde tipo = 'aporte'
retiradas  = Σ movimento_caixa.valor  onde tipo = 'retirada'

caixa      = aportes − retiradas − Σ pago(todas) + Σ recebido(todas)
aplicado   = Σ ( pago × aberto / face )        ← capital ainda na rua
capital    = caixa + aplicado
a_receber  = Σ aberto
```

A identidade que serve de **teste de regressão**:

```
caixa + aplicado  ==  aportes − retiradas + lucro_realizado
```

Se esses dois lados divergirem em qualquer momento, há bug. Rode como asserção
em teste automatizado.

### Lucro realizado e a receber

O custo de cada operação é recuperado na mesma proporção do que já voltou:

```
custo_recuperado = pago × recebido / face
lucro_realizado  = Σ ( recebido − custo_recuperado )
lucro_a_receber  = Σ ( aberto   − pago × aberto / face )
```

### Exemplo conferido — posição em 19/10/2026

```
aportes      = 150.000,00   (100.000 em 28/08 + 50.000 em 16/09)
retiradas    = 0
Σ pago       = 151.194,24
Σ recebido   = 113.004,56   (7 duplicatas)

caixa        = 150.000 − 0 − 151.194,24 + 113.004,56 = 111.810,32  ✓
aplicado     =  43.843,56 − 1.810,92 = 42.032,64
a_receber    =  43.843,56   (4 duplicatas em aberto)
lucro_realizado =  3.842,96
lucro_a_receber =  1.810,92

conferência: 111.810,32 + 42.032,64 = 153.842,96
             150.000,00 + 3.842,96  = 153.842,96   ✓
```

---

## 3. Rentabilidade da carteira

Média ponderada pelo capital de cada operação:

```
pago_total   = Σ pago
lucro_total  = Σ lucro
prazo_medio_carteira = Σ ( pago × prazo_medio(op) ) / pago_total

retorno_carteira = lucro_total / pago_total
taxa_mes         = (1 + retorno_carteira)^(30 / prazo_medio_carteira) − 1
lucro_mes_reais  = Σ ( pago(op) × taxa_mes(op) )     ← soma das operações, não da média
```

### Ocupação e rendimento efetivo

```
ocupacao = aplicado / capital
rendimento_do_caixa_inteiro = taxa_mes × ocupacao
```

Esta é a métrica mais importante do sistema. Em 19/10/2026 as operações rendiam
**3,26% ao mês**, mas com apenas 27,3% do capital girando, o caixa inteiro rendia
**0,89% ao mês** — abaixo do CDI. A carteira estava ótima e o resultado, ruim.

---

## 4. Agenda de retornos

```
agenda = todas as duplicatas com recebida_em is null,
         ordenadas por vencimento asc

atrasada(d) = d.vencimento < hoje
```

---

## 5. Resultado por mês (competência)

A parte mais sutil do sistema, e a que responde "quanto o dinheiro parado me
custou neste mês".

### Princípio

O lucro de uma operação não pertence ao mês da compra: pertence aos dias em que o
dinheiro esteve na rua. Uma compra paga em 16/09 com duplicata em 26/10 tem 40
dias de duração — 14 caem em setembro e 26 em outubro, e o lucro se divide na
mesma proporção.

### Algoritmo

Para o mês `M`, com `ini` = primeiro dia, `fim` = último dia, `nDias` = dias do mês:

```
lucro_mes   = 0
capital_dia = 0

para cada operação confirmada:
    face  = Σ duplicatas
    lucro = face − pago
    para cada duplicata d:
        fim_d = d.recebida_em ?? d.vencimento
        n     = max(1, fim_d − data_pagamento)              # duração em dias

        # janela de apropriação: (data_pagamento, fim_d]
        a = max(data_pagamento + 1 dia, ini)
        b = min(fim_d, fim)
        overlap = (b − a) + 1
        se overlap <= 0: continua
        overlap = min(overlap, n)

        lucro_mes   += lucro × (d.valor / face) × (overlap / n)
        capital_dia += pago  × (d.valor / face) × overlap
```

Capital total médio no mês, dia a dia:

```
capital_total_dia = 0
para cada dia do mês:
    saldo = Σ movimentos com data <= dia   (aporte +, retirada −)
    capital_total_dia += saldo
```

Resultados:

```
aplicado_medio = capital_dia / nDias
capital_medio  = capital_total_dia / nDias
parado         = max(0, capital_medio − aplicado_medio)
ocupacao       = aplicado_medio / capital_medio

taxa_do_mes         = (lucro_mes / aplicado_medio) × (30 / nDias)
taxa_sobre_o_total  = (lucro_mes / capital_medio)  × (30 / nDias)

custo_do_parado = parado × (lucro_mes / aplicado_medio)
```

`custo_do_parado` é o número que o usuário pediu: **quanto o dinheiro parado
deixou de render naquele mês**, na mesma taxa que o dinheiro aplicado rendeu.
Não é uma perda contábil — é custo de oportunidade, e deve ser rotulado como
"deixou de ganhar", nunca como "prejuízo".

### Exemplos conferidos

| Mês | Lucro | Aplicado médio | Parado médio | Deixou de ganhar |
|---|---|---|---|---|
| Ago/2026 | 249,90 | 8.936,52 | 3.966,71 | 110,92 |
| Set/2026 | 3.200,32 | 103.260,88 | 21.739,12 | 673,75 |
| Out/2026 | 2.108,57 | 56.379,73 | 93.620,27 | 3.501,35 |
| Nov/2026 | 95,09 | 2.053,92 | 147.946,08 | 6.849,36 |

Agosto parece pequeno porque a operação começou em 27/08: só 4 dias do mês
tiveram dinheiro na rua.

### Meses em aberto

Um mês cujo último dia ainda não passou mistura realizado com contratado. A tela
precisa marcar: `mês em curso` quando `fim >= hoje > ini`, e `projeção` quando
`ini > hoje`. Os números mudam a cada compra nova.

---

## 6. Casos de borda

| Caso | Comportamento esperado |
|---|---|
| `face == pago` | lucro 0, retorno 0, taxas 0. Permitido, com aviso na tela. |
| `prazo_medio == 0` | Impossível: `dias` tem piso de 1. |
| Duplicata recebida no mesmo dia do pagamento | `dias = 1`. Taxa mensal fica enorme — correto, mas a tela deve mostrar "menos de 1 dia" em vez de "1200% a.m.". |
| Operação sem duplicata | Só em `rascunho`. Views e totais ignoram. |
| Mês sem nenhuma operação ativa | `lucro_mes = 0`, `aplicado_medio = 0`, `taxa = 0`. Dividir por zero → retorne 0, não `NaN`. |
| Capital total zero (antes do 1º aporte) | `ocupacao = 0`. |
| Recebimento desfeito | O valor sai do caixa, a duplicata volta a `aberta`, o lucro realizado diminui. Tudo recalculado, nada guardado. |
| Operação estornada | Sai de todos os cálculos como se não existisse, mas permanece na tabela e no log. |
| Duas operações com o mesmo `numero_pedido` | Bloqueado por unique `(fornecedor_id, numero_pedido)`. Pedidos diferentes do mesmo número base têm sufixo: `03273-0/26`, `03273-1/26`, `03273-2/26`. |
