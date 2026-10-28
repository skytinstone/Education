# 운영 배포 — AWS EC2 (시드니) + eurekai.cloud

서버 한 대에 Docker Compose 로 세 가지를 띄운다. 내 PC 는 꺼도 된다.

```
사용자 ── https://eurekai.cloud ──▶ [EC2 t4g.small (시드니), 탄력적 IP]
                                     ├─ caddy  : HTTPS 인증서 자동 발급·갱신, 80·443 만 외부에 열림
                                     ├─ app    : FastAPI (/api + /app 화면), 시작할 때 마이그레이션·seed 자동 실행
                                     └─ db     : PostgreSQL 17 (외부에서 접속 불가)
                                   업로드 파일: 서버의 ~/Education/data/uploads
                                   백업: 매일 DB 덤프 + 업로드 → 서버 backups/ 와 S3 버킷
```

관련 파일: `Dockerfile` · `docker-compose.prod.yml` · `deploy/Caddyfile` · `.env.production.example` · `scripts/backup.sh`
같은 파일이 다른 클라우드(Oracle, Lightsail 등)의 우분투 서버에서도 그대로 동작한다.

비용(대략): EC2 t4g.small 약 $15 + 탄력적 IP 약 $3.6 + 디스크 20GB 약 $1.6 + S3 백업 몇 센트 ≈ **월 $20**.
Free plan 크레딧은 2027-04-28 까지 — 크레딧이 떨어지거나 기간이 끝나면 서비스가 멈추므로 그 전에 유료 전환 여부를 정한다.

---

## 1. 예산 알림
**Billing and Cost Management → Budgets → 예산 생성 → 템플릿: 제로 지출 예산**, 이메일 수신자에 내 이메일.

## 2. EC2 서버 만들기
오른쪽 위 리전을 **아시아 태평양(시드니) ap-southeast-2** 로 바꾼 뒤 (Free plan 계정은 배정된 리전 하나만 쓸 수 있다 — 서울은 플랜 업그레이드 후) **EC2 → 인스턴스 시작**

| 항목 | 값 |
|---|---|
| 이름 | `eureka-prod` |
| AMI | **Ubuntu Server 24.04 LTS**, 아키텍처 **64비트(Arm)** |
| 인스턴스 유형 | **t4g.small** (vCPU 2 · 메모리 2GB) — Arm 을 골라야 목록에 보인다 |
| 키 페어 | **새 키 페어 생성** → 이름 `eureka-prod`, RSA, `.pem` → 내려받은 파일을 잘 보관 (다시 받을 수 없음) |
| 네트워크 설정 | **SSH 트래픽 허용: 내 IP** · **인터넷에서 HTTPS 트래픽 허용** · **인터넷에서 HTTP 트래픽 허용** |
| 스토리지 | **20 GiB gp3** |

SSH 를 '내 IP' 로 막아 두면 집·회사 IP 가 바뀌었을 때 접속이 안 된다 → **EC2 → 보안 그룹 → 인바운드 규칙 편집** 에서 22번 규칙의 소스를 다시 '내 IP' 로 바꾼다.

### 탄력적 IP (고정 IP)
**EC2 → 탄력적 IP → 탄력적 IP 주소 할당 → 할당** → 방금 IP 선택 → **작업 → 탄력적 IP 주소 연결** → 인스턴스 `eureka-prod`.
서버를 지워도 IP 는 남아 요금이 나오므로, 서버를 정리할 때는 IP 도 **릴리스**한다.

## 3. 가비아 DNS
가비아 → DNS 관리 → `eurekai.cloud` → DNS 설정

| 타입 | 호스트 | 값/위치 | TTL |
|---|---|---|---|
| A | `@` | 탄력적 IP | 600 |
| A | `www` | 탄력적 IP | 600 |

내 PC 에서 `nslookup eurekai.cloud` 결과가 탄력적 IP 로 나오면 반영된 것이다 (보통 몇 분). **반영된 뒤에 6번을 해야** HTTPS 인증서가 발급된다.

