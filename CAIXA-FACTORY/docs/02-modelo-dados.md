# 02 — Modelo de dados

PostgreSQL 15+. Para MySQL, troque `bigserial` por `bigint auto_increment`,
`jsonb` por `json`, `text` por `varchar`, e mova os `check` para triggers.

## 1. Diagrama

```
  fornecedor 1 ──< operacao 1 ──< duplicata
                      │
                      ├──< documento
                      │
  movimento_caixa     └──< evento (auditoria, polimórfico)

  usuario ──< operacao.criado_por, movimento_caixa.criado_por, evento.usuario_id
  parametro (configuração: limiar de caixa parado, etc.)
```

## 2. DDL

```sql
-- ---------------------------------------------------------------
-- Caixa Factory — esquema inicial
-- ---------------------------------------------------------------
create schema if not exists caixa;
set search_path to caixa, public;

-- Usuários ------------------------------------------------------
create table usuario (
  id            bigserial primary key,
  nome          text        not null,
  email         text        not null unique,
  senha_hash    text        not null,
  papel         text        not null default 'operador'
                check (papel in ('admin','operador','leitura')),
  ativo         boolean     not null default true,
  criado_em     timestamptz not null default now()
);

-- Fornecedores --------------------------------------------------
create table fornecedor (
  id               bigserial primary key,
  nome             text        not null,
  cnpj             text unique,
  chave_pix        text,
  desconto_padrao  numeric(6,4),          -- 0.0400 = 4%; apenas sugestão (A-05)
  prazo_padrao     text,                  -- '30/40', '30', '28/35/42'
  observacoes      text,
  ativo            boolean     not null default true,
  criado_em        timestamptz not null default now()
);

comment on column fornecedor.desconto_padrao is
  'Sugestão de preenchimento. O valor real vem sempre dos documentos (ver A-05).';

-- Operações -----------------------------------------------------
create table operacao (
  id              bigserial primary key,
  fornecedor_id   bigint      not null references fornecedor(id),
  numero_pedido   text        not null,          -- 'PC 03273-2/26'
  numero_nf       text,                          -- '12893'
  data_pedido     date,
  data_pagamento  date        not null,          -- inicia a contagem do prazo (RN-09)
  valor_pago      numeric(14,2) not null check (valor_pago  > 0),
  valor_cheio     numeric(14,2) not null check (valor_cheio > 0),
  situacao        text        not null default 'confirmada'
                  check (situacao in ('rascunho','confirmada','estornada')),
  origem          text        not null default 'manual'
                  check (origem in ('manual','robo','importacao')),
  observacoes     text,
  estornada_em    timestamptz,
  estorno_motivo  text,
  criado_por      bigint      references usuario(id),
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),

  constraint pago_nao_passa_do_cheio check (valor_cheio >= valor_pago),  -- RN-02
  constraint pedido_unico_por_fornecedor unique (fornecedor_id, numero_pedido)
);

create index on operacao (data_pagamento);
create index on operacao (situacao) where situacao = 'confirmada';

-- Duplicatas ----------------------------------------------------
create table duplicata (
  id            bigserial primary key,
  operacao_id   bigint      not null references operacao(id) on delete restrict,
  sequencia     int         not null check (sequencia >= 1),
  valor         numeric(14,2) not null check (valor > 0),
  vencimento    date        not null,
  recebida_em   date,
  criado_em     timestamptz not null default now(),

  unique (operacao_id, sequencia)
);

create index on duplicata (vencimento) where recebida_em is null;
create index on duplicata (operacao_id);

-- Movimentos de caixa -------------------------------------------
create table movimento_caixa (
  id           bigserial primary key,
  tipo         text        not null check (tipo in ('aporte','retirada')),
  data         date        not null,
  valor        numeric(14,2) not null check (valor > 0),
  observacoes  text,
  criado_por   bigint      references usuario(id),
  criado_em    timestamptz not null default now()
);

create index on movimento_caixa (data);

-- Documentos ----------------------------------------------------
create table documento (
  id            bigserial primary key,
  operacao_id   bigint      references operacao(id) on delete restrict,
  tipo          text        not null
                check (tipo in ('pedido_compra','comprovante_pix','nota_fiscal','outro')),
  nome_arquivo  text        not null,      -- 2026-10-19_PC-03273-2-26_comprovante-pix.pdf
  caminho       text        not null,      -- operacoes/2026-10/<nome_arquivo>
  mime          text,
  bytes         bigint,
  sha256        text        unique,        -- evita subir o mesmo arquivo duas vezes
  data_doc      date,                      -- data impressa no documento
  enviado_em    timestamptz not null default now()
);

create index on documento (operacao_id);

-- Auditoria -----------------------------------------------------
create table evento (
  id           bigserial primary key,
  entidade     text        not null,   -- 'operacao','duplicata','movimento_caixa'
  entidade_id  bigint      not null,
  acao         text        not null,   -- 'criou','alterou','recebeu','desfez','estornou'
  antes        jsonb,
  depois       jsonb,
  usuario_id   bigint      references usuario(id),
  em           timestamptz not null default now()
);

create index on evento (entidade, entidade_id);
create index on evento (em desc);

-- Parâmetros ----------------------------------------------------
create table parametro (
  chave      text primary key,
  valor      text not null,
  descricao  text
);

insert into parametro (chave, valor, descricao) values
  ('caixa_parado_limite',  '20000.00', 'Acima disso o robô alerta (R$)'),
  ('caixa_parado_dias',    '3',        'Dias seguidos acima do limite antes de alertar'),
  ('alerta_destino',       '',         'Telegram chat id / e-mail para os alertas'),
  ('dias_agenda',          '45',       'Janela da tela de próximos retornos');
```

