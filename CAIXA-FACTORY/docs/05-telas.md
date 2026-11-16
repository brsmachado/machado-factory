# 05 — Telas

A página em uso hoje já é a especificação visual validada. Este documento
descreve o comportamento que o programador precisa preservar; o HTML/CSS pode ser
reaproveitado quase inteiro, trocando o estado embutido por chamadas à API.

## 1. Mapa das telas

```
/                 Painel (tudo numa página, rolagem vertical)
  ├─ faixa superior: título + status de gravação + ações
  ├─ 4 cartões de posição
  ├─ Rentabilidade do dinheiro (4 indicadores)
  ├─ Resultado por mês (seletor + barras + 4 indicadores)
  ├─ A conferir (só aparece se houver pendência)
  ├─ Próximos retornos (agenda)
  ├─ Operações (tabela + filtros + busca + exportar)
  ├─ Aportes e retiradas (tabela)
  └─ nota explicativa do método

/entrar           Login
/fornecedores     Cadastro (tela simples, pouco usada)
/historico        Log de eventos (auditoria)
```

Tudo numa página é deliberado: o dono olha o painel inteiro de uma vez, no
celular ou no painel lateral do Claude, que tem cerca de 680px de largura.
**Testar nessa largura é obrigatório.**

## 2. Painel — os quatro cartões de posição

| Cartão | Valor | Linha de apoio |
|---|---|---|
| **Caixa disponível** (destaque, maior) | `caixa` | "livre para novas compras" + barra caixa/aplicado + legenda com capital total |
| A receber da empresa | `a_receber` | "N parcelas em aberto · M operações" |
| Lucro realizado | `lucro_realizado` | "média de X% sobre o valor pago" |
| Lucro a receber | `lucro_a_receber` | "desconto embutido no que ainda está na rua" |

Regras:

- Caixa negativo em vermelho. Não deveria acontecer (RN-03), mas se acontecer
  tem que gritar.
- A barra é empilhada: azul = caixa, âmbar = aplicado, proporcionais ao capital.
- No painel estreito os três cartões menores ficam **lado a lado numa linha**.
  Um cartão sozinho com espaço vazio ao lado é lido como "não carregou" — isso
  já foi reportado como bug pelo usuário.

## 3. Rentabilidade do dinheiro

Quatro indicadores em linha:

1. **Retorno sobre o que você paga** — `taxa_mes` ao mês; apoio: `retorno` em N
   dias, equivalente a `taxa_ano` ao ano
2. **Lucro por mês** — `lucro_mes_reais`; apoio: lucro total
3. **Capital em uso** — `ocupacao`; apoio: "o restante fica parado no caixa, sem
   render"
4. **Rendimento do caixa inteiro** (destacado) — `rendimento_caixa_inteiro`

O quarto é o mais importante e por isso tem fundo próprio.

## 4. Resultado por mês

O seletor tem **três formas de uso**, todas obrigatórias:

- clicar numa barra
- escolher na lista suspensa
- setas ‹ › para o mês anterior/seguinte (desabilitadas nas pontas)

As barras são uma série só, altura proporcional ao maior lucro do período,
mínimo 2px para o mês não sumir. O valor aparece no topo da barra **apenas no
mês selecionado e no hover** — número em toda barra polui. Rótulo do mês
abreviado embaixo, sempre visível.

Indicadores do mês escolhido: **Lucro do mês · Aplicado no mês · Ficou parado ·
Deixou de ganhar** (destacado, em vermelho).

Um selo ao lado do título marca `mês em curso` ou `projeção`, e a nota de rodapé
avisa que os números ainda vão mudar.

O mês selecionado é estado de interface por visitante — não grava no servidor.

## 5. Tabela de operações

Colunas: **Compra** (data + selo de estado) · **Fornecedor** (nome, pedido/NF,
observações) · **Valor cheio** · **Paguei** · **Lucro** · **Retorno em
duplicatas** · ações.

A célula de lucro tem três linhas:

```
R$ 171,16                        ← lucro, verde (vermelho se negativo)
R$ 190,61 por mês                ← lucro mensal em reais
4,17% sobre o que paguei · 4,64% a.m.
desconto de 4,00% no valor cheio ← cinza, secundário
```

Essa hierarquia é o cumprimento de RN-07 na tela: o retorno em cima, o desconto
embaixo e apagado.

**Duplicatas como botões.** Cada duplicata é um botão clicável dentro da linha:

