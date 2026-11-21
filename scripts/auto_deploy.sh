#!/bin/sh
# 자동 배포 — GitHub main 에 새 커밋이 생기면 서버가 직접 받아서 반영한다.
# 서버가 GitHub 를 확인하는 방식이라 SSH 포트를 외부에 열 필요가 없다 (docs/DEPLOY.md '9. 자동 배포').
#
#   순서: 새 커밋 확인 → GitHub Actions 테스트 통과 확인 → 백업 → 받아서 빌드·실행
#         → 상태 확인 → 실패하면 이전 버전으로 되돌림
#
#   설치(한 번):  sh scripts/install_auto_deploy.sh      (2분마다 이 스크립트를 실행하도록 cron 등록)
#   바로 배포:    sh scripts/auto_deploy.sh
#   테스트 결과를 기다리지 않고 바로:  FORCE=1 sh scripts/auto_deploy.sh
#   기록:         tail -f backups/deploy.log
#   .env 에 DEPLOY_WEBHOOK_URL (Slack·Discord 웹훅) 을 넣으면 배포 결과를 알려 준다 (선택)
set -eu
# 배포가 이 스크립트 파일 자체를 바꿀 수 있어서 (sh 는 실행하면서 파일을 읽는다), 임시 복사본으로 실행한다
if [ -z "${DEPLOY_DIR:-}" ]; then
  DEPLOY_DIR=$(cd "$(dirname "$0")/.." && pwd)
  COPY=$(mktemp /tmp/eureka-deploy.XXXXXX)
  cp "$0" "$COPY"
  DEPLOY_DIR=$DEPLOY_DIR exec sh "$COPY" "$@"
fi
trap 'rm -f "$0"' EXIT
cd "$DEPLOY_DIR"

REPO=skytinstone/Education
CI_CHECK=test                     # .github/workflows/ci.yml 의 테스트 job 이름
COMPOSE="docker compose -f docker-compose.prod.yml"
SKIP=backups/.deploy-skip         # 테스트 실패·배포 실패로 건너뛴 커밋 (새 커밋이 오면 다시 시도)
mkdir -p backups

log() { echo "$(date '+%F %T') $*"; }
notify() {
  URL=$(grep -E '^DEPLOY_WEBHOOK_URL=' .env 2>/dev/null | cut -d= -f2- || true)
  [ -n "$URL" ] || return 0
  MSG=$(printf '%s' "$1" | sed 's/"/\\"/g')
  curl -s -m 10 -H 'Content-Type: application/json' -d "{\"text\":\"$MSG\",\"content\":\"$MSG\"}" "$URL" > /dev/null || true
}

# 이전 배포가 아직 진행 중이면 이번 차례는 건너뛴다
exec 9>/tmp/eureka-deploy.lock
flock -n 9 || exit 0

git fetch -q origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
  # 코드는 최신인데 실행 중인 앱의 버전 표시가 다르면 (손으로 docker compose up 했거나, 예전 스크립트로 배포한 경우)
  # 다시 빌드하지 않고 버전만 넣어 앱을 다시 띄운다 → /api/health 의 version 과 GitHub '운영 반영 확인'이 맞아진다
  RUNNING=$($COMPOSE exec -T app sh -c 'echo "${APP_VERSION:-}"' 2>/dev/null | tr -d '\r' || true)
  HEAD7=$(git rev-parse --short=7 HEAD)
  if [ -n "$RUNNING" ] && [ "$RUNNING" != "$HEAD7" ]; then
    log "실행 중인 버전 표시($RUNNING)를 $HEAD7 로 맞춰요"
    APP_VERSION=$HEAD7 $COMPOSE up -d app
  fi
  exit 0
fi
[ "$(cat "$SKIP" 2>/dev/null || true)" = "$REMOTE" ] && [ "${FORCE:-0}" != 1 ] && exit 0
SHORT=$(git rev-parse --short=7 origin/main)
TITLE=$(git log -1 --format=%s origin/main)

# ---------- 1. GitHub Actions 테스트 결과 확인 ----------
if [ "${FORCE:-0}" != 1 ]; then
  J=$(curl -fsS -m 15 -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/$REPO/commits/$REMOTE/check-runs?check_name=$CI_CHECK" 2>/dev/null || echo '')
  AGE=$(( $(date +%s) - $(git log -1 --format=%ct origin/main) ))
  if echo "$J" | grep -Eq '"conclusion": *"(failure|cancelled|timed_out|action_required)"'; then
    log "건너뜀: $SHORT $TITLE — GitHub 테스트 실패. 고쳐서 다시 push 하면 그 커밋을 배포해요"
    notify "❌ Eureka 배포 건너뜀 ($SHORT) — 테스트 실패: $TITLE"
    echo "$REMOTE" > "$SKIP"
    exit 0
  elif [ -z "$J" ] || echo "$J" | grep -Eq '"status": *"(queued|in_progress|waiting|pending|requested)"'; then
    exit 0                                            # 테스트 진행 중 (또는 GitHub 응답 없음) → 다음 차례에 다시
  elif echo "$J" | grep -Eq '"total_count": *0'; then
    [ "$AGE" -lt 1200 ] && exit 0                     # 테스트가 아직 시작 전 → 20분까지 기다림
    log "주의: $SHORT 의 테스트 결과가 20분 넘게 없어 그대로 배포해요"
  fi
fi

# ---------- 2. 백업 → 반영 ----------
log "배포 시작: $(git rev-parse --short=7 HEAD) → $SHORT $TITLE"
if ! sh scripts/backup.sh; then
  log "백업 실패 — 배포를 멈췄어요 (디스크 공간·DB 상태를 확인하세요)"
  notify "⚠️ Eureka 배포 중단 ($SHORT) — 백업 실패"
  exit 1
fi
PREV=$LOCAL
git merge -q --ff-only origin/main

up() { APP_VERSION=$(git rev-parse --short=7 HEAD) $COMPOSE up -d --build --remove-orphans; }
healthy() {   # 새 컨테이너가 마이그레이션까지 마치고 응답할 때까지 최대 3분
  i=0
  while [ $i -lt 90 ]; do
    if $COMPOSE exec -T app python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status != 200)" > /dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1)); sleep 2
  done
  return 1
}

up
if healthy; then
  rm -f "$SKIP"
  docker image prune -f > /dev/null
  log "배포 완료: $SHORT"
  notify "✅ Eureka 배포 완료 ($SHORT) — $TITLE"
else
  # ---------- 3. 실패 → 이전 버전으로 ----------
  log "상태 확인 실패 — 이전 버전 $(git rev-parse --short=7 "$PREV") 로 되돌려요. 앱 로그:"
  $COMPOSE logs --tail 60 app || true
  git reset -q --hard "$PREV"
  up
  echo "$REMOTE" > "$SKIP"
  if healthy; then log "되돌리기 완료 (방금 백업: backups/ 의 최신 db-*.dump)"; else log "되돌린 버전도 응답이 없어요 — 서버를 직접 확인하세요"; fi
  notify "🚨 Eureka 배포 실패 ($SHORT) — 이전 버전으로 되돌렸어요. 서버 backups/deploy.log 확인"
  exit 1
fi
