# 작업 흐름: 이슈 → 브랜치 → PR

기능·버그마다 이슈를 열고, 브랜치에서 작업한 뒤 PR 로 `main` 에 합친다.

1. **이슈 열기** — `gh issue create` (템플릿: 기능 · 버그). 번호를 기억한다 (예: #12).
2. **브랜치 만들기** — `git switch -c feat/12-짧은-설명` (버그는 `fix/`, 문서·설정은 `chore/`).
3. **작업·커밋** — 작은 단위로 자주 커밋한다. 커밋 메시지 끝에 `(#12)` 를 붙이면 이슈와 연결된다.
4. **PR 열기** — `gh pr create --fill` 후 본문에 `Closes #12`. PR 에서 CI 테스트가 돈다.
5. **합치기** — CI 가 통과하면 `gh pr merge --squash --delete-branch`. 이슈는 저절로 닫힌다.
6. **운영 반영** — `main` 에 합쳐지면 EC2 자동 배포(scripts/auto_deploy.sh)가 CI 통과를 확인한 뒤 반영한다.

## 커밋 작성자
이 저장소의 커밋은 `skytinstone` 계정으로 남긴다 (GitHub 활동 기록에 잡히도록).

```bash
git config user.name "skytinstone"
git config user.email "110448207+skytinstone@users.noreply.github.com"
```
