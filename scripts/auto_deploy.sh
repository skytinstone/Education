#!/bin/sh
# 자동 배포 — GitHub main 에 새 커밋이 있으면 받아서 다시 빌드·실행한다.
# 서버가 GitHub 를 확인하는 방식이라 SSH 포트를 외부에 열 필요가 없다 (docs/DEPLOY.md '자동 배포').
#   2분마다 실행:  crontab -e  →  */2 * * * * cd ~/Education && sh scripts/auto_deploy.sh >> backups/deploy.log 2>&1
set -eu
cd "$(dirname "$0")/.."

# 이전 배포가 아직 빌드 중이면 이번 차례는 건너뛴다
exec 9>/tmp/eureka-deploy.lock
flock -n 9 || exit 0

git fetch -q origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0

echo "$(date '+%F %T') 배포 시작: $(git rev-parse --short HEAD) → $(git log -1 --format='%h %s' origin/main)"
git merge -q --ff-only origin/main
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f > /dev/null
echo "$(date '+%F %T') 배포 완료"
