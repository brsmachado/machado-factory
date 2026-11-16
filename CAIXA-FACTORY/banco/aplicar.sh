#!/usr/bin/env bash
# Aplica as migrações de migracoes/ que ainda não rodaram neste banco.
#
#   DATABASE_URL=postgresql://caixa:SENHA@localhost/caixa_factory ./aplicar.sh
#
# Cada arquivo roda numa transação só (tudo ou nada) e fica registrado em
# caixa.migracao_aplicada. Arquivo já aplicado e depois alterado = erro:
# migração publicada não se edita, cria-se uma nova.
set -euo pipefail
export PGOPTIONS="${PGOPTIONS:-} -c client_min_messages=warning"
cd "$(dirname "$0")"
PSQL=(psql "${DATABASE_URL:-}" -X -q -v ON_ERROR_STOP=1)
[ -z "${DATABASE_URL:-}" ] && PSQL=(psql -X -q -v ON_ERROR_STOP=1)

"${PSQL[@]}" <<'SQL'
create schema if not exists caixa;
create table if not exists caixa.migracao_aplicada (
  arquivo     text primary key,
  sha256      text not null,
  aplicada_em timestamptz not null default now()
);
SQL

for f in migracoes/*.sql; do
  nome=$(basename "$f")
  hash=$(sha256sum "$f" | cut -d' ' -f1)
  ja=$("${PSQL[@]}" -tA -c "select sha256 from caixa.migracao_aplicada where arquivo = '$nome'")
  if [ -n "$ja" ]; then
    if [ "$ja" != "$hash" ]; then
      echo "ERRO: $nome já foi aplicada e mudou depois. Crie uma migração nova." >&2
      exit 1
    fi
    continue
  fi
  echo "aplicando $nome"
  { cat "$f"; echo; echo "insert into caixa.migracao_aplicada (arquivo, sha256) values ('$nome', '$hash');"; } \
    | "${PSQL[@]}" -1
done
echo "banco em dia."
