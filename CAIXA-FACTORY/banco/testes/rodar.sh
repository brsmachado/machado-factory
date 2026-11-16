#!/usr/bin/env bash
# Cria um banco descartável, aplica as migrações, carrega o seed real,
# roda testes.sql e apaga o banco. Usa as variáveis PG* do ambiente
# (PGHOST, PGPORT, PGUSER) e precisa de permissão para criar banco.
#
#   PGHOST=localhost PGUSER=postgres ./testes/rodar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PGOPTIONS="${PGOPTIONS:-} -c client_min_messages=warning"
DB="caixa_teste_$$"
createdb "$DB"
trap 'dropdb --if-exists "$DB"' EXIT
export PGDATABASE="$DB"
unset DATABASE_URL
./aplicar.sh >/dev/null
python3 carregar_seed.py | psql -X -q -v ON_ERROR_STOP=1 -tA >/dev/null
psql -X -q -v ON_ERROR_STOP=1 -tA -f testes/testes.sql | tail -n 1