## 3. Triggers de integridade

### RN-01 — a soma das duplicatas tem que fechar

```sql
create or replace function caixa.valida_soma_duplicatas() returns trigger as $$
declare
  v_op    bigint := coalesce(new.operacao_id, old.operacao_id);
  v_soma  numeric(14,2);
  v_cheio numeric(14,2);
  v_sit   text;
begin
  select valor_cheio, situacao into v_cheio, v_sit
    from caixa.operacao where id = v_op;

  -- rascunho pode estar incompleto; confirmada não
  if v_sit = 'rascunho' then return null; end if;

  select coalesce(sum(valor),0) into v_soma
    from caixa.duplicata where operacao_id = v_op;

  if v_soma <> v_cheio then
    raise exception
      'Duplicatas somam % e o valor cheio é % (operação %)', v_soma, v_cheio, v_op;
  end if;
  return null;
end $$ language plpgsql;

create constraint trigger tg_soma_duplicatas
  after insert or update or delete on caixa.duplicata
  deferrable initially deferred
  for each row execute function caixa.valida_soma_duplicatas();
```

`deferrable initially deferred` é essencial: permite inserir a operação e as
duplicatas na mesma transação e só validar no commit.

### RN-04 — recebimento não vem antes do pagamento

```sql
create or replace function caixa.valida_recebimento() returns trigger as $$
declare v_pag date;
begin
  if new.recebida_em is null then return new; end if;
  select data_pagamento into v_pag from caixa.operacao where id = new.operacao_id;
  if new.recebida_em < v_pag then
    raise exception 'Recebimento em % é anterior ao pagamento em %', new.recebida_em, v_pag;
  end if;
  return new;
end $$ language plpgsql;

create trigger tg_valida_recebimento
  before insert or update of recebida_em on caixa.duplicata
  for each row execute function caixa.valida_recebimento();
```

### A-02 — vencimento com ano implausível

```sql
alter table caixa.duplicata add constraint vencimento_plausivel
  check (vencimento >= date '2026-01-01' and vencimento <= date '2099-12-31');
```

A checagem fina (`vencimento` entre `data_pagamento` e `+365 dias`) fica na
aplicação, porque precisa de confirmação do usuário, não de bloqueio seco.

### RN-06 — não apagar operação com recebimento

```sql
create or replace function caixa.protege_operacao() returns trigger as $$
begin
  if exists (select 1 from caixa.duplicata
             where operacao_id = old.id and recebida_em is not null) then
    raise exception 'Operação % tem duplicata recebida: use estorno, não exclusão', old.id;
  end if;
  return old;
end $$ language plpgsql;

create trigger tg_protege_operacao
  before delete on caixa.operacao
  for each row execute function caixa.protege_operacao();
```

### Auditoria automática

```sql
create or replace function caixa.registra_evento() returns trigger as $$
begin
  insert into caixa.evento (entidade, entidade_id, acao, antes, depois, usuario_id)
  values (
    tg_table_name,
    coalesce(new.id, old.id),
    lower(tg_op),
    case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end,
    case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end,
    nullif(current_setting('caixa.usuario_id', true), '')::bigint
  );
  return coalesce(new, old);
end $$ language plpgsql;

create trigger tg_evento_operacao after insert or update or delete on caixa.operacao
  for each row execute function caixa.registra_evento();
create trigger tg_evento_duplicata after insert or update or delete on caixa.duplicata
  for each row execute function caixa.registra_evento();
create trigger tg_evento_movimento after insert or update or delete on caixa.movimento_caixa
  for each row execute function caixa.registra_evento();
```

