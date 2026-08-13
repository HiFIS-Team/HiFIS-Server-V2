#!/bin/bash
# 인증서 만료 점검 — 매일 05:10.
#
#   설치:  sudo install -m 755 hifis-cert-check.sh /usr/local/sbin/
#          sudo tee /etc/cron.d/hifis-cert-check <<'EOF'
#          10 5 * * * root /usr/local/sbin/hifis-cert-check.sh
#          EOF
#
# ## 왜 그라파나가 아니라 파일을 보나
#
# blackbox 는 **공인 주소가 아니라 컨테이너를 HTTP 로** 찌른다
# (`http://api:8000/health`). 집 인터넷이 잠깐 끊긴 것을 "사이트 다운"으로
# 안 부르려고 일부러 그렇게 해 둔 것이라, **TLS 를 아예 안 거쳐서
# `probe_ssl_earliest_cert_expiry` 가 수집되지 않는다.** 그라파나 규칙을
# 얹을 재료가 없다.
#
# 대신 nginx 가 실제로 내미는 파일을 직접 읽는다. 갱신이 조용히 실패하면
# 이 파일이 안 바뀌므로 그대로 걸린다.
#
# ## 못 잡는 것 하나
#
# **갱신은 됐는데 nginx 를 안 다시 읽힌 경우** — 파일은 새 것인데 내미는 건
# 옛 것이다. certbot 의 deploy hook 이 reload 를 하고 있어서 지금은 안 나는
# 사고지만, hook 이 빠지면 여기서는 안 보인다.

set -uo pipefail

# 셋 다 시험할 때 덮어쓸 수 있게 열어 뒀다 (운영에서는 그냥 기본값으로 돈다)
LIVE=${LIVE:-/etc/letsencrypt/live}
API=${API:-https://api.hifis.app/security/alert}
ENV_FILE=${ENV_FILE:-/home/fitnessstar/hifis-api/.env}

# 며칠 남았을 때부터 알리나. Let's Encrypt 는 30일 전부터 갱신을 시도하므로
# 14일까지 남았다는 건 **갱신이 이미 몇 번 실패했다**는 뜻이다
WARN_DAYS=14

NOW=$(date +%s)
PROBLEMS=()
CHECKED=0

for cert in "$LIVE"/*/cert.pem; do
  [ -f "$cert" ] || continue
  domain=$(basename "$(dirname "$cert")")
  end=$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)
  if [ -z "$end" ]; then
    PROBLEMS+=("$domain 인증서를 못 읽는다")
    continue
  fi
  CHECKED=$((CHECKED + 1))
  left=$(( ($(date -d "$end" +%s) - NOW) / 86400 ))
  if [ "$left" -lt 0 ]; then
    PROBLEMS+=("$domain 이 $(( -left ))일 전에 만료됐다")
  elif [ "$left" -le "$WARN_DAYS" ]; then
    PROBLEMS+=("$domain ${left}일 남음")
  fi
done

# 인증서를 하나도 못 찾는 것도 사고다 — 폴더가 비었거나 경로가 바뀌었다
[ "$CHECKED" -gt 0 ] || PROBLEMS+=("$LIVE 에 인증서가 없다")

[ ${#PROBLEMS[@]} -gt 0 ] || { echo "인증서 $CHECKED개 정상"; exit 0; }

TOKEN=$(grep -m1 '^INTERNAL_HOOK_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'')
[ -n "$TOKEN" ] || { echo "INTERNAL_HOOK_TOKEN 을 못 읽었다 — $ENV_FILE"; exit 1; }

body=$(printf '%s · ' "${PROBLEMS[@]}"); body=${body% · }
echo "인증서 문제: $body"
curl -sS -m 15 -o /dev/null -X POST "$API" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg m "$body" '{status:"firing", title:"인증서 만료 임박", message:$m}')"
