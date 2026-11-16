-- ---------------------------------------------------------------
-- Caixa Factory — 003: auditoria automática
-- Fonte: docs/02-modelo-dados.md, seção 3 ("Auditoria automática")
--
-- A API faz `set local caixa.usuario_id = '<id>'` no início de cada transação
-- para o log saber quem agiu.
--
-- A ação gravada usa o vocabulário do domínio, não o do SQL:
--   insert -> 'criou', delete -> 'excluiu', update -> 'alterou', e ainda
--   duplicata com recebida_em  null -> data  : 'recebeu'
--   duplicata com recebida_em  data -> null  : 'desfez'
--   operação rascunho -> confirmada          : 'confirmou'
--   operação * -> estornada                  : 'estornou'
-- ---------------------------------------------------------------
set search_path to caixa, public;

create or replace function caixa.registra_evento() returns trigger
language plpgsql as $$
declare
  v_antes  jsonb := case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) - 'senha_hash' end;
  v_depois jsonb := case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) - 'senha_hash' end;
  v_acao   text  := case tg_op when 'INSERT' then 'criou' when 'DELETE' then 'excluiu' else 'alterou' end;
begin
  if tg_op = 'UPDATE' then
    -- nada mudou de fato (só atualizado_em): não polui o log
    if (v_antes - 'atualizado_em') = (v_depois - 'atualizado_em') then return new; end if;

    if tg_table_name = 'duplicata' then
      if old.recebida_em is null and new.recebida_em is not null then v_acao := 'recebeu';
      elsif old.recebida_em is not null and new.recebida_em is null then v_acao := 'desfez';
      end if;
    elsif tg_table_name = 'operacao' then
      if new.situacao = 'estornada' and old.situacao <> 'estornada' then v_acao := 'estornou';
      elsif old.situacao = 'rascunho' and new.situacao = 'confirmada' then v_acao := 'confirmou';
      end if;
    end if;
  end if;

  insert into caixa.evento (entidade, entidade_id, acao, antes, depois, usuario_id)
  values (
    tg_table_name,
    coalesce(new.id, old.id),
    v_acao,
    v_antes,
    v_depois,
    nullif(current_setting('caixa.usuario_id', true), '')::bigint
  );
  return coalesce(new, old);
end $$;

create trigger tg_evento_operacao   after insert or update or delete on caixa.operacao
  for each row execute function caixa.registra_evento();
create trigger tg_evento_duplicata  after insert or update or delete on caixa.duplicata
  for each row execute function caixa.registra_evento();
create trigger tg_evento_movimento  after insert or update or delete on caixa.movimento_caixa
  for each row execute function caixa.registra_evento();
create trigger tg_evento_fornecedor after insert or update or delete on caixa.fornecedor
  for each row execute function caixa.registra_evento();
create trigger tg_evento_documento  after insert or update or delete on caixa.documento
  for each row execute function caixa.registra_evento();
create trigger tg_evento_usuario    after insert or update or delete on caixa.usuario
  for each row execute function caixa.registra_evento();

-- O log só cresce: ninguém altera nem apaga evento ----------------
create or replace function caixa.evento_somente_inclusao() returns trigger
language plpgsql as $$
begin
  raise exception 'O log de eventos não pode ser alterado nem apagado'
    using errcode = 'insufficient_privilege';
end $$;

create trigger tg_evento_imutavel
  before update or delete on caixa.evento
  for each row execute function caixa.evento_somente_inclusao();

create trigger tg_evento_sem_truncate
  before truncate on caixa.evento
  for each statement execute function caixa.evento_somente_inclusao();
