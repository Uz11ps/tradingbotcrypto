from __future__ import annotations

import io
import os
import sys
import tarfile
from pathlib import Path

import paramiko


HOST = "72.56.121.150"
USER = "root"
PASSWORD = "b^nvnWDD2YQ.d_"
REMOTE_DIR = "/opt/tradingbotcrypto_direct"
REMOTE_TAR = "/tmp/tradingbotcrypto_direct.tar.gz"
BOT_TOKEN = "7587176487:AAFsbPSHf_r_96b_t-9FEd3yG1__fJCFue8"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _run(ssh: paramiko.SSHClient, command: str) -> tuple[int, str, str]:
    _, stdout, stderr = ssh.exec_command(command)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return code, out, err


def _build_archive(repo_root: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        include_paths = [
            "app",
            "alembic",
            "scripts",
            "Dockerfile",
            "docker-compose.yml",
            "pyproject.toml",
            "README.md",
            "alembic.ini",
        ]
        for rel in include_paths:
            full = repo_root / rel
            if full.exists():
                tar.add(full, arcname=rel)
    buf.seek(0)
    return buf.read()


def _build_env() -> str:
    return (
        f"TELEGRAM_BOT_TOKEN={BOT_TOKEN}\n"
        "TELEGRAM_SIGNALS_CHAT_ID=0\n"
        "API_HOST=0.0.0.0\n"
        "API_PORT=8000\n"
        "API_PUBLIC_BASE_URL=http://api:8000\n"
        "POSTGRES_HOST=postgres\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_DB=cryptoarbi\n"
        "POSTGRES_USER=cryptoarbi\n"
        "POSTGRES_PASSWORD=cryptoarbi\n"
        "DATABASE_URL=postgresql+asyncpg://cryptoarbi:cryptoarbi@postgres:5432/cryptoarbi\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "LOG_LEVEL=INFO\n"
        "SIGNAL_ENGINE_MODE=rsi\n"
        "WORKER_INTERVAL_SECONDS=20\n"
        "FEED_UNIVERSE_SIZE=300\n"
        "FEED_MOVERS_LIMIT=20\n"
        "FEED_MIN_CHANGE_PCT=2.5\n"
        "WORKER_FEED_COOLDOWN_SECONDS=900\n"
        "SIGNAL_PRICE_CHANGE_5M_TRIGGER_PCT=2.0\n"
        "SIGNAL_PRICE_CHANGE_15M_TRIGGER_PCT=3.5\n"
        "SIGNAL_VOLUME_MULTIPLIER_BASE=1.35\n"
        "SIGNAL_VOLUME_MULTIPLIER_STRONG=1.2\n"
        "SIGNAL_STRONG_MOVE_PCT=5.0\n"
        "SIGNAL_VOLUME_AVG_WINDOW=20\n"
        "SIGNAL_REPEAT_GUARD_MIN_MOVE_PCT=0.4\n"
        "SIGNAL_REPEAT_GUARD_MIN_RSI_DELTA=2.0\n"
        "SIGNAL_RETENTION_DAYS=14\n"
        "SIGNAL_RETENTION_PRUNE_INTERVAL_SECONDS=3600\n"
        "WORKER_SHARD_INDEX=0\n"
        "WORKER_SHARD_COUNT=3\n"
        "SIGNAL_FILTER_REDIS_PREFIX=signal_filter\n"
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    archive = _build_archive(repo_root)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    try:
        print("Uploading archive...")
        sftp = ssh.open_sftp()
        with sftp.file(REMOTE_TAR, "wb") as fp:
            fp.write(archive)

        print("Preparing remote directories...")
        for cmd in [
            f"mkdir -p '{REMOTE_DIR}'",
            f"cd '{REMOTE_DIR}' && rm -rf app alembic scripts Dockerfile docker-compose.yml pyproject.toml README.md alembic.ini",
            f"tar -xzf '{REMOTE_TAR}' -C '{REMOTE_DIR}'",
        ]:
            code, out, err = _run(ssh, cmd)
            if out:
                print(out)
            if err:
                print(err)
            if code != 0:
                return code

        print("Writing remote .env...")
        with sftp.file(f"{REMOTE_DIR}/.env", "w") as fp:
            fp.write(_build_env())
        sftp.close()

        print("Stopping old stacks to free ports...")
        for cmd in [
            "cd '/opt/tradingbotcrypto' && docker compose down || true",
            "cd '/opt/tradingbotcrypto_clean' && docker compose down || true",
        ]:
            code, out, err = _run(ssh, cmd)
            if out:
                print(out)
            if err:
                print(err)
            if code != 0:
                return code

        print("Starting direct stack...")
        code, out, err = _run(
            ssh,
            f"cd '{REMOTE_DIR}' && docker compose --profile worker up -d --build --remove-orphans",
        )
        print(out)
        print(err)
        if code != 0:
            return code

        print("Compose status:")
        code, out, err = _run(ssh, f"cd '{REMOTE_DIR}' && docker compose ps")
        print(out)
        print(err)
        return code
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
