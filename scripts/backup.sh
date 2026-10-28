#!/bin/sh
# 운영 서버 백업 — DB 덤프 + 업로드 파일을 backups/ 에 날짜별로 남기고, 14일 지난 것은 지운다.
# .env 에 BACKUP_S3_BUCKET 이 있으면 S3 에도 올린다 (서버 IAM 역할 사용, docs/DEPLOY.md 4번).
# 서버 이전할 때도 이 두 파일만 옮기면 된다.
#   매일 새벽 4시 자동 실행:  crontab -e  →  0 4 * * * cd ~/Education && sh scripts/backup.sh >> backups/backup.log 2>&1
set -eu
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d-%H%M)
mkdir -p backups
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U eureka -d eureka --format=custom > "backups/db-$STAMP.dump"
tar -czf "backups/uploads-$STAMP.tar.gz" -C data uploads
find backups -name 'db-*.dump' -mtime +14 -delete
find backups -name 'uploads-*.tar.gz' -mtime +14 -delete
echo "$STAMP 백업 완료: $(du -h "backups/db-$STAMP.dump" | cut -f1) DB, $(du -h "backups/uploads-$STAMP.tar.gz" | cut -f1) 업로드"

BUCKET=$(grep -E '^BACKUP_S3_BUCKET=' .env 2>/dev/null | cut -d= -f2- || true)
if [ -n "$BUCKET" ]; then
  aws s3 cp "backups/db-$STAMP.dump" "s3://$BUCKET/$STAMP/" --only-show-errors
  aws s3 cp "backups/uploads-$STAMP.tar.gz" "s3://$BUCKET/$STAMP/" --only-show-errors
  echo "$STAMP S3 업로드 완료: s3://$BUCKET/$STAMP/"
fi
