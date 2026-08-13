#!/bin/bash
# 백업 점검 — 매일 05:00, 백업(04:25)이 끝난 뒤에 돈다.
#
#   설치:  sudo install -m 755 hifis-backup-check.sh /usr/local/sbin/
#          sudo tee /etc/cron.d/hifis-backup-check <<'EOF'
#          0 5 * * * root /usr/local/sbin/hifis-backup-check.sh
#          EOF
#
# ## 왜 백업 스크립트를 고치지 않고 따로 도나
#
# **과정이 아니라 결과를 본다.** 백업 스크립트 안에 "실패하면 알려라"를 넣으면
# 그 스크립트가 아는 실패만 잡힌다 — 크론이 안 돌았거나, 스크립트가 통째로
# 죽었거나, 디스크가 차서 파일이 반만 써진 것은 못 잡는다.
#
# 여기서는 **/var/backups/hifis 를 눈으로 보듯 확인한다.** 오늘 파일이 있나,
# 열리나, 어제만 한가. 무엇 때문에 실패했든 결과가 없으면 걸린다.
#
# ## 조용하면 잘 되는 것인가
#
# 아니다 — 이 스크립트가 안 돌아도 조용하다. 그래서 **일요일에는 잘 됐다는
# 알림을 한 번 보낸다.** 두 주 동안 아무 소식이 없으면 그 자체가 신호다.
# 성가시면 WEEKLY_OK=0 으로 끈다.

set -uo pipefail

# 셋 다 시험할 때 덮어쓸 수 있게 열어 뒀다 (운영에서는 그냥 기본값으로 돈다)
DIR=${DIR:-/var/backups/hifis}
API=${API:-https://api.hifis.app/security/alert}
ENV_FILE=${ENV_FILE:-/home/fitnessstar/hifis-api/.env}   # INTERNAL_HOOK_TOKEN 을 여기서 읽는다

# 어제 대비 이 비율 아래로 작아지면 이상으로 본다 (성공했는데 빈 파일인 경우)
SHRINK_PCT=50

# 맥으로 당겨간 지 이만큼 지나면 알린다. 서버 백업은 서버가 털리면 같이 죽는다
PULL_MAX_DAYS=7

WEEKLY_OK=${WEEKLY_OK:-1}   # 일요일에 '잘 됐다' 한 번

TODAY=$(date +%Y%m%d)
YDAY=$(date -d yesterday +%Y%m%d)
PROBLEMS=()

note() { PROBLEMS+=("$1"); }

# ── 1. 오늘 것이 있나 · 열리나 ────────────────────────────────────────────
for f in "hifis-db-$TODAY.sql.gz" "careers-db-$TODAY.sql.gz" "config-$TODAY.tgz"; do
  path="$DIR/$f"
  if [ ! -f "$path" ]; then
    note "$f 가 없다"
    continue
  fi
  # 크기 0 은 물론이고, gzip 이 중간에 끊긴 것도 여기서 걸린다
  if ! gzip -t "$path" 2>/dev/null; then
    note "$f 가 깨졌다 (압축이 안 풀린다)"
  fi
done

# ── 2. 어제만 한가 — "성공했는데 빈 덤프" 를 잡는다 ────────────────────────
for name in hifis-db careers-db; do
  new="$DIR/$name-$TODAY.sql.gz"
  old="$DIR/$name-$YDAY.sql.gz"
  [ -f "$new" ] && [ -f "$old" ] || continue
  n=$(stat -c%s "$new"); o=$(stat -c%s "$old")
  [ "$o" -gt 0 ] || continue
  if [ $((n * 100 / o)) -lt "$SHRINK_PCT" ]; then
    note "$name 덤프가 어제의 $((n * 100 / o))% 다 ($o → $n 바이트)"
  fi
done

# ── 3. 업로드 스냅샷 ─────────────────────────────────────────────────────
for kind in hifis careers; do
  [ -d "$DIR/uploads/$kind/$TODAY" ] || note "업로드 스냅샷($kind)이 없다"
done

# ── 4. 맥이 당겨갔나 ─────────────────────────────────────────────────────
# `당겨오기.sh` 가 끝나면서 이 파일을 만진다. 서버 안의 백업은 서버가 털리면
# 같이 사라지므로, **맥으로 옮겨진 것만 진짜 백업이다**
#
# 백업 폴더가 아니라 홈에 둔다 — `/var/backups` 는 root 것이라 당겨오는 계정
# (`fitnessstar`)이 못 쓴다. 폴더 안에 두면 rsync 가 도로 맥으로 복사하기도 한다
MARK=${MARK:-/home/fitnessstar/.hifis-last-pull}
if [ ! -f "$MARK" ]; then
  note "맥으로 한 번도 안 당겨갔다"
elif [ "$(find "$MARK" -mtime +$PULL_MAX_DAYS | wc -l)" -gt 0 ]; then
  note "맥으로 당겨간 지 ${PULL_MAX_DAYS}일이 넘었다 (마지막 $(date -r "$MARK" +%m/%d))"
fi

# ── 보내기 ───────────────────────────────────────────────────────────────
TOKEN=$(grep -m1 '^INTERNAL_HOOK_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'')
[ -n "$TOKEN" ] || { echo "INTERNAL_HOOK_TOKEN 을 못 읽었다 — $ENV_FILE"; exit 1; }

send() {  # send <제목> <본문>
  curl -sS -m 15 -o /dev/null -X POST "$API" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg t "$1" --arg m "$2" '{status:"firing", title:$t, message:$m}')"
}

if [ ${#PROBLEMS[@]} -gt 0 ]; then
  # 폰 알림이 좁다 — 여러 개면 첫 줄에 개수를 적고 이어 붙인다
  body=$(printf '%s · ' "${PROBLEMS[@]}"); body=${body% · }
  echo "백업 문제 ${#PROBLEMS[@]}건: $body"
  send "백업 실패" "$body"
  exit 1
fi

echo "백업 정상 ($TODAY)"
if [ "$WEEKLY_OK" = 1 ] && [ "$(date +%u)" = 7 ]; then
  size=$(du -sh "$DIR" 2>/dev/null | cut -f1)
  send "백업 정상" "이번 주 백업이 다 잘 됐어요 · 보관 $size"
fi
