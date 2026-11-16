-- ---------------------------------------------------------------
-- Caixa Factory — 001: tabelas
-- Fonte: docs/02-modelo-dados.md, seção 2
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
  desconto_padrao  numeric(6,4) check (desconto_padrao is null
                                       or (desconto_padrao >= 0 and desconto_padrao < 1)),
  prazo_padrao     text,                  -- '30/40', '30', '28/35/42'
  observacoes      text,
  ativo            boolean     not null default true,
  criado_em        timestamptz not null default now()
);

comment on column fornecedor.desconto_padrao is
  'Sugestão de preenchimento (0.0400 = 4%). O valor real vem sempre dos documentos (ver A-05).';

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
  constraint pedido_unico_por_fornecedor unique (fornecedor_id, numero_pedido),
  -- estorno sempre com data e motivo; nada além de estornada tem esses campos
  constraint estorno_completo check (
    (situacao =  'estornada' and estornada_em is not null and coalesce(estorno_motivo,'') <> '')
 or (situacao <> 'estornada' and estornada_em is null)
  )
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

  unique (operacao_id, sequencia),
  -- A-02: barra o ano absurdo; a checagem fina (pagamento .. +365) é na aplicação
  constraint vencimento_plausivel
    check (vencimento >= date '2026-01-01' and vencimento <= date '2099-12-31')
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
  bytes         bigint      check (bytes is null or bytes >= 0),
  sha256        text        unique         -- evita subir o mesmo arquivo duas vezes
                check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  data_doc      date,                      -- data impressa no documento
  enviado_em    timestamptz not null default now()
);

create index on documento (operacao_id);

-- Auditoria -----------------------------------------------------
create table evento (
  id           bigserial primary key,
  entidade     text        not null,   -- 'operacao','duplicata','movimento_caixa',...
  entidade_id  bigint      not null,
  acao         text        not null,   -- 'criou','alterou','recebeu','desfez','estornou','excluiu'
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
