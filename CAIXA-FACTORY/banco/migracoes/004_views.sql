-- ---------------------------------------------------------------
-- Caixa Factory — 004: views de cálculo
-- Fonte: docs/02-modelo-dados.md, seção 4, e docs/03-formulas.md, seções 1 a 4
--
-- Estas views são a implementação de referência das fórmulas. Se a aplicação
-- calcular por conta própria, os resultados têm que bater com elas.
--
-- Diferença em relação ao texto da especificação: em v_operacao a coluna
-- `recebido` já sai com coalesce (nunca nula), e a coluna auxiliar `recebido_`
-- da especificação deixou de existir. Valores em reais saem arredondados a
-- 2 casas em v_caixa (RN-10); taxas saem sem arredondar.
-- ---------------------------------------------------------------
set search_path to caixa, public;

-- Métricas por operação -----------------------------------------
create view caixa.v_operacao as
with base as (
  select o.id,
         o.fornecedor_id, o.numero_pedido, o.numero_nf,
         o.data_pedido, o.data_pagamento, o.valor_pago, o.valor_cheio,
         o.situacao, o.observacoes,
         sum(d.valor)                                                       as face,
         coalesce(sum(d.valor) filter (where d.recebida_em is not null), 0) as recebido,
         count(*)::int                                                      as qt_duplicatas,
         (count(*) filter (where d.recebida_em is null))::int               as qt_abertas,
         (count(*) filter (where d.recebida_em is null
                             and d.vencimento < current_date))::int         as qt_atrasadas,
         min(d.vencimento) filter (where d.recebida_em is null)             as proximo_vencimento,
         -- prazo médio ponderado pelo valor de cada duplicata
         sum(d.valor * greatest(coalesce(d.recebida_em, d.vencimento) - o.data_pagamento, 1))
           / nullif(sum(d.valor), 0)                                        as prazo_medio
    from caixa.operacao o
    join caixa.duplicata d on d.operacao_id = o.id
   where o.situacao = 'confirmada'
   group by o.id
)
select b.*,
       b.face - b.recebido                          as aberto,
       b.face - b.valor_pago                        as lucro,
       (b.face - b.valor_pago) / b.valor_pago       as retorno,     -- taxa do investidor
       (b.face - b.valor_pago) / b.face             as desconto,    -- taxa do fornecedor
       power(1 + (b.face - b.valor_pago) / b.valor_pago,
             30.0  / nullif(b.prazo_medio, 0)) - 1  as taxa_mes,
       power(1 + (b.face - b.valor_pago) / b.valor_pago,
             365.0 / nullif(b.prazo_medio, 0)) - 1  as taxa_ano,
       case
         when b.face - b.recebido <= 0.005 then 'encerrada'
         when b.recebido > 0.005           then 'parcial'
         when b.qt_atrasadas > 0           then 'atrasada'
         else 'em_aberto'
       end                                          as estado,
       b.qt_atrasadas > 0                           as atrasada     -- flag independente
  from base b;

comment on view caixa.v_operacao is
  'Métricas por operação confirmada (docs/03-formulas.md §1). retorno = lucro/pago; desconto = lucro/face.';

-- Posição do caixa ----------------------------------------------
create view caixa.v_caixa as
with mov as (
  select coalesce(sum(valor) filter (where tipo = 'aporte'),   0) as aportes,
         coalesce(sum(valor) filter (where tipo = 'retirada'), 0) as retiradas
    from caixa.movimento_caixa
), op as (
  select coalesce(sum(valor_pago), 0)                                       as pago_total,
         coalesce(sum(recebido), 0)                                         as recebido_total,
         coalesce(sum(valor_pago * aberto / nullif(face, 0)), 0)            as aplicado,
         coalesce(sum(aberto), 0)                                           as a_receber,
         coalesce(sum(recebido - valor_pago * recebido / nullif(face, 0)), 0) as lucro_realizado,
         coalesce(sum(aberto   - valor_pago * aberto   / nullif(face, 0)), 0) as lucro_a_receber,
         coalesce(sum(qt_abertas), 0)::int                                  as duplicatas_abertas,
         (count(*) filter (where aberto > 0.005))::int                      as operacoes_abertas
    from caixa.v_operacao
)
select mov.aportes,
       mov.retiradas,
       round(mov.aportes - mov.retiradas - op.pago_total + op.recebido_total, 2)  as caixa,
       round(op.aplicado, 2)                                                      as aplicado,
       round(mov.aportes - mov.retiradas - op.pago_total + op.recebido_total
             + op.aplicado, 2)                                                    as capital,
       round(op.a_receber, 2)                                                     as a_receber,
       round(op.lucro_realizado, 2)                                               as lucro_realizado,
       round(op.lucro_a_receber, 2)                                               as lucro_a_receber,
       op.duplicatas_abertas,
       op.operacoes_abertas
  from mov, op;

comment on view caixa.v_caixa is
  'Posição do caixa (docs/03-formulas.md §2). Identidade: caixa + aplicado = aportes - retiradas + lucro_realizado.';

-- Rentabilidade da carteira -------------------------------------
-- docs/03-formulas.md §3 e o bloco "rentabilidade" de GET /resumo
create view caixa.v_carteira as
with t as (
  select coalesce(sum(valor_pago), 0)                                as pago_total,
         coalesce(sum(lucro), 0)                                     as lucro_total,
         sum(valor_pago * prazo_medio) / nullif(sum(valor_pago), 0)  as prazo_medio,
         coalesce(sum(valor_pago * taxa_mes), 0)                     as lucro_mes_reais
    from caixa.v_operacao
), r as (
  select t.*,
         coalesce(t.lucro_total / nullif(t.pago_total, 0), 0) as retorno
    from t
)
select r.pago_total,
       r.lucro_total,
       r.retorno,
       r.prazo_medio                                                   as prazo_medio_dias,
       coalesce(power(1 + r.retorno, 30.0  / nullif(r.prazo_medio, 0)) - 1, 0) as taxa_mes,
       coalesce(power(1 + r.retorno, 365.0 / nullif(r.prazo_medio, 0)) - 1, 0) as taxa_ano,
       round(r.lucro_mes_reais, 2)                                     as lucro_mes_reais,
       coalesce(c.aplicado / nullif(c.capital, 0), 0)                  as ocupacao,
       coalesce(power(1 + r.retorno, 30.0 / nullif(r.prazo_medio, 0)) - 1, 0)
         * coalesce(c.aplicado / nullif(c.capital, 0), 0)              as rendimento_caixa_inteiro
  from r, caixa.v_caixa c;

comment on view caixa.v_carteira is
  'Rentabilidade da carteira (docs/03-formulas.md §3). rendimento_caixa_inteiro = taxa_mes × ocupação.';

-- Agenda de retornos --------------------------------------------
-- docs/03-formulas.md §4. A janela (parametro dias_agenda) é filtro da API.
create view caixa.v_agenda as
select d.id,
       d.operacao_id,
       f.nome                                  as fornecedor,
       o.numero_pedido,
       d.sequencia,
       (select count(*) from caixa.duplicata x where x.operacao_id = d.operacao_id)::int as de,
       d.valor,
       d.vencimento,
       d.vencimento - current_date             as dias_para_vencer,
       d.vencimento < current_date             as atrasada
  from caixa.duplicata d
  join caixa.operacao  o on o.id = d.operacao_id
  join caixa.fornecedor f on f.id = o.fornecedor_id
 where o.situacao = 'confirmada'
   and d.recebida_em is null
 order by d.vencimento, d.id;
