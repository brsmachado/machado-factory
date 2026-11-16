-- ---------------------------------------------------------------
-- Testes do banco. Rodam sobre a carga de 19/10/2026 e desfazem tudo no fim.
-- Use testes/rodar.sh, que cria um banco descartável.
-- Cada falha aborta com a mensagem do que não bateu.
-- ---------------------------------------------------------------
\set ON_ERROR_STOP 1
set client_min_messages = warning;
begin;
set search_path to caixa, public;

-- helpers -------------------------------------------------------
create function pg_temp.igual(nome text, veio numeric, esperado numeric, tol numeric default 0)
returns void language plpgsql as $$
begin
  if veio is null or abs(veio - esperado) > tol then
    raise exception 'FALHOU %: esperado %, veio %', nome, esperado, veio;
  end if;
end $$;

-- roda o comando, força as triggers deferred e exige um erro contendo `trecho`
create function pg_temp.espera_erro(nome text, cmd text, trecho text)
returns void language plpgsql as $$
declare msg text;
begin
  begin
    execute cmd;
    set constraints all immediate;
  exception when others then
    get stacked diagnostics msg = message_text;
    if position(trecho in msg) = 0 then
      raise exception 'FALHOU %: erro diferente do esperado: %', nome, msg;
    end if;
    return;   -- o bloco com exceção já desfez o que o comando fez
  end;
  raise exception 'FALHOU %: deveria ter dado erro (%)', nome, trecho;
end $$;

-- roda o comando, força as triggers deferred e exige que passe
create function pg_temp.passa(nome text, cmd text)
returns void language plpgsql as $$
declare msg text;
begin
  execute cmd;
  set constraints all immediate;
  set constraints all deferred;
exception when others then
  get stacked diagnostics msg = message_text;
  raise exception 'FALHOU %: %', nome, msg;
end $$;

-- 1. conferência pós-carga (docs/07-migracao.md §5) ------------
select pg_temp.igual('caixa',           caixa,           111810.32) from v_caixa;
select pg_temp.igual('aplicado',        aplicado,         42032.64) from v_caixa;
select pg_temp.igual('capital',         capital,         153842.96) from v_caixa;
select pg_temp.igual('a_receber',       a_receber,        43843.56) from v_caixa;
select pg_temp.igual('lucro_realizado', lucro_realizado,   3842.96) from v_caixa;
select pg_temp.igual('lucro_a_receber', lucro_a_receber,   1810.92) from v_caixa;
select pg_temp.igual('duplicatas_abertas', duplicatas_abertas, 4)   from v_caixa;
select pg_temp.igual('identidade', caixa + aplicado, aportes - retiradas + lucro_realizado) from v_caixa;

-- 2. rentabilidade da carteira (docs/03-formulas.md §3) --------
select pg_temp.igual('carteira taxa_mes',  round(taxa_mes, 4), 0.0326)  from v_carteira;
select pg_temp.igual('carteira lucro_mes', lucro_mes_reais,    4965.73) from v_carteira;
select pg_temp.igual('carteira ocupacao',  round(ocupacao, 3), 0.273)   from v_carteira;
select pg_temp.igual('rendimento caixa inteiro', round(rendimento_caixa_inteiro, 4), 0.0089) from v_carteira;

-- 3. exemplos conferidos por operação (docs/03-formulas.md §1) -
select pg_temp.igual('03282-2 lucro',    lucro,                 1958.40),
       pg_temp.igual('03282-2 retorno',  round(retorno, 6),     0.030928),
       pg_temp.igual('03282-2 desconto', round(desconto, 6),    0.030000),
       pg_temp.igual('03282-2 prazo',    prazo_medio,           35),
       pg_temp.igual('03282-2 taxa_mes', round(taxa_mes, 6),    0.026452),
       pg_temp.igual('03282-2 taxa_ano', round(taxa_ano, 4),    0.3738, 0.0001),  -- doc trunca 0,37388
       pg_temp.igual('03282-2 lucro/mês', round(valor_pago * taxa_mes, 2), 1674.96, 0.01)
  from v_operacao where numero_pedido = 'PC 03282-2/26';