## 4. S3 백업 버킷 + 서버 권한
1. **S3 → 버킷 만들기** — 리전 시드니(서버와 같은 곳), 이름 예: `eurekai-backups-<아무숫자>` (전 세계에서 유일해야 함), **모든 퍼블릭 액세스 차단** 켜 둔 그대로
2. 만든 버킷 → **관리 → 수명 주기 규칙 생성** — 이름 `expire-90d`, 범위 '모든 객체', **객체의 현재 버전 만료: 90일** (오래된 백업 자동 삭제)
3. **IAM → 역할 → 역할 생성** — 신뢰할 엔터티 'AWS 서비스', 사용 사례 **EC2** → 권한 정책은 건너뛰고 이름 `eureka-prod-ec2` 로 생성
4. 만든 역할 → **권한 추가 → 인라인 정책 생성 → JSON** 에 붙여넣기 (버킷 이름 두 곳을 바꾼다), 이름 `eureka-backup-s3`:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"], "Resource": "arn:aws:s3:::버킷이름/*"},
       {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::버킷이름"}
     ]
   }
   ```
5. **EC2 → 인스턴스 `eureka-prod` → 작업 → 보안 → IAM 역할 수정** → `eureka-prod-ec2`

서버에 AWS 접근 키를 저장하지 않아도 이 역할로 S3 에 올릴 수 있다. 지우기 권한은 주지 않았다 (서버가 털려도 백업은 못 지움).

## 5. 서버 준비
내 PC (PowerShell) 에서 접속:
```bash
ssh -i C:\경로\eureka-prod.pem ubuntu@탄력적IP
```
`UNPROTECTED PRIVATE KEY FILE` 오류가 나면 .pem 파일 → 속성 → 보안 → 고급 → 상속 사용 안 함 → 내 계정만 '읽기' 남기기.

서버에서:
```bash
# Docker · AWS CLI 설치 후 다시 접속 (docker 명령을 sudo 없이 쓰기 위해)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
sudo snap install aws-cli --classic

# 메모리 2GB 보완용 스왑 2GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
exit
```

### 코드 내려받기 (비공개 저장소 → 읽기 전용 Deploy key)
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```
출력된 한 줄을 GitHub → `skytinstone/Education` → **Settings → Deploy keys → Add deploy key** 에 붙여넣는다 (Allow write access 는 체크하지 않음). 그다음:
```bash
git clone git@github.com:skytinstone/Education.git
cd Education
```

### 설정 파일
```bash
cp .env.production.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD 용
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET 용
nano .env     # 위 값, BACKUP_S3_BUCKET, OpenAI·Google·카카오 키를 채운다 (Ctrl+O 저장, Ctrl+X 종료)

# 업로드 폴더 — 컨테이너 안의 사용자(uid 10001)가 쓸 수 있게
mkdir -p data/uploads/avatars && sudo chown -R 10001:10001 data/uploads
```

## 6. 실행
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f      # Ctrl+C 로 빠져나옴 (서버는 계속 돈다)
```
- 처음 빌드는 몇 분 걸린다
- 확인: https://eurekai.cloud/api/health → `{"status":"ok"}`, https://eurekai.cloud → 로그인 화면

## 7. 간편 로그인 주소 바꾸기
| | 바꿀 곳 | 값 |
|---|---|---|
| Google Cloud Console | OAuth 클라이언트 → 승인된 리디렉션 URI 에 **추가** | `https://eurekai.cloud/api/auth/google/callback` |
| Kakao Developers | 플랫폼 → Web 사이트 도메인 **추가** | `https://eurekai.cloud` |
| | 카카오 로그인 → Redirect URI **추가** | `https://eurekai.cloud/api/auth/kakao/callback` |

localhost 주소는 지우지 않고 남겨 두면 로컬 개발도 계속 된다. Google 앱이 '테스트' 상태면 테스트 사용자로 등록된 계정만 로그인된다.

## 8. 백업 (매일 자동)
```bash
sh scripts/backup.sh          # 한 번 돌려서 S3 에 올라가는지 확인
crontab -e
# 맨 아래에 추가:
0 4 * * * cd ~/Education && sh scripts/backup.sh >> backups/backup.log 2>&1
```
서버 `backups/` 에 14일치, S3 버킷에 90일치가 남는다.

---

## 새 버전 배포
내 PC 에서 `git push` 한 뒤, 서버에서:
```bash
cd ~/Education && git pull && docker compose -f docker-compose.prod.yml up -d --build
```
마이그레이션과 개념·문제 은행 갱신은 컨테이너가 시작할 때 자동으로 된다.

## 자주 쓰는 명령
```bash
alias dc='docker compose -f docker-compose.prod.yml'   # ~/.bashrc 에 넣어 두면 편하다
dc ps                                     # 상태
dc logs -f app                            # API 로그
dc restart app                            # API 만 재시작
dc exec db psql -U eureka                 # DB 직접 보기
dc exec app python -m education.generate --help   # 문제 은행 채우기
```

## 백업에서 되살리기 / 다른 서버로 옮기기
1. 새 서버를 5번까지 준비 (`.env` 는 기존 것을 복사)
2. 최신 백업 받기: `aws s3 cp s3://버킷이름/<날짜>/ . --recursive` (또는 기존 서버 `backups/` 에서 복사)
3. 새 서버에서:
   ```bash
   tar -xzf uploads-*.tar.gz -C data && sudo chown -R 10001:10001 data/uploads
   dc up -d db
   dc exec -T db pg_restore -U eureka -d eureka --clean --if-exists < db-*.dump
   dc up -d --build
   ```
4. 가비아 A 레코드를 새 서버 IP 로 바꾼다 → 반영되면 Caddy 가 인증서를 새로 받는다

## 주의
- `.env`, `.pem` 키 파일은 git·채팅에 올리지 않는다
- 서버를 멈춰도(중지) 탄력적 IP·디스크 요금은 계속 나온다
