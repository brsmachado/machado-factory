-- ---------------------------------------------------------------
-- Caixa Factory — 007: o robô
-- Fonte: docs/06-robo.md. Um robô só, no Telegram: lê pedidos e comprovantes
-- e monta rascunhos; todo dia útil manda o aviso de vencimentos e de dinheiro
-- parado. Ele nunca grava operação: quem aprova é o dono.
-- ---------------------------------------------------------------
set search_path to caixa, public;

-- Rascunho de operação. Fica fora da tabela operacao porque nasce incompleto:
-- às vezes só o pedido chegou, às vezes só o comprovante, e operacao exige
-- fornecedor, pedido, data e valores.
--   extraido  : o que o robô leu de cada documento ({"pedido": {...}, "comprovante": {...}})
--   correcoes : o que o dono corrigiu por cima (mesmas chaves de dados)
--   dados     : extraido + correcoes, no formato do POST /operacoes
--   pendencias: conferências C1..C8 que falharam, recalculadas a cada mudança
create table caixa.rascunho (
  id               bigserial primary key,
  estado           text        not null default 'pendente'
                   check (estado in ('pendente','aprovado','descartado')),
  extraido         jsonb       not null default '{}',
  correcoes        jsonb       not null default '{}',
  dados            jsonb       not null default '{}',
  pendencias       jsonb       not null default '[]',
  operacao_id      bigint      unique references caixa.operacao(id),
  descarte_motivo  text,
  decidido_em      timestamptz,
  decidido_por     bigint      references caixa.usuario(id),
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),

  constraint aprovado_tem_operacao check ((estado = 'aprovado') = (operacao_id is not null)),
  constraint decidido_tem_data     check ((estado = 'pendente') = (decidido_em is null))
);

create index on caixa.rascunho (estado) where estado = 'pendente';

create trigger tg_evento_rascunho after insert or update or delete on caixa.rascunho
  for each row execute function caixa.registra_evento();

-- documento recebido pelo robô fica ligado ao rascunho até a aprovação
alter table caixa.documento add column rascunho_id bigint references caixa.rascunho(id);
create index on caixa.documento (rascunho_id);

-- Caixa no fim de cada dia em que o aviso rodou: para saber há quantos dias o
-- dinheiro está parado, e para a série histórica do painel.
create table caixa.caixa_diario (
  dia            date          primary key,
  caixa          numeric(14,2) not null,
  aplicado       numeric(14,2) not null,
  capital        numeric(14,2) not null,
  registrado_em  timestamptz   not null default now()
);

-- Alertas. Hoje só de dinheiro parado; a tabela aceita outros.
create table caixa.alerta (
  id          bigserial primary key,
  tipo        text          not null check (tipo in ('caixa_parado')),
  dia         date          not null,         -- o dia de negócio do aviso que gerou o alerta
  mensagem    text          not null,
  valor       numeric(14,2),
  dias        int,
  criado_em   timestamptz   not null default now(),
  baixado_em  timestamptz
);

create index on caixa.alerta (tipo, dia desc);

insert into caixa.parametro (chave, valor, descricao) values
  ('alerta_repetir_dias',     '7',    'Repetir o alerta de caixa parado só depois destes dias...'),
  ('alerta_repetir_variacao', '0.20', '...ou se o valor parado mudar mais que esta fração'),
  ('vence_em_breve_dias',     '3',    'O aviso diário lista o que vence até estes dias à frente'),
  ('telegram_offset',         '0',    'Último update do Telegram já processado (uso interno)');

update caixa.parametro set descricao = 'Telegram chat id do dono (o robô só conversa com ele)'
 where chave = 'alerta_destino';