select pg_temp.igual('03273-2 retorno',  round(retorno, 6),  0.041667),
       pg_temp.igual('03273-2 desconto', round(desconto, 6), 0.040000),
       pg_temp.igual('03273-2 prazo',    prazo_medio,        27),
       pg_temp.igual('03273-2 taxa_mes', round(taxa_mes, 6), 0.046402)
  from v_operacao where numero_pedido = 'PC 03273-2/26';

-- 4. resultado por mês (docs/03-formulas.md §5) ----------------
select pg_temp.igual(r.mes || ' lucro',    r.lucro,          e.lucro),
       pg_temp.igual(r.mes || ' aplicado', r.aplicado_medio, e.aplicado),
       pg_temp.igual(r.mes || ' parado',   r.parado_medio,   e.parado),
       pg_temp.igual(r.mes || ' custo',    r.custo_do_parado, e.custo)
  from resultado_mensal(p_hoje => date '2026-10-19') r
  join (values ('2026-08',  249.90,   8936.52,   3966.71,  110.92),
               ('2026-09', 3200.32, 103260.88,  21739.12,  673.75),
               ('2026-10', 2108.57,  56379.73,  93620.27, 3501.35),
               ('2026-11',   95.09,   2053.92, 147946.08, 6849.36))
       as e(mes, lucro, aplicado, parado, custo) on e.mes = r.mes;

do $$ begin
  if (select count(*) from resultado_mensal(p_hoje => date '2026-10-19')) <> 4 then
    raise exception 'FALHOU resultado_mensal: esperava 4 meses (ago a nov)';
  end if;
  if (select estado from resultado_mes(date '2026-10-01', date '2026-10-19')) <> 'em_curso'
  or (select estado from resultado_mes(date '2026-09-01', date '2026-10-19')) <> 'fechado'
  or (select estado from resultado_mes(date '2026-11-01', date '2026-10-19')) <> 'projecao' then
    raise exception 'FALHOU estado do mês';
  end if;
  -- mês sem nada: zeros, nunca NaN nem erro
  if (select taxa_mes from resultado_mes(date '2026-01-01')) <> 0 then
    raise exception 'FALHOU mês vazio';
  end if;
end $$;

-- 5. RN-01 — soma das duplicatas -------------------------------
select pg_temp.espera_erro('RN-01 soma errada', $$
  with o as (insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio)
             values (1, 'T-01', '2026-10-20', 900, 1000) returning id)
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, 1, 999.99, '2026-11-20' from o $$, 'Duplicatas somam');

select pg_temp.espera_erro('RN-01 confirmada sem duplicata', $$
  insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio)
  values (1, 'T-02', '2026-10-20', 900, 1000) $$, 'Duplicatas somam');

select pg_temp.espera_erro('RN-01 mudar valor_cheio', $$
  update operacao set valor_cheio = valor_cheio + 1 where numero_pedido = 'PC 03273-2/26' $$,
  'Duplicatas somam');

select pg_temp.espera_erro('RN-01 mudar valor da duplicata', $$
  update duplicata set valor = valor - 0.01 where id = (select min(id) from duplicata) $$,
  'Duplicatas somam');

select pg_temp.passa('RN-01 três duplicatas, última absorve o centavo', $$
  with o as (insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio)
             values (1, 'T-03', '2026-10-20', 9600, 10000) returning id)
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, s, v, d::date from o,
    (values (1, 3333.33, '2026-11-20'), (2, 3333.33, '2026-11-30'), (3, 3333.34, '2026-12-10')) x(s, v, d) $$);

select pg_temp.passa('rascunho pode ficar incompleto', $$
  insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio, situacao, origem)
  values (2, 'T-04', '2026-10-20', 900, 1000, 'rascunho', 'robo') $$);

