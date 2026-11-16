# 01 — Domínio, regras de negócio e armadilhas

## 1. O negócio em três parágrafos

A Machado Embalagens compra de fornecedores a prazo — tipicamente duplicatas em
30 e 40 dias. Quando o fornecedor oferece desconto para pagamento à vista, quem
paga é o **investidor** (Bruno), com dinheiro próprio, direto ao fornecedor via
PIX.

A empresa então registra no contas a pagar uma duplicata **em nome do
investidor**, pelo valor cheio da compra, com o vencimento original. Nos
documentos isso aparece como `PIX 34277300855 — FAZER PAGAMENTO CONTA BRUNO`.

O investidor paga menos do que vai receber. A diferença — o desconto que o
fornecedor concedeu — é o lucro dele. O sistema existe para saber quanto disso
já voltou, quanto está na rua, e se o capital está rendendo ou dormindo.

```
Fornecedor  ──NF R$ 9.725,00 (30 dias)──>  Machado Embalagens
     ^                                            |
     | PIX R$ 9.336,00 à vista                    | duplicata R$ 9.725,00
     |                                            v  venc. 24/10
  Investidor  <─────── R$ 9.725,00 em 24/10 ──────┘

  Saiu 9.336,00 · Voltou 9.725,00 · Lucro 389,00 em 30 dias
```

## 2. Glossário

Use estes termos em código, banco, API e tela. Mistura de vocabulário é a maior
fonte de bug neste domínio.

| Termo | Significado | Campo |
|---|---|---|
| **Operação** | Uma compra paga à vista pelo investidor | `operacao` |
| **Valor cheio** | O que a empresa devolve ao investidor; soma das duplicatas | `operacao.valor_cheio` |
| **Valor pago** | O PIX que saiu da conta do investidor para o fornecedor | `operacao.valor_pago` |
| **Lucro** | `valor_cheio − valor_pago` | calculado |
| **Duplicata** | Cada parcela do retorno, com valor e vencimento | `duplicata` |
| **Desconto** | `lucro ÷ valor_cheio` — a taxa que o **fornecedor** concedeu | calculado |
| **Retorno** | `lucro ÷ valor_pago` — a taxa que o **investidor** ganhou | calculado |
| **Aporte** | Dinheiro novo que o investidor coloca no caixa | `movimento_caixa` |
| **Retirada** | Dinheiro que o investidor tira do caixa | `movimento_caixa` |
| **Caixa disponível** | Dinheiro livre para uma nova compra | calculado |
| **Aplicado** / **na rua** | Capital dentro de duplicatas ainda não recebidas | calculado |
| **Capital total** | `caixa + aplicado` | calculado |
| **Dinheiro parado** | O caixa que não está sendo usado — custa lucro | calculado |
| **Prazo médio** | Dias até o retorno, ponderados pelo valor de cada duplicata | calculado |

Evite: "fatura", "boleto", "título", "parcela", "empréstimo", "juros". Nenhum
desses é o que acontece aqui, e cada um traz um modelo mental errado junto.

## 3. Ciclo de vida da operação

```
                    ┌──────────────┐
   robô lê docs ───> │   rascunho   │ ──aprovação──┐
                    └──────────────┘              │
                           │ descarte             v
                           v              ┌──────────────┐
                       (arquivado)        │  confirmada  │
                                          └──────────────┘
                                                 │
                            ┌────────────────────┼──────────────────┐
                            v                    v                  v
                    1ª duplicata            todas recebidas      estorno
                      recebida                    │                  │
                            v                     v                  v
                    ┌──────────────┐      ┌──────────────┐   ┌──────────────┐
                    │   parcial    │─────>│  encerrada   │   │  estornada   │
                    └──────────────┘      └──────────────┘   └──────────────┘
```

`parcial` e `encerrada` **não são campos** — são derivados das duplicatas:

```
nenhuma recebida            → em aberto
alguma recebida, falta      → parcial
todas recebidas             → encerrada
alguma vencida e não paga   → atrasada   (flag independente, pode somar com parcial)
```

Guarde em `operacao.situacao` apenas `rascunho`, `confirmada` e `estornada`.
Derive o resto, sempre. Um campo de status redundante vai dessincronizar.

## 4. Regras de negócio

### RN-01 — A soma das duplicatas é o valor cheio

`Σ duplicata.valor = operacao.valor_cheio`, com tolerância zero.

Quando o sistema divide um valor cheio em N duplicatas, a **última absorve a
diferença de arredondamento**:

```
parte = floor(valor_cheio / n * 100) / 100
últimas = valor_cheio − (parte × (n−1))
```

Exemplo real: R$ 25.951,80 em 2 → 12.975,90 + 12.975,90. Com R$ 10.000,00 em 3 →
3.333,33 + 3.333,33 + 3.333,34.

Validar por trigger no banco, não só na aplicação.

### RN-02 — O valor pago não pode passar do valor cheio

`valor_pago ≤ valor_cheio`. Igual é permitido (lucro zero) mas a tela avisa.
Maior é erro de digitação — bloquear.

### RN-03 — Não se compra sem caixa

No momento do lançamento, `valor_pago ≤ caixa_disponível`. A mensagem de erro
precisa dizer quanto há e o que fazer:

> Caixa insuficiente: você tem R$ 2.913,60 livre. Registre um aporte antes de
> lançar esta compra.

Ao **editar** uma operação já existente, o caixa disponível para a conta é
`caixa + valor_pago_anterior − já_recebido_dela` — senão a própria operação
bloqueia a edição de si mesma.

### RN-04 — Recebimento não acontece antes do pagamento

