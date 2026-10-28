#!/bin/sh
# 운영 서버 보안 기본 설정 — 처음 한 번만 실행 (여러 번 실행해도 안전)
#   sudo sh scripts/harden_server.sh
# 1) 보안 업데이트 자동 설치  2) SSH 무차별 대입 차단(fail2ban)  3) SSH 비밀번호 로그인 금지(키만 허용)
# 4) Docker 로그 크기 제한 (봇 요청 로그가 디스크를 채우지 않게)
set -eu
[ "$(id -u)" = 0 ] || { echo "sudo 로 실행하세요: sudo sh scripts/harden_server.sh"; exit 1; }

apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q unattended-upgrades fail2ban

# 1) 보안 업데이트 매일 자동 설치 (재부팅은 하지 않음)
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# 2) SSH 로그인 10분 안에 5번 틀리면 1시간 차단
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

# 3) 비밀번호 로그인 금지 — EC2 는 원래 키 로그인만 쓰지만 확실히 막아 둔다
cat > /etc/ssh/sshd_config.d/99-eureka.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t && systemctl reload ssh

# 4) 컨테이너 로그는 컨테이너마다 최대 10MB × 3개
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
  echo "Docker 로그 제한 설정 — 적용하려면 (서비스가 몇 초 끊김):"
  echo "  sudo systemctl restart docker && docker compose -f docker-compose.prod.yml up -d --force-recreate"
fi

echo "완료: 자동 보안 업데이트 · fail2ban · SSH 키 로그인만 허용"
fail2ban-client status sshd | tail -3