```
┌─────────────────────────────────┐
│ 1/2   16/10/2026   R$ 12.975,90 │  âmbar = em aberto
│ 2/2   recebida 26/10  R$ 12.975,90 │ verde = recebida
└─────────────────────────────────┘
                                      vermelho = vencida e não recebida
```

Clicar numa aberta abre "Registrar recebimento" com a data já preenchida (o
vencimento, se já passou; senão hoje). Clicar numa recebida abre "Desfazer
recebimento", com aviso de que o valor sai do caixa.

Filtros: `Todas · Em aberto · Recebidas` + busca por fornecedor ou NF. A busca
filtra sem recarregar a página inteira e **sem perder o foco do campo**.

## 6. Formulário de operação

```
Data da compra        Fornecedor
Valor cheio (R$)      Você pagou (R$)
┌──────────────────────────────────────────┐
│ Seu lucro nesta operação                 │
│ R$ 171,16 · 4,17% sobre o que você paga  │
│            (desconto de 4,00%)           │
└──────────────────────────────────────────┘
┌─ Duplicatas — como a Machado te devolve ─┐
│            [Dividir valor cheio] [+ dup] │
│ 1ª  [2026-11-15]  [4.279,00]         ✕   │
│ Soma das duplicatas            R$ 4.279,00│
└──────────────────────────────────────────┘
NF / Pedido
Observações
```

Comportamento:

- **"Dividir valor cheio"** reparte igualmente entre as duplicatas existentes, a
  última absorvendo o arredondamento (RN-01). Os vencimentos nascem em +30 e +40
  dias da data da compra — a condição mais comum.
- **"+ duplicata"** acrescenta uma com vencimento 10 dias após a última.
- A prévia do lucro recalcula a cada tecla.
- A linha "Soma das duplicatas" fica **vermelha** quando não bate com o valor
  cheio informado, mostrando os dois números.
- Entrada de valor aceita `1.234,56`, `1234,56` e `1234.56`.
- `Enter` confirma, `Esc` fecha, clique fora fecha.

Mensagens de erro, exatamente estas:

| Situação | Mensagem |
|---|---|
| Sem fornecedor | Informe o fornecedor. |
| Sem valor pago | Informe quanto você pagou ao fornecedor. |
| Sem duplicata | Cadastre pelo menos uma duplicata de retorno. |
| Duplicata sem valor | Toda duplicata precisa de um valor. |
| Duplicata sem data | Toda duplicata precisa de uma data de vencimento. |
| Soma < pago | As duplicatas somam R$ X, menos do que você pagou (R$ Y). Nesse caso não há lucro. |
| Caixa insuficiente | Caixa insuficiente: você tem R$ X livre. Registre um aporte antes de lançar esta compra. |

Erro explica o que houve **e** como resolver. Nada de "campo inválido".

## 7. Painel "A conferir"

Só aparece quando há pendências — rascunho do robô aguardando conferência,
divergência de valores, vencimento implausível. Cartão de borda âmbar, acima da
agenda, com os números lado a lado e a nota explicando o que fazer.

Quando a lista esvazia, o cartão some inteiro. Nada de "nenhuma pendência".

## 8. Aparência

Tokens do sistema atual, já validados em claro e escuro:

```css
--accent: #14508C / #77ACE8      /* azul profundo */
--ok:     #136A4B / #54C296      /* verde — recebido, lucro */
--warn:   #8A5A00 / #DFAC42      /* âmbar — em aberto, parado */
--bad:    #9C2A21 / #EF8577      /* vermelho — atrasado, prejuízo */
--band:   #101821                /* faixa superior escura */
```

Tipografia: **Archivo** em títulos e rótulos, **IBM Plex Sans** no texto, **IBM
Plex Mono** com `font-variant-numeric: tabular-nums` em todo número — sem isso as
colunas de dinheiro não alinham.

Tema claro e escuro são dois conjuntos escolhidos, não uma inversão automática. O
`body` sempre pinta o próprio fundo.

## 9. Acessibilidade e estados

- Foco visível em tudo que recebe teclado.
- Botão de duplicata é `<button>` com `aria-label` completo
  ("Brislu Plásticos, 1ª de 2, vence 16/10/2026, R$ 12.975,90").
- Tabela com cabeçalho real; nada de `div` fingindo de tabela.
- Tabelas largas rolam na horizontal **dentro do próprio contêiner** — a página
  nunca rola para o lado.
- `prefers-reduced-motion` desliga as transições.
- Estado vazio tem texto que ensina: "Clique em Nova operação para lançar a
  primeira compra com desconto."
- Estado de gravação visível na faixa superior: `Tudo salvo` · `Salvando…` ·
  `Falha ao salvar`.
