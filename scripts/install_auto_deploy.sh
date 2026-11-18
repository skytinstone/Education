#!/bin/sh
# 자동 배포 켜기 (서버에서 한 번만):  sh scripts/install_auto_deploy.sh
# - 2분마다 scripts/auto_deploy.sh 실행 (새 커밋이 있을 때만 일함)
# - 매일 새벽 4시(한국 시간) 백업 — 이미 등록돼 있으면 그대로 둔다
# 끄기:  crontab -l | grep -v auto_deploy.sh | crontab -
set -eu
DIR=$(cd "$(dirname "$0")/.." && pwd)

if ! command -v crontab > /dev/null 2>&1; then
  echo "cron 이 없어서 설치해요 (sudo 비밀번호를 물을 수 있어요)"
  if command -v dnf > /dev/null 2>&1; then sudo dnf install -y cronie && sudo systemctl enable --now crond
  elif command -v apt-get > /dev/null 2>&1; then sudo apt-get install -y cron && sudo systemctl enable --now cron
  else echo "cron 을 직접 설치한 뒤 다시 실행해 주세요"; exit 1
  fi
fi
command -v flock > /dev/null 2>&1 || { echo "flock 이 필요해요 (util-linux 패키지)"; exit 1; }
mkdir -p "$DIR/backups"

CURRENT=$(crontab -l 2>/dev/null || true)
NEW=$(printf '%s\n' "$CURRENT" | grep -v 'scripts/auto_deploy.sh' || true)
NEW="$NEW
*/2 * * * * cd $DIR && sh scripts/auto_deploy.sh >> backups/deploy.log 2>&1"
if ! printf '%s\n' "$CURRENT" | grep -q 'scripts/backup.sh'; then
  # 서버 시간은 UTC → 19:00 UTC = 한국 04:00
  NEW="$NEW
0 19 * * * cd $DIR && sh scripts/backup.sh >> backups/backup.log 2>&1"
fi
printf '%s\n' "$NEW" | sed '/^$/d' | crontab -

echo "자동 배포를 켰어요. 등록된 작업:"
crontab -l
echo
echo "이제 내 PC 에서 git push 하면, 테스트 통과 후 2~5분 안에 반영돼요."
echo "기록 보기:  tail -f $DIR/backups/deploy.log"
