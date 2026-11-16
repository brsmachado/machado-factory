-- ---------------------------------------------------------------
-- Caixa Factory — 005: resultado por mês (competência)
-- Fonte: docs/03-formulas.md, seção 5
--
--   select * from caixa.resultado_mes(date '2026-10-01');
--   select * from caixa.resultado_mensal(date '2026-08-01', date '2026-12-01');
--   select * from caixa.resultado_mensal();          -- 1º movimento até último vencimento
--
-- O lucro de cada duplicata é apropriado linearmente nos dias
-- (data_pagamento, fim] — fim = recebida_em ou, se não houver, vencimento.
-- custo_do_parado é custo de oportunidade ("deixou de ganhar"), não prejuízo.
-- ---------------------------------------------------------------
set search_path to caixa, public;

create or replace function caixa.resultado_mes(p_mes date, p_hoje date default current_date)
returns table (
  mes               text,
  dias              int,
  estado            text,        -- fechado | em_curso | projecao
  lucro             numeric,
  aplicado_medio    numeric,
  capital_medio     numeric,
  parado_medio      numeric,
  ocupacao          numeric,
  taxa_mes          numeric,
  taxa_sobre_total  numeric,
  custo_do_parado   numeric
)
language plpgsql stable as $$
declare
  v_ini      date := date_trunc('month', p_mes)::date;
  v_fim      date := (date_trunc('month', p_mes) + interval '1 month - 1 day')::date;
  v_n        int  := v_fim - v_ini + 1;
  v_lucro    numeric := 0;
  v_cap_dia  numeric := 0;
  v_tot_dia  numeric := 0;
  v_aplic    numeric;
  v_capital  numeric;
  v_parado   numeric;
begin
  -- lucro e capital aplicado, dia a dia, por duplicata
  select coalesce(sum(x.lucro_op * x.peso * x.overlap / x.n), 0),
         coalesce(sum(x.pago     * x.peso * x.overlap), 0)
    into v_lucro, v_cap_dia
    from (
      select o.valor_pago                         as pago,
             f.face - o.valor_pago                as lucro_op,
             d.valor / f.face                     as peso,
             greatest(coalesce(d.recebida_em, d.vencimento) - o.data_pagamento, 1) as n,
             least(
               least(coalesce(d.recebida_em, d.vencimento), v_fim)
                 - greatest(o.data_pagamento + 1, v_ini) + 1,
               greatest(coalesce(d.recebida_em, d.vencimento) - o.data_pagamento, 1)
             )                                    as overlap
        from caixa.operacao o
        join caixa.duplicata d on d.operacao_id = o.id
        join (select operacao_id, sum(valor) as face
                from caixa.duplicata group by operacao_id) f on f.operacao_id = o.id
       where o.situacao = 'confirmada'
    ) x
   where x.overlap > 0;

  -- capital total (aportes − retiradas acumulados) em cada dia do mês
  select coalesce(sum(s.saldo), 0) into v_tot_dia
    from generate_series(v_ini, v_fim, interval '1 day') as g(dia)
    cross join lateral (
      select coalesce(sum(case m.tipo when 'aporte' then m.valor else -m.valor end), 0) as saldo
        from caixa.movimento_caixa m
       where m.data <= g.dia::date
    ) s;

  v_aplic   := v_cap_dia / v_n;
  v_capital := v_tot_dia / v_n;
  v_parado  := greatest(0, v_capital - v_aplic);

  mes              := to_char(v_ini, 'YYYY-MM');
  dias             := v_n;
  estado           := case when v_fim < p_hoje then 'fechado'
                           when v_ini > p_hoje then 'projecao'
                           else 'em_curso' end;
  lucro            := round(v_lucro, 2);
  aplicado_medio   := round(v_aplic, 2);
  capital_medio    := round(v_capital, 2);
  parado_medio     := round(v_parado, 2);
  -- divisão por zero vira 0, nunca NaN (docs/03-formulas.md §6)
  ocupacao         := coalesce(v_aplic / nullif(v_capital, 0), 0);
  taxa_mes         := coalesce(v_lucro / nullif(v_aplic,   0), 0) * 30 / v_n;
  taxa_sobre_total := coalesce(v_lucro / nullif(v_capital, 0), 0) * 30 / v_n;
  custo_do_parado  := round(v_parado * coalesce(v_lucro / nullif(v_aplic, 0), 0), 2);
  return next;
end $$;

create or replace function caixa.resultado_mensal(
  p_de   date default null,
  p_ate  date default null,
  p_hoje date default current_date
)
returns table (
  mes text, dias int, estado text, lucro numeric, aplicado_medio numeric,
  capital_medio numeric, parado_medio numeric, ocupacao numeric,
  taxa_mes numeric, taxa_sobre_total numeric, custo_do_parado numeric
)
language sql stable as $$
  with limites as (
    select date_trunc('month', coalesce(p_de,
             (select min(dt) from (select min(data) as dt from caixa.movimento_caixa
                                   union all
                                   select min(data_pagamento) from caixa.operacao
                                    where situacao = 'confirmada') a)))::date as ini,
           date_trunc('month', coalesce(p_ate,
             (select max(coalesce(d.recebida_em, d.vencimento))
                from caixa.duplicata d
                join caixa.operacao o on o.id = d.operacao_id
               where o.situacao = 'confirmada')))::date as fim
  )
  select r.*
    from limites l
    cross join lateral generate_series(l.ini, l.fim, interval '1 month') as g(m)
    cross join lateral caixa.resultado_mes(g.m::date, p_hoje) r
   where l.ini is not null and l.fim is not null
   order by r.mes
$$;
