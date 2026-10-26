import subprocess

from education.config import ROOT


def test_models_match_migrations(engine, test_db_url):
    """모델을 바꾸고 마이그레이션을 안 만들면 실패한다 (alembic check)."""
    r = subprocess.run(["alembic", "-x", f"db_url={test_db_url}", "check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
