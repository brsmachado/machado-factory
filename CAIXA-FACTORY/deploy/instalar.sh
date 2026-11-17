#!/usr/bin/env bash
# Caixa Factory — instalação e atualização na VPS (Ubuntu 22.04/24.04).
# Segue docs/08-deploy.md. Pode rodar de novo a qualquer momento: só faz o que falta,
# aplica migrações novas e reinicia os serviços.
#
# Antes, como root na VPS:
#   git clone git@github.com:brsmachado/machado-factory.git /opt/caixa-factory/repo
#   (repositório privado: use uma deploy key do GitHub, só leitura)
#
# Depois:
#   sudo bash /opt/caixa-factory/repo/CAIXA-FACTORY/deploy/instalar.sh caixa.machadoemb.com.br voce@email
#
# O que NÃO faz: mexer no SSH (para não trancar você para fora) e criar o registro A
# na Locaweb — isso é com você (docs/08-deploy.md §1 e §2).
set -euo pipefail

DOMINIO="${1:-}"
EMAIL="${2:-}"
[ "$(id -u)" = 0 ] || { echo "Rode como root (sudo)."; exit 1; }
[ -n "$DOMINIO" ] || { echo "Uso: instalar.sh <dominio> [email-para-o-certificado]"; exit 1; }

BASE=/opt/caixa-factory
REPO=$BASE/repo
APP=$REPO/CAIXA-FACTORY/api
BANCO=$REPO/CAIXA-FACTORY/banco
VENV=$BASE/venv
ENV=$BASE/.env
[ -d "$APP" ] || { echo "Não achei $APP. Clone o repositório em $REPO primeiro."; exit 1; }

passo() { printf '\n== %s\n' "$*"; }

passo "Pacotes e fuso"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q nginx postgresql postgresql-contrib python3-venv python3-pip \
  certbot python3-certbot-nginx fail2ban unattended-upgrades ufw >/dev/null
timedatectl set-timezone America/Sao_Paulo      # senão o aviso das 9h sai às 6h
systemctl enable --now fail2ban >/dev/null

passo "Firewall (SSH continua liberado; Postgres fica fechado)"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

passo "Usuário e pastas"
id caixa >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/caixa --shell /bin/bash caixa
mkdir -p $BASE/documentos $BASE/backups /var/log/caixa
chown -R caixa:caixa $BASE/documentos $BASE/backups /var/log/caixa
chmod 750 $BASE/documentos $BASE/backups
git config --system --add safe.directory $REPO 2>/dev/null || true

passo "Banco (o app entra pelo socket local, sem senha: peer auth do usuário caixa)"
sudo -u postgres psql -qtAc "select 1 from pg_roles where rolname='caixa'" | grep -q 1 \
  || sudo -u postgres psql -qc "create role caixa login"
sudo -u postgres psql -qtAc "select 1 from pg_database where datname='caixa_factory'" | grep -q 1 \
  || sudo -u postgres psql -qc "create database caixa_factory owner caixa"

passo "Python"
[ -d $VENV ] || python3 -m venv $VENV
$VENV/bin/pip install -q --upgrade pip
$VENV/bin/pip install -q -r $APP/requirements.txt

passo ".env"
if [ ! -f $ENV ]; then
  cat > $ENV <<EOF
DATABASE_URL=postgresql:///caixa_factory
DOCUMENTOS_DIR=$BASE/documentos
TZ=America/Sao_Paulo
ROBO_TOKEN=$(openssl rand -hex 32)
# do @BotFather
TELEGRAM_BOT_TOKEN=
# o seu chat com o robô (ele ignora qualquer outro)
TELEGRAM_CHAT_ID=
# seu usuário no sistema: os cliques no Telegram agem como você
TELEGRAM_USUARIO_EMAIL=
# leitura das fotos de pedido e comprovante (Claude)
ANTHROPIC_API_KEY=
EOF
  echo "criado $ENV — preencha Telegram e ANTHROPIC_API_KEY e rode este script de novo"
fi
chown root:caixa $ENV
chmod 640 $ENV

passo "Migrações"
sudo -u caixa env DATABASE_URL=postgresql:///caixa_factory PGOPTIONS="-c client_min_messages=warning" \
  bash $BANCO/aplicar.sh

rodar() {   # roda um comando do app como o usuário caixa, com o .env carregado
  sudo -u caixa bash -c "cd $APP && set -a && . $ENV && set +a && $*"
}
rodar "$VENV/bin/python -m caixa_api.cli criar-robo" >/dev/null

passo "Serviços (API + tela, e o robô do Telegram)"
cat > /etc/systemd/system/caixa-factory.service <<EOF
[Unit]
Description=Caixa Factory — API e tela
After=network.target postgresql.service