select pg_temp.espera_erro('confirmar rascunho incompleto', $$
  update operacao set situacao = 'confirmada' where numero_pedido = 'T-04' $$, 'Duplicatas somam');

-- 6. RN-02 — pago não passa do cheio ---------------------------
select pg_temp.espera_erro('RN-02', $$
  insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio, situacao)
  values (1, 'T-05', '2026-10-20', 1000.01, 1000, 'rascunho') $$, 'pago_nao_passa_do_cheio');

-- 7. RN-03 — não se compra sem caixa ---------------------------
-- caixa agora: 111.810,32 − 9.600 da T-03 = 102.210,32
select pg_temp.espera_erro('RN-03 compra maior que o caixa', $$
  with o as (insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio)
             values (1, 'T-06', '2026-10-20', 102210.33, 110000) returning id)
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, 1, 110000, '2026-11-20' from o $$, 'você tem R$ 102.210,32 livre');

select pg_temp.passa('RN-03 compra exatamente do tamanho do caixa', $$
  with o as (insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio)
             values (1, 'T-07', '2026-10-20', 102210.32, 110000) returning id)
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, 1, 110000, '2026-11-20' from o $$);

-- caixa agora: 0. Editar a própria operação sem aumentar o pago tem que passar
select pg_temp.passa('RN-03 editar a própria operação com caixa zero', $$
  update operacao set observacoes = 'editada', valor_pago = valor_pago - 10 where numero_pedido = 'T-07' $$);
select pg_temp.espera_erro('RN-03 editar aumentando além do caixa', $$
  update operacao set valor_pago = valor_pago + 10.01 where numero_pedido = 'T-07' $$, 'Caixa insuficiente');

select pg_temp.espera_erro('RN-03 confirmar rascunho sem caixa', $$
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, 1, 1000, '2026-11-20' from operacao where numero_pedido = 'T-04';
  update operacao set situacao = 'confirmada' where numero_pedido = 'T-04' $$, 'Caixa insuficiente');

-- 8. RN-05 — retirada limitada ao caixa (caixa agora: 10,00) ---
select pg_temp.espera_erro('RN-05 retirada maior que o caixa', $$
  insert into movimento_caixa (tipo, data, valor) values ('retirada', '2026-10-21', 10.01) $$,
  'Caixa insuficiente');
select pg_temp.espera_erro('RN-05 apagar aporte já usado', $$
  delete from movimento_caixa where id = 2 $$, 'Caixa insuficiente');
select pg_temp.passa('RN-05 retirada igual ao caixa', $$
  insert into movimento_caixa (tipo, data, valor) values ('retirada', '2026-10-21', 10.00) $$);

-- 9. RN-04 — recebimento não vem antes do pagamento ------------
select pg_temp.espera_erro('RN-04 receber antes de pagar', $$
  update duplicata set recebida_em = '2026-10-18'
   where operacao_id = (select id from operacao where numero_pedido = 'PC 03273-2/26') $$,
  'anterior ao pagamento');
select pg_temp.espera_erro('RN-04 mover pagamento para depois do recebimento', $$
  update operacao set data_pagamento = '2026-09-27' where numero_pedido = 'PC 03282-2/26' $$,
  'fica depois de um recebimento');
select pg_temp.passa('RN-04 antecipação é normal', $$
  update duplicata set recebida_em = '2026-10-20'
   where operacao_id = (select id from operacao where numero_pedido = 'PC 03273-2/26') $$);

-- 10. A-02 — ano implausível -----------------------------------
select pg_temp.espera_erro('A-02 vencimento em 2025', $$
  insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio, situacao)
  values (2, 'T-08', '2026-09-04', 1, 1, 'rascunho');
  insert into duplicata (operacao_id, sequencia, valor, vencimento)
  select id, 1, 1, '2025-10-06' from operacao where numero_pedido = 'T-08' $$, 'vencimento_plausivel');

