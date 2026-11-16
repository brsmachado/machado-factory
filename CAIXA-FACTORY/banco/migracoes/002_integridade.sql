-- ---------------------------------------------------------------
-- Caixa Factory — 002: regras de integridade no banco
-- Fonte: docs/02-modelo-dados.md, seção 3, e docs/01-dominio.md, seção 4
--
-- Além do que está na especificação, este arquivo fecha quatro brechas:
--   * RN-01 também é checada quando a OPERAÇÃO muda (valor_cheio, confirmação),
--     e quando uma operação confirmada é criada sem nenhuma duplicata;
--   * RN-04 também é checada quando a data_pagamento da operação muda;
--   * RN-03 / RN-05: o caixa disponível nunca fica negativo depois de uma
--     compra, edição de compra ou movimento de caixa;
--   * operação estornada fica congelada (ela e as duplicatas dela).
-- ---------------------------------------------------------------
set search_path to caixa, public;

-- Formata dinheiro para mensagem de erro: 111810.32 -> 'R$ 111.810,32'
create or replace function caixa.fmt_brl(v numeric) returns text
language sql immutable as $$
  select 'R$ ' || translate(to_char(round(v, 2), 'FM999,999,999,990.00'), ',.', '.,')
$$;

-- Caixa disponível (docs/03-formulas.md, seção 2), direto das tabelas.
-- Só operações confirmadas contam: rascunho ainda não saiu do bolso,
-- estornada sai de todos os cálculos.
create or replace function caixa.caixa_disponivel() returns numeric
language sql stable as $$
  select (select coalesce(sum(case tipo when 'aporte' then valor else -valor end), 0)
            from caixa.movimento_caixa)
       - (select coalesce(sum(valor_pago), 0)
            from caixa.operacao where situacao = 'confirmada')
       + (select coalesce(sum(d.valor), 0)
            from caixa.duplicata d
            join caixa.operacao o on o.id = d.operacao_id
           where o.situacao = 'confirmada' and d.recebida_em is not null)
$$;

-- RN-01 — a soma das duplicatas tem que fechar --------------------
create or replace function caixa.checa_soma_duplicatas(p_op bigint) returns void
language plpgsql as $$
declare
  v_soma  numeric(14,2);
  v_cheio numeric(14,2);
  v_sit   text;
  v_ped   text;
begin
  select valor_cheio, situacao, numero_pedido into v_cheio, v_sit, v_ped
    from caixa.operacao where id = p_op;

  -- operação apagada na mesma transação, ou rascunho (pode estar incompleto),
  -- ou estornada (descarte de rascunho incompleto é estorno também)
  if not found or v_sit <> 'confirmada' then return; end if;

  select coalesce(sum(valor), 0) into v_soma
    from caixa.duplicata where operacao_id = p_op;

  if v_soma <> v_cheio then
    raise exception 'Duplicatas somam % e o valor cheio é % (operação %, %)',
      caixa.fmt_brl(v_soma), caixa.fmt_brl(v_cheio), p_op, v_ped
      using errcode = 'check_violation', constraint = 'rn01_soma_duplicatas';
  end if;
end $$;

create or replace function caixa.tg_soma_duplicatas_duplicata() returns trigger
language plpgsql as $$
begin
  if tg_op in ('UPDATE','DELETE') then perform caixa.checa_soma_duplicatas(old.operacao_id); end if;
  if tg_op in ('UPDATE','INSERT') and (tg_op = 'INSERT' or new.operacao_id <> old.operacao_id) then
    perform caixa.checa_soma_duplicatas(new.operacao_id);
  end if;
  return null;
end $$;

create or replace function caixa.tg_soma_duplicatas_operacao() returns trigger
language plpgsql as $$
begin
  perform caixa.checa_soma_duplicatas(new.id);
  return null;
end $$;

-- deferred: operação e duplicatas entram na mesma transação; valida no commit
create constraint trigger tg_soma_duplicatas
  after insert or update or delete on caixa.duplicata
  deferrable initially deferred
  for each row execute function caixa.tg_soma_duplicatas_duplicata();

create constraint trigger tg_soma_duplicatas_op
  after insert or update of valor_cheio, situacao on caixa.operacao
  deferrable initially deferred
  for each row execute function caixa.tg_soma_duplicatas_operacao();

-- RN-04 — recebimento não vem antes do pagamento ------------------
create or replace function caixa.valida_recebimento() returns trigger
language plpgsql as $$
declare v_pag date;
begin
  if new.recebida_em is null then return new; end if;
  select data_pagamento into v_pag from caixa.operacao where id = new.operacao_id;
  if new.recebida_em < v_pag then
    raise exception 'Recebimento em % é anterior ao pagamento em %',
      to_char(new.recebida_em, 'DD/MM/YYYY'), to_char(v_pag, 'DD/MM/YYYY')
      using errcode = 'check_violation', constraint = 'rn04_recebimento_apos_pagamento';
  end if;
  return new;
end $$;

create trigger tg_valida_recebimento
  before insert or update of recebida_em, operacao_id on caixa.duplicata
  for each row execute function caixa.valida_recebimento();

