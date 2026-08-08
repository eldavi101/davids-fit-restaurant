#!/usr/bin/env bash
# Equity Signal Tracker — one-command backend setup.
#
#   ./scripts/setup.sh
#
# Creates .env (with freshly generated secrets), starts Postgres and the API, fills the
# database with real market data, and prints the two values to type into the app's
# Settings screen.
#
# The script never writes a credential anywhere except .env, which is git-ignored. The
# market-data key is read without echo and is never printed back.

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
COMPOSE="docker compose"

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '\n\033[1m%s\033[0m\n' "$*"; }

command -v docker >/dev/null 2>&1 || die "docker is not installed. See https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"
$COMPOSE version >/dev/null 2>&1 || die "docker compose is not available"

random_secret() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 32
	else
		head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
	fi
}

# ---------------------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------------------

if [[ -f "$ENV_FILE" ]]; then
	note "$ENV_FILE already exists — keeping it. Delete it first if you want a clean setup."
else
	note "Creating $ENV_FILE"

	echo
	echo "Which market-data provider will this deployment use?"
	echo "  1) polygon       2) finnhub       3) fmp"
	echo "  4) twelvedata    5) alphavantage  6) synthetic (generated data, no key needed)"
	read -r -p "Choice [1-6]: " choice

	case "$choice" in
		1) provider=polygon;      key_var=POLYGON_API_KEY;      rate=100 ;;
		2) provider=finnhub;      key_var=FINNHUB_API_KEY;      rate=60 ;;
		3) provider=fmp;          key_var=FMP_API_KEY;          rate=200 ;;
		4) provider=twelvedata;   key_var=TWELVEDATA_API_KEY;   rate=8 ;;
		5) provider=alphavantage; key_var=ALPHAVANTAGE_API_KEY; rate=5 ;;
		6) provider=synthetic;    key_var="";                   rate=0 ;;
		*) die "unrecognised choice: $choice" ;;
	esac

	provider_key=""
	if [[ -n "$key_var" ]]; then
		# -s: the key is never echoed to the terminal or the shell history.
		read -r -s -p "Paste the ${provider} API key (input hidden): " provider_key
		echo
		[[ -n "$provider_key" ]] || die "no API key entered"
	fi

	app_key="$(random_secret)"
	pg_password="$(random_secret)"

	cp .env.example "$ENV_FILE"
	chmod 600 "$ENV_FILE"

	set_env() {
		local name="$1" value="$2"
		if grep -q "^${name}=" "$ENV_FILE"; then
			# Value written via awk so characters special to sed cannot corrupt the file.
			awk -v n="$name" -v v="$value" -F= 'BEGIN{OFS="="}
				$1==n {print n "=" v; next} {print}' "$ENV_FILE" > "$ENV_FILE.tmp"
			mv "$ENV_FILE.tmp" "$ENV_FILE"
		else
			printf '%s=%s\n' "$name" "$value" >> "$ENV_FILE"
		fi
		chmod 600 "$ENV_FILE"
	}

	set_env APP_ENV production
	set_env API_KEYS "$app_key"
	set_env POSTGRES_PASSWORD "$pg_password"
	set_env DATABASE_URL "postgresql+psycopg://equity:${pg_password}@db:5432/equity_signal"
	set_env MARKET_DATA_PROVIDER "$provider"
	set_env MARKET_DATA_RATE_LIMIT_PER_MINUTE "$rate"
	set_env ENABLE_SCHEDULER true
	[[ -n "$key_var" ]] && set_env "$key_var" "$provider_key"

	note "Wrote $ENV_FILE (permissions 600). It is git-ignored — never commit it."
fi

# ---------------------------------------------------------------------------------------
# bring the stack up
# ---------------------------------------------------------------------------------------

note "Building and starting Postgres + API"
$COMPOSE up -d --build db api

printf 'Waiting for the API to answer /api/v1/health'
for _ in $(seq 1 60); do
	if curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1; then
		printf ' ✔\n'
		break
	fi
	printf '.'
	sleep 2
done
curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1 \
	|| die "the API did not become healthy. Check: $COMPOSE logs api"

# ---------------------------------------------------------------------------------------
# first run: schema, universe, first scan
# ---------------------------------------------------------------------------------------

note "Bootstrapping: schema, universe, first scan, first monitor pass"
echo "(A full universe refresh against a rate-limited plan can take a while — that is the"
echo " client-side pacing doing its job, not a hang.)"
$COMPOSE run --rm bootstrap || die "bootstrap failed — the output above says which step"

# ---------------------------------------------------------------------------------------

app_key_value="$(grep '^API_KEYS=' "$ENV_FILE" | cut -d= -f2-)"
lan_ip="$( (hostname -I 2>/dev/null || echo '') | awk '{print $1}')"

note "Done. Enter these in the app: Settings → Backend"
echo
echo "  Backend URL : http://${lan_ip:-<this-host>}:8000/api/v1/     (same Wi-Fi)"
echo "                https://<your-domain>/api/v1/                  (with the tls profile)"
echo "  API key     : ${app_key_value}"
echo
echo "Android emulator on this machine uses http://10.0.2.2:8000/api/v1/ instead."
echo
echo "Useful commands:"
echo "  $COMPOSE logs -f api                          follow the scanner"
echo "  $COMPOSE exec api python -m app.cli check     re-run the configuration check"
echo "  $COMPOSE exec api python -m app.cli scan      force a scan now"