-- 11. RN-06 — o que tem recebimento não se apaga ---------------
select pg_temp.espera_erro('RN-06 apagar operação recebida', $$
  delete from duplicata where operacao_id = 1 and recebida_em is null;
  delete from operacao where id = 1 $$, 'use estorno');
select pg_temp.espera_erro('RN-06 apagar duplicata recebida', $$
  delete from duplicata where id = 1 $$, 'desfaça o recebimento');

-- 12. ciclo de vida e estorno ----------------------------------
select pg_temp.espera_erro('confirmada não volta a rascunho', $$
  update operacao set situacao = 'rascunho' where id = 7 $$, 'não volta a rascunho');
select pg_temp.espera_erro('estorno sem motivo', $$
  update operacao set situacao = 'estornada', estornada_em = now() where id = 6 $$, 'estorno_completo');

insert into usuario (id, nome, email, senha_hash, papel)
values (900, 'Teste', 'teste@exemplo.invalid', 'x', 'admin');
set local caixa.usuario_id = '900';

-- caixa antes: 0 + 4.279,00 recebidos antecipados da 03273-2. T-03 sai de todos
-- os cálculos: o caixa ganha de volta os 9.600 dela
select pg_temp.passa('estornar', $$
  update operacao set situacao = 'estornada', estornada_em = now(), estorno_motivo = 'teste'
   where numero_pedido = 'T-03' $$);
select pg_temp.igual('estorno devolve o caixa', caixa, 4279.00 + 9600.00) from v_caixa;
select pg_temp.igual('identidade depois do estorno', caixa + aplicado,
                     aportes - retiradas + lucro_realizado) from v_caixa;
select pg_temp.espera_erro('estornada fica congelada', $$
  update operacao set observacoes = 'x' where numero_pedido = 'T-03' $$, 'está estornada');
select pg_temp.espera_erro('duplicata de estornada fica congelada', $$
  update duplicata set recebida_em = '2026-11-20'
   where operacao_id = (select id from operacao where numero_pedido = 'T-03') $$, 'operação estornada');

-- 13. auditoria ------------------------------------------------
select pg_temp.passa('desfazer recebimento', $$
  update duplicata set recebida_em = null where id = 1 $$);
do $$ begin
  if not exists (select 1 from evento where entidade = 'duplicata' and entidade_id = 1
                    and acao = 'desfez' and usuario_id = 900
                    and antes->>'recebida_em' = '2026-09-26' and depois->>'recebida_em' is null) then
    raise exception 'FALHOU auditoria: desfazer não foi registrado';
  end if;
  if not exists (select 1 from evento where entidade = 'duplicata' and acao = 'recebeu' and usuario_id is null) then
    raise exception 'FALHOU auditoria: recebimento não foi registrado';
  end if;
  if not exists (select 1 from evento where entidade = 'operacao' and acao = 'estornou' and usuario_id = 900) then
    raise exception 'FALHOU auditoria: estorno não foi registrado';
  end if;
  if exists (select 1 from evento where entidade = 'usuario' and (depois ? 'senha_hash')) then
    raise exception 'FALHOU auditoria: senha_hash foi parar no log';
  end if;
end $$;
-- desfazer recebimento é correção e não é barrado, mesmo deixando o caixa negativo
select pg_temp.igual('desfazer pode deixar caixa negativo', caixa, 4279.00 + 9600.00 - 32640.00) from v_caixa;

select pg_temp.espera_erro('log não se altera', $$ update evento set acao = 'x' $$, 'não pode ser alterado');
select pg_temp.espera_erro('log não se apaga',  $$ delete from evento $$,           'não pode ser alterado');

-- 14. unicidade ------------------------------------------------
select pg_temp.espera_erro('pedido repetido no mesmo fornecedor', $$
  insert into operacao (fornecedor_id, numero_pedido, data_pagamento, valor_pago, valor_cheio, situacao)
  values (1, 'PC 03282-2/26', '2026-10-20', 1, 1, 'rascunho') $$, 'pedido_unico_por_fornecedor');

select 'todos os testes passaram' as resultado;
rollback;
