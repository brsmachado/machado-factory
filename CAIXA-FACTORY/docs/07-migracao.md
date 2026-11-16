# 07 — Migração dos dados existentes

Três meses de operação já estão registrados. Nada se perde.

## 1. De onde vêm os dados

| Fonte | O que tem | Onde está |
|---|---|---|
| **Artefato publicado** | A verdade atual — 7 operações, 11 duplicatas, 2 aportes | JSON embutido na página |
| **CSV de operações** | Mesmo conteúdo, uma linha por duplicata | `registros/operacoes.csv` |
| **CSV de movimentos** | Aportes e retiradas | `registros/movimentos.csv` |
| **Documentos** | 16 arquivos: pedidos e comprovantes | `operacoes/AAAA-MM/` |

A fonte canônica é o **artefato**. Os CSV são espelhos para o contador e podem
estar um passo atrás.

## 2. O arquivo de carga

[`seed/estado-2026-10-19.json`](seed/estado-2026-10-19.json) já está no formato
das tabelas: fornecedores, movimentos, operações e duplicatas, com ids
atribuídos e valores como string decimal.

```json
{
  "fornecedores": [
    { "id": 1, "nome": "Brislu Plásticos" },
    { "id": 2, "nome": "SB Indústria e Comércio de Papel" }
  ],
  "movimentos_caixa": [
    { "id": 1, "tipo": "aporte", "data": "2026-08-28", "valor": "100000.00",
      "observacoes": "Aporte inicial" }
  ],
  "operacoes": [
    { "id": 1, "fornecedor_id": 1, "numero_pedido": "PC 03282-2/26",
      "data_pagamento": "2026-08-27", "valor_pago": "63321.60",
      "valor_cheio": "65280.00", "situacao": "confirmada", "origem": "importacao" }
  ],
  "duplicatas": [
    { "id": 1, "operacao_id": 1, "sequencia": 1, "valor": "32640.00",
      "vencimento": "2026-09-26", "recebida_em": "2026-09-26" }
  ],
  "conferencia": { "caixa": "111810.32", "...": "..." }
}
```

O bloco `conferencia` existe para ser usado: depois da carga, rode `GET /resumo`
e compare campo a campo. Divergência de um centavo significa bug no cálculo.

## 3. Como extrair uma versão mais nova

O artefato continua em uso e pode ter avançado. Para pegar o estado do dia:

```bash
# o JSON está dentro de <script id="estado" type="application/json">
python3 - <<'EOF'
import re, json
html = open('caixa-machado.html', encoding='utf-8').read()
m = re.search(r'<script id="estado" type="application/json">(.*?)</script>', html, re.S)
estado = json.loads(m.group(1).replace('<\\/', '</'))
print(json.dumps(estado, ensure_ascii=False, indent=2))
EOF
```

A barra invertida antes de `/` é escape do HTML — sem o `replace` o JSON não
parseia.

### Formato do artefato → formato das tabelas

| Artefato | Tabela |
|---|---|
| `movimentos[].tipo/data/valor/obs` | `movimento_caixa` direto |
| `operacoes[].data` | `operacao.data_pagamento` (é a data do PIX) |
| `operacoes[].pago` | `operacao.valor_pago` |
| `operacoes[].doc` | separar em `numero_pedido` e `numero_nf` pelo `·` |
| `Σ operacoes[].parcelas[].v` | `operacao.valor_cheio` |
| `parcelas[].v/d/r` | `duplicata.valor` / `vencimento` / `recebida_em` |
| `parcelas[].r == ""` | `recebida_em = NULL` |

A `sequencia` da duplicata vem da ordem de vencimento.

## 4. Ordem da carga

```sql
begin;
set local caixa.usuario_id = '1';

-- 1. fornecedores
-- 2. movimentos_caixa
-- 3. operacoes
-- 4. duplicatas        ← a trigger de soma é deferred, valida no commit

-- reposiciona as sequences
select setval('caixa.fornecedor_id_seq',       (select max(id) from caixa.fornecedor));
select setval('caixa.operacao_id_seq',         (select max(id) from caixa.operacao));
select setval('caixa.duplicata_id_seq',        (select max(id) from caixa.duplicata));
select setval('caixa.movimento_caixa_id_seq',  (select max(id) from caixa.movimento_caixa));

commit;
```

Esquecer o `setval` é o erro clássico: o primeiro registro novo colide com id
existente.

## 5. Conferência obrigatória pós-carga

```sql
select * from caixa.v_caixa;
```

Tem que devolver exatamente:

| campo | valor |
|---|---|
| caixa | 111810.32 |
| aplicado | 42032.64 |
| capital | 153842.96 |
| a_receber | 43843.56 |
| lucro_realizado | 3842.96 |
| lucro_a_receber | 1810.92 |

E a identidade:

```sql
select (caixa + aplicado) = (aportes - retiradas + lucro_realizado) as ok
  from caixa.v_caixa;   -- precisa ser true
```

Também confira o resultado mensal contra a tabela de
[03-formulas.md](03-formulas.md#exemplos-conferidos):

| Mês | Lucro | Aplicado médio | Parado médio | Deixou de ganhar |
|---|---|---|---|---|
| 2026-08 | 249,90 | 8.936,52 | 3.966,71 | 110,92 |
| 2026-09 | 3.200,32 | 103.260,88 | 21.739,12 | 673,75 |
| 2026-10 | 2.108,57 | 56.379,73 | 93.620,27 | 3.501,35 |
| 2026-11 | 95,09 | 2.053,92 | 147.946,08 | 6.849,36 |

## 6. Documentos

Os 16 arquivos já estão organizados e **a convenção de nomes do sistema novo é a
mesma**:

```
operacoes/
  2026-08/
    2026-08-27_PC-03282-2-26_pedido-compra.png
    2026-08-28_PC-03282-2-26_comprovante-pix.png
    2026-08-28_PC-03282-4-26_pedido-compra.png
    2026-08-28_PC-03282-4-26_comprovante-pix.png
  2026-09/   (8 arquivos)
  2026-10/   (2 arquivos)
```

Padrão: `AAAA-MM-DD_PC-<pedido com hífen>_<tipo>.<ext>`, onde o tipo é
`pedido-compra` ou `comprovante-pix`, e a data é a do próprio documento (o
pedido e o comprovante podem ser de dias diferentes).

Script de vinculação:

```python
import re, pathlib
PADRAO = re.compile(r'(\d{4}-\d{2}-\d{2})_PC-(.+?)_(pedido-compra|comprovante-pix)\.')

for arq in pathlib.Path('operacoes').rglob('*'):
    if not arq.is_file(): continue
    m = PADRAO.match(arq.name)
    if not m:
        print('fora do padrão:', arq); continue
    data, pedido_slug, tipo = m.groups()
    numero_pedido = 'PC ' + pedido_slug.replace('-26', '/26', 1)[::-1].replace('-', '-', 1)[::-1]
    # casar por numero_pedido na tabela operacao e inserir em documento
```

O `sha256` de cada arquivo entra na tabela — é o que impede o mesmo comprovante
de ser anexado duas vezes.

## 7. Cortar o cordão

Depois da carga conferida:

1. Publique uma última versão do artefato com um aviso no topo: *"Este painel foi
   substituído pelo Caixa Factory em `<endereço>`. Mantido apenas para
   histórico."*
2. **Não apague o artefato.** Ele é o backup de origem e custa nada manter.
3. Guarde `seed/estado-2026-10-19.json` no repositório — é a prova de que a
   migração estava certa no dia em que foi feita.