`duplicata.recebida_em ≥ operacao.data_pagamento`. Pode ser antes do vencimento
(antecipação) ou depois (atraso) — ambos são normais e devem ser aceitos sem
alarde.

### RN-05 — Retirada limitada ao caixa

`valor_retirada ≤ caixa_disponível`. Sem exceção: o capital na rua não pode ser
sacado porque ainda não voltou.

### RN-06 — Operação com dinheiro recebido não se apaga

Se qualquer duplicata tem `recebida_em`, a operação só sai por **estorno**, que
cria os lançamentos contrários e mantém o histórico. Operação sem nenhum
recebimento pode ser excluída logicamente (`situacao = 'estornada'`).

### RN-07 — As duas taxas

```
desconto = lucro / valor_cheio      ← a negociação com o fornecedor
retorno  = lucro / valor_pago       ← o ganho do investidor
retorno  = desconto / (1 − desconto)
```

| Desconto | Retorno |
|---|---|
| 3,00% | 3,09% |
| 4,00% | 4,17% |
| 5,00% | 5,26% |
| 10,00% | 11,11% |

**Toda taxa exibida no sistema é o retorno sobre o valor pago.** O desconto
aparece como informação secundária, sempre rotulado "desconto no valor cheio".
Misturar os dois já gerou confusão real no uso da ferramenta.

### RN-08 — O lucro é apropriado dia a dia

O lucro de uma operação **não** é jogado inteiro no mês da compra. Ele é
distribuído linearmente pelos dias entre o pagamento e o vencimento de cada
duplicata, para que cada mês mostre o dinheiro que realmente esteve na rua
naquele período. Fórmula em [03-formulas.md](03-formulas.md#5-resultado-por-mês-competência).

### RN-09 — O prazo conta do pagamento, não do pedido

`data_pagamento` é o que inicia a contagem, porque é quando o dinheiro sai. Pode
ser diferente da `data_pedido`. Caso real: pedido PC 03273-2/26 emitido em
16/10/2026, PIX feito em 19/10/2026 — o prazo até o vencimento em 15/11 é de **27
dias**, não 30.

### RN-10 — Moeda e arredondamento

Duas casas decimais, `ROUND_HALF_UP`, em todo lugar. Percentuais calculados em
`NUMERIC` e arredondados só na exibição. Nunca comparar dinheiro com `=` em
ponto flutuante; se precisar de tolerância, use `0.005`.

## 5. Armadilhas reais — todas já aconteceram

Estas não são hipóteses. Cada uma apareceu nos três primeiros meses de operação e
precisa de tratamento explícito.

### A-01 — O fornecedor lança o desconto na própria nota

A SB Indústria emite a NF já com o desconto aplicado. Resultado: **o total
impresso do pedido não bate com a soma dos itens**.

> Pedido PC 03273-1/26: itens 250 un × R$ 38,90 = **R$ 9.725,00**.
> Total do pedido e duplicata impressos: **R$ 9.327,00**. Diferença: R$ 398,00.

O valor cheio correto é **a soma dos itens** (R$ 9.725,00) — é isso que a Machado
devolve. Quem lê o total impresso lança a operação com prejuízo de R$ 9,00 em vez
de lucro de R$ 389,00.

**Tratamento:** o robô de ingestão compara `Σ(qtd × valor_unitário)` com o total
impresso. Divergência acima de R$ 0,01 vira uma pendência explícita no rascunho,
com os dois números lado a lado. Nunca escolher sozinho.

### A-02 — Ano errado no vencimento

O pedido PC 03273-0/26, de setembro de 2026, saiu com vencimento impresso
**06/10/2025**. Um título com data no passado some dos relatórios ou aparece como
vencido há um ano.

**Tratamento:** se `vencimento < data_pagamento` ou `vencimento > data_pagamento +
365 dias`, barrar e pedir confirmação. É quase sempre o ano digitado errado.

### A-03 — Quantidade do pedido ≠ quantidade da nota

No PC 03273-2/26 a quantidade do pedido era 250 un mas a entrada em estoque foi de
**110 un**, e o valor cheio seguiu a quantidade entregue (110 × 38,90 =
R$ 4.279,00).

**Tratamento:** o valor cheio vem sempre do **total da duplicata**, não da
multiplicação da quantidade pedida. A conferência de itens serve para detectar
A-01, não para calcular o valor.

### A-04 — Mais de um pedido pago no mesmo dia, com PIX separados

Em 16/09/2026 foram dois pedidos da Brislu, com dois PIX de valores diferentes
(R$ 24.864,00 e R$ 32.313,60). Casar comprovante com pedido pela data não
funciona.

**Tratamento:** casar por **valor**. Se dois comprovantes do mesmo dia têm
valores diferentes, o maior pertence ao pedido de maior valor cheio. Se houver
empate de valor, pedir a escolha.

### A-05 — A taxa do fornecedor muda sem aviso

A Brislu operava a 3,00% em agosto e passou a 4,19% em setembro. O sistema não
pode ter desconto fixo por fornecedor — `fornecedor.desconto_padrao` é apenas
sugestão de preenchimento, e o valor real vem sempre dos documentos.

## 6. O que o sistema deliberadamente NÃO faz

Deixar isso claro evita escopo inventado depois:

- Não emite nenhum documento fiscal.
- Não movimenta conta bancária nem dispara PIX.
- Não controla estoque, nem preço de venda, nem margem de revenda.
- Não é contabilidade: é controle gerencial do capital do investidor.
- Não decide se uma compra deve ser feita — mostra o retorno e quem decide é a
  pessoa.
