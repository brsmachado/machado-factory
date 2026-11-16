# Caixa Machado — capital proprio aplicado nas compras

Pago o fornecedor a vista com desconto e a Machado Embalagens me devolve o valor cheio
nas duplicatas. O desconto e o meu lucro, reconhecido conforme cada duplicata volta.

Atencao aos dois percentuais: o desconto e sobre o valor cheio; o retorno e sobre o que
saiu do meu bolso, que e menor. Desconto de 3% = 3,09% de retorno. Desconto de 4% = 4,17%.

## Onde fica cada coisa

- `sistema/caixa-machado.html` — copia de seguranca do sistema. A versao viva, com os
  lancamentos gravados, e o artefato publicado no Claude ("Caixa Machado").
- `operacoes/AAAA-MM/` — pedido de compra e comprovante de PIX de cada operacao.
- `registros/operacoes.csv` — espelho em planilha, uma linha por duplicata.
- `registros/movimentos.csv` — aportes e retiradas do caixa.
  (separador `;`, padrao Excel BR)

## Como nomear os arquivos

`AAAA-MM-DD_PC-<numero do pedido>_<tipo>.png`

- `pedido-compra` — a tela do pedido no sistema, com valor cheio e duplicatas.
- `comprovante-pix` — o comprovante do pagamento a vista ao fornecedor.

## Operacoes registradas

| Pedido | Fornecedor | Valor cheio | Paguei | Lucro | Retorno | Duplicatas |
|---|---|---|---|---|---|---|
| PC 03282-2/26 | Brislu Plasticos | R$ 65.280,00 | R$ 63.321,60 | R$ 1.958,40 | 3,09% | 2x R$ 32.640,00 — 26/09 e 06/10 |
| PC 03282-4/26 | Brislu Plasticos | R$ 8.160,00 | R$ 7.915,20 | R$ 244,80 | 3,09% | 2x R$ 4.080,00 — 27/09 e 07/10 |
| PC 03273-0/26 | SB Ind. e Com. de Papel | R$ 9.725,00 | R$ 9.336,00 | R$ 389,00 | 4,17% | 1x R$ 9.725,00 — 06/10 |
| PC 03295-5/26 | Brislu Plasticos | R$ 25.951,80 | R$ 24.864,00 | R$ 1.087,80 | 4,38% | 2x R$ 12.975,90 — 16/10 e 26/10 |
| PC 03331-1/26 | Brislu Plasticos | R$ 33.727,32 | R$ 32.313,60 | R$ 1.413,72 | 4,38% | 2x R$ 16.863,66 — 16/10 e 26/10 |

## Posicao em 19/10/2026

Aportado: R$ 150.000,00 · Caixa livre: **R$ 111.810,32** · Capital em uso: 27,3%
Ja recebido da Machado: R$ 113.004,56 em 7 duplicatas · Lucro realizado: R$ 3.842,96
A receber: R$ 43.843,56 em 4 duplicatas · Lucro a receber: R$ 1.810,92
Rentabilidade media das operacoes: 3,26% ao mes

ATENCAO: com R$ 111 mil parados, o rendimento do caixa inteiro caiu para 0,89% ao mes.
Em outubro o dinheiro parado ja custou cerca de R$ 3.500 em lucro nao realizado.

Obs.: a SB lanca o desconto na propria nota — o total impresso do pedido pode vir menor
que a soma dos itens. A duplicata correta e sempre o valor dos itens.