[Service]
User=caixa
WorkingDirectory=$APP
EnvironmentFile=$ENV
ExecStart=$VENV/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$BASE/documentos

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/caixa-robo.service <<EOF
[Unit]
Description=Caixa Factory — robô do Telegram
After=network-online.target postgresql.service

[Service]
User=caixa
WorkingDirectory=$APP
EnvironmentFile=$ENV
ExecStart=$VENV/bin/python -m caixa_api.robo telegram
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$BASE/documentos

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable caixa-factory >/dev/null
systemctl restart caixa-factory
if grep -q '^TELEGRAM_BOT_TOKEN=.\+' $ENV && grep -q '^TELEGRAM_CHAT_ID=.\+' $ENV && grep -q '^TELEGRAM_USUARIO_EMAIL=.\+' $ENV; then
  systemctl enable caixa-robo >/dev/null
  systemctl restart caixa-robo
else
  echo "robô do Telegram não iniciado: falta TELEGRAM_* no $ENV"
fi

passo "Nginx"
cat > /etc/nginx/conf.d/caixa-limites.conf <<'EOF'
# no máximo 10 tentativas de login por minuto por IP
limit_req_zone $binary_remote_addr zone=caixa_login:10m rate=10r/m;
EOF
cat > /etc/nginx/sites-available/caixa-factory <<EOF
server {
    listen 80;
    server_name $DOMINIO;
    client_max_body_size 25M;          # comprovantes e PDFs

    location = /api/v1/auth/entrar {
        limit_req zone=caixa_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;       # leitura de documento pelo robô pode levar alguns segundos
    }
}
EOF
ln -sf /etc/nginx/sites-available/caixa-factory /etc/nginx/sites-enabled/caixa-factory
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

passo "HTTPS"
if [ -n "$EMAIL" ] && [ ! -d /etc/letsencrypt/live/$DOMINIO ]; then
  if certbot --nginx -d "$DOMINIO" --agree-tos -m "$EMAIL" --redirect --non-interactive; then
    echo "certificado instalado"
  else
    echo "certbot falhou: confira se o registro A de $DOMINIO já aponta para esta VPS (dig +short $DOMINIO)"
  fi
elif [ -z "$EMAIL" ]; then
  echo "sem e-mail: HTTPS não configurado (rode de novo com o e-mail como 2º argumento)"
fi

passo "Backup diário e aviso das 9h (cron do usuário caixa)"
cat > $BASE/backup.sh <<EOF
#!/usr/bin/env bash
# dados financeiros sem segunda via: banco + documentos, todo dia, 30 dias de histórico
set -euo pipefail
DIA=\$(date +%F)
pg_dump -Fc caixa_factory > $BASE/backups/banco-\$DIA.dump
tar -czf $BASE/backups/documentos-\$DIA.tar.gz -C $BASE documentos
find $BASE/backups -type f -mtime +30 -delete
# copie para FORA da VPS (docs/08-deploy.md §6), por exemplo:
# rsync -az $BASE/backups/ usuario@outro-servidor:/backups/caixa-factory/
EOF
chmod 750 $BASE/backup.sh
chown caixa:caixa $BASE/backup.sh
crontab -u caixa - <<EOF
# Caixa Factory — gerado por deploy/instalar.sh (fuso America/Sao_Paulo)
0 2 * * *    $BASE/backup.sh >> /var/log/caixa/backup.log 2>&1
0 9 * * 1-5  cd $APP && set -a && . $ENV && set +a && $VENV/bin/python -m caixa_api.robo aviso >> /var/log/caixa/robo.log 2>&1
EOF

passo "Conferência"
sleep 2
if curl -fsS http://127.0.0.1:8000/api/v1/saude; then
  echo
else
  echo "a API não respondeu: journalctl -u caixa-factory -n 50"
  exit 1
fi
N=$(sudo -u caixa psql -qtAc "select count(*) from caixa.usuario where papel = 'admin' and ativo" caixa_factory)
OPS=$(sudo -u caixa psql -qtAc "select count(*) from caixa.operacao" caixa_factory)

cat <<EOF

Pronto. Falta, uma vez só:
$( [ "$OPS" = 0 ] && echo "  • carregar os dados de 19/10:  sudo -u caixa bash -c 'cd $APP && $VENV/bin/python $BANCO/carregar_seed.py | psql -q caixa_factory'" )
$( [ "$N" = 0 ] && echo "  • criar o seu login:          sudo -u caixa bash -c 'cd $APP && set -a && . $ENV && set +a && $VENV/bin/python -m caixa_api.cli criar-usuario --nome Bruno --email SEU@EMAIL --papel admin'" )
  • preencher TELEGRAM_* e ANTHROPIC_API_KEY em $ENV e rodar este script de novo
  • testar um restore do backup (docs/08-deploy.md §6)
  • abrir https://$DOMINIO
EOF