create or replace function caixa.valida_data_pagamento() returns trigger
language plpgsql as $$
declare v_min date;
begin
  select min(recebida_em) into v_min from caixa.duplicata where operacao_id = new.id;
  if v_min is not null and v_min < new.data_pagamento then
    raise exception 'Pagamento em % fica depois de um recebimento já lançado em %',
      to_char(new.data_pagamento, 'DD/MM/YYYY'), to_char(v_min, 'DD/MM/YYYY')
      using errcode = 'check_violation', constraint = 'rn04_recebimento_apos_pagamento';
  end if;
  return new;
end $$;

create trigger tg_valida_data_pagamento
  before update of data_pagamento on caixa.operacao
  for each row execute function caixa.valida_data_pagamento();

-- RN-03 / RN-05 — não se compra nem se retira sem caixa -----------
-- Checa o caixa DEPOIS da mudança. Isso já cobre a regra de edição da RN-03
-- (caixa + valor_pago_anterior − já recebido): a própria operação editada
-- entra na conta com o valor novo, não em dobro.
-- Desfazer recebimento NÃO é barrado: corrigir um lançamento errado tem que
-- ser possível mesmo que o caixa fique negativo — aí a tela mostra o buraco.
create or replace function caixa.checa_caixa() returns trigger
language plpgsql as $$
declare v_caixa numeric;
begin
  -- só interessa o que tira dinheiro: compra confirmada ou retirada / aporte desfeito
  if tg_table_name = 'operacao' then
    if new.situacao <> 'confirmada' then return null; end if;
  end if;

  v_caixa := caixa.caixa_disponivel();
  if v_caixa < 0 then
    if tg_table_name = 'operacao' then
      raise exception 'Caixa insuficiente: faltam % para esta compra (você tem % livre). Registre um aporte antes de lançar esta compra.',
        caixa.fmt_brl(-v_caixa), caixa.fmt_brl(new.valor_pago + v_caixa)
        using errcode = 'check_violation', constraint = 'rn03_caixa_suficiente';
    else
      raise exception 'Caixa insuficiente: o movimento deixaria o caixa em %. O capital na rua não pode ser sacado antes de voltar.',
        caixa.fmt_brl(v_caixa)
        using errcode = 'check_violation', constraint = 'rn05_retirada_limitada';
    end if;
  end if;
  return null;
end $$;

create constraint trigger tg_caixa_operacao
  after insert or update of valor_pago, situacao on caixa.operacao
  deferrable initially deferred
  for each row execute function caixa.checa_caixa();

create constraint trigger tg_caixa_movimento
  after insert or update or delete on caixa.movimento_caixa
  deferrable initially deferred
  for each row execute function caixa.checa_caixa();

-- Ciclo de vida da operação ---------------------------------------
-- rascunho -> confirmada | estornada ; confirmada -> estornada ; estornada é final
create or replace function caixa.valida_situacao() returns trigger
language plpgsql as $$
begin
  if old.situacao = 'estornada' then
    raise exception 'Operação % está estornada e não pode mais ser alterada', old.id
      using errcode = 'check_violation', constraint = 'operacao_estornada_congelada';
  end if;
  if old.situacao = 'confirmada' and new.situacao = 'rascunho' then
    raise exception 'Operação % já foi confirmada e não volta a rascunho: use estorno', old.id
      using errcode = 'check_violation', constraint = 'ciclo_de_vida';
  end if;
  new.atualizado_em := now();
  return new;
end $$;

create trigger tg_valida_situacao
  before update on caixa.operacao
  for each row execute function caixa.valida_situacao();

create or replace function caixa.protege_duplicata_estornada() returns trigger
language plpgsql as $$
begin
  if exists (select 1 from caixa.operacao
              where id in (coalesce(new.operacao_id, old.operacao_id), old.operacao_id)
                and situacao = 'estornada') then
    raise exception 'Duplicata de operação estornada não pode ser alterada'
      using errcode = 'check_violation', constraint = 'operacao_estornada_congelada';
  end if;
  return coalesce(new, old);
end $$;

create trigger tg_protege_duplicata_estornada
  before insert or update or delete on caixa.duplicata
  for each row execute function caixa.protege_duplicata_estornada();

-- RN-06 — não apagar o que tem dinheiro recebido ------------------
create or replace function caixa.protege_operacao() returns trigger
language plpgsql as $$
begin
  if exists (select 1 from caixa.duplicata
             where operacao_id = old.id and recebida_em is not null) then
    raise exception 'Operação % tem duplicata recebida: use estorno, não exclusão', old.id
      using errcode = 'restrict_violation', constraint = 'rn06_sem_exclusao_com_recebimento';
  end if;
  return old;
end $$;

create trigger tg_protege_operacao
  before delete on caixa.operacao
  for each row execute function caixa.protege_operacao();

create or replace function caixa.protege_duplicata_recebida() returns trigger
language plpgsql as $$
begin
  if old.recebida_em is not null then
    raise exception 'Duplicata % já foi recebida: desfaça o recebimento antes de excluir', old.id
      using errcode = 'restrict_violation', constraint = 'rn06_sem_exclusao_com_recebimento';
  end if;
  return old;
end $$;

create trigger tg_protege_duplicata_recebida
  before delete on caixa.duplicata
  for each row execute function caixa.protege_duplicata_recebida();