A API precisa fazer `set local caixa.usuario_id = '<id>'` no início de cada
transação para que o log saiba quem agiu.

## 4. Views de cálculo

Estas views são a implementação de referência de [03-formulas.md](03-formulas.md).
Se a aplicação calcular por conta própria, os resultados têm que bater com elas.

```sql
-- Métricas por operação -----------------------------------------
create view v_operacao as
with base as (
  select o.id,
         o.fornecedor_id, o.numero_pedido, o.numero_nf,
         o.data_pedido, o.data_pagamento, o.valor_pago, o.valor_cheio,
         o.situacao, o.observacoes,
         sum(d.valor)                                                as face,
         sum(d.valor) filter (where d.recebida_em is not null)       as recebido,
         count(*)                                                     as qt_duplicatas,
         count(*) filter (where d.recebida_em is null)                as qt_abertas,
         count(*) filter (where d.recebida_em is null
                            and d.vencimento < current_date)          as qt_atrasadas,
         -- prazo médio ponderado pelo valor de cada duplicata
         sum(d.valor * greatest(
               (coalesce(d.recebida_em, d.vencimento) - o.data_pagamento), 1))
           / nullif(sum(d.valor), 0)                                  as prazo_medio
    from operacao o
    join duplicata d on d.operacao_id = o.id
   where o.situacao = 'confirmada'
   group by o.id
)
select b.*,
       coalesce(b.recebido, 0)                       as recebido_,
       b.face - coalesce(b.recebido,0)               as aberto,
       b.face - b.valor_pago                         as lucro,
       (b.face - b.valor_pago) / b.valor_pago        as retorno,
       (b.face - b.valor_pago) / b.face              as desconto,
       power(1 + (b.face - b.valor_pago) / b.valor_pago,
             30.0 / nullif(b.prazo_medio,0)) - 1     as taxa_mes,
       power(1 + (b.face - b.valor_pago) / b.valor_pago,
             365.0 / nullif(b.prazo_medio,0)) - 1    as taxa_ano,
       case
         when b.face - coalesce(b.recebido,0) <= 0.005 then 'encerrada'
         when coalesce(b.recebido,0) > 0.005          then 'parcial'
         when b.qt_atrasadas > 0                      then 'atrasada'
         else 'em_aberto'
       end                                           as estado
  from base b;

-- Posição do caixa ----------------------------------------------
create view v_caixa as
with mov as (
  select coalesce(sum(valor) filter (where tipo='aporte'),  0) as aportes,
         coalesce(sum(valor) filter (where tipo='retirada'),0) as retiradas
    from movimento_caixa
), op as (
  select coalesce(sum(valor_pago),0)                                as pago_total,
         coalesce(sum(recebido_),0)                                 as recebido_total,
         coalesce(sum(valor_pago * aberto / nullif(face,0)),0)      as aplicado,
         coalesce(sum(aberto),0)                                    as a_receber,
         coalesce(sum(recebido_ - valor_pago * recebido_/nullif(face,0)),0) as lucro_realizado,
         coalesce(sum(aberto   - valor_pago * aberto  /nullif(face,0)),0)   as lucro_a_receber
    from v_operacao
)
select mov.aportes, mov.retiradas,
       mov.aportes - mov.retiradas - op.pago_total + op.recebido_total as caixa,
       op.aplicado,
       mov.aportes - mov.retiradas - op.pago_total + op.recebido_total
         + op.aplicado                                                 as capital,
       op.a_receber, op.lucro_realizado, op.lucro_a_receber
  from mov, op;
```

> **Cuidado com `v_operacao`:** o `join duplicata` elimina operações sem
> duplicata. Em `rascunho` isso é esperado (a view filtra `confirmada`), mas se
> um dia aparecer operação confirmada sem duplicata, ela some silenciosamente dos
> totais. A trigger RN-01 impede esse estado; mantenha-a ativa.

## 5. Índices e desempenho

Com o volume real (dezenas de operações por ano), **nenhuma otimização é
necessária**. Os índices do DDL já são mais do que suficientes. Se um dia a
tabela passar de 100 mil duplicatas, materialize `v_operacao`; antes disso, não.

## 6. Retenção

Nada expira. `evento` cresce devagar (algumas dezenas de linhas por mês) e é a
única defesa contra "mas eu não mexi nisso". Mantenha indefinidamente.
