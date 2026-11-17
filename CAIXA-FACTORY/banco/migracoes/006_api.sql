-- ---------------------------------------------------------------
-- Caixa Factory — 006: tabelas de apoio da API
-- Fonte: docs/04-api.md, seção 1 (autenticação e idempotência)
-- ---------------------------------------------------------------
set search_path to caixa, public;

-- Sessões de login da tela. Guarda só o sha256 do token: quem lê o banco
-- não consegue se passar por ninguém.
create table caixa.sessao (
  token_hash   text        primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  usuario_id   bigint      not null references caixa.usuario(id) on delete cascade,
  criada_em    timestamptz not null default now(),
  expira_em    timestamptz not null,
  ultimo_uso   timestamptz not null default now()
);

create index on caixa.sessao (usuario_id);
create index on caixa.sessao (expira_em);

-- Idempotency-Key: repetir o mesmo POST em até 24h devolve a resposta original.
create table caixa.idempotencia (
  chave        text        not null check (length(chave) between 8 and 200),
  usuario_id   bigint      not null references caixa.usuario(id) on delete cascade,
  rota         text        not null,        -- 'POST /operacoes'
  status       int         not null,
  resposta     jsonb,
  criado_em    timestamptz not null default now(),
  primary key (chave, usuario_id)
);

create index on caixa.idempotencia (criado_em);

-- PATCH /operacoes troca a lista de duplicatas e renumera a sequência por
-- vencimento num único UPDATE. Com a unique deferrable, a checagem é no fim
-- do comando, e trocar 1<->2 não colide no meio do caminho.
alter table caixa.duplicata drop constraint duplicata_operacao_id_sequencia_key;
alter table caixa.duplicata add constraint duplicata_sequencia_unica
  unique (operacao_id, sequencia) deferrable initially immediate;
