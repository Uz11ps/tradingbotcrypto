#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass

try:
    import paramiko
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Paramiko is required. Install it with: pip install paramiko"
    ) from e


@dataclass(slots=True)
class DeployConfig:
    host: str
    user: str
    password: str
    repo_url: str
    branch: str
    deploy_dir: str
    bot_token: str
    signals_chat_id: int
    api_port: int
    postgres_port: int
    worker_interval_seconds: int
    feed_universe_size: int
    feed_movers_limit: int
    feed_min_change_pct: float
    worker_feed_cooldown_seconds: int


class Deployer:
    def __init__(self, cfg: DeployConfig) -> None:
        self.cfg = cfg
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self) -> None:
        self.ssh.connect(
            self.cfg.host,
            username=self.cfg.user,
            password=self.cfg.password,
            timeout=30,
        )

    def close(self) -> None:
        self.ssh.close()

    def run(self, cmd: str) -> str:
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if code != 0:
            raise RuntimeError(f"Command failed ({code}): {cmd}\n{out}\n{err}")
        return out

    def ensure_runtime(self) -> None:
        self.run("export DEBIAN_FRONTEND=noninteractive && apt-get update -y")
        self.run(
            "export DEBIAN_FRONTEND=noninteractive && "
            "apt-get install -y ca-certificates curl git docker-compose-plugin"
        )
        self.run("if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com | sh; fi")
        self.run("systemctl enable --now docker || true")

    def sync_repo(self) -> None:
        self.run(
            f"if [ -d '{self.cfg.deploy_dir}/.git' ]; then "
            f"cd '{self.cfg.deploy_dir}' && git fetch origin && git checkout '{self.cfg.branch}' && "
            f"git pull --ff-only origin '{self.cfg.branch}'; "
            f"else git clone -b '{self.cfg.branch}' '{self.cfg.repo_url}' '{self.cfg.deploy_dir}'; fi"
        )

    def write_env(self) -> None:
        env_content = (
            f"TELEGRAM_BOT_TOKEN={self.cfg.bot_token}\n"
            f"TELEGRAM_SIGNALS_CHAT_ID={self.cfg.signals_chat_id}\n"
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
            f"WORKER_INTERVAL_SECONDS={self.cfg.worker_interval_seconds}\n"
            f"FEED_UNIVERSE_SIZE={self.cfg.feed_universe_size}\n"
            f"FEED_MOVERS_LIMIT={self.cfg.feed_movers_limit}\n"
            f"FEED_MIN_CHANGE_PCT={self.cfg.feed_min_change_pct}\n"
            f"WORKER_FEED_COOLDOWN_SECONDS={self.cfg.worker_feed_cooldown_seconds}\n"
            f"API_PORT={self.cfg.api_port}\n"
            f"POSTGRES_PORT={self.cfg.postgres_port}\n"
        )
        sftp = self.ssh.open_sftp()
        with sftp.file(f"{self.cfg.deploy_dir}/.env", "w") as file_obj:
            file_obj.write(env_content)
        sftp.close()

    def up(self) -> None:
        self.run(f"cd '{self.cfg.deploy_dir}' && docker compose down || true")
        self.run(f"cd '{self.cfg.deploy_dir}' && docker compose --profile worker up -d --build")

    def status(self) -> str:
        return self.run(f"cd '{self.cfg.deploy_dir}' && docker compose ps")

    def bot_logs(self) -> str:
        return self.run(f"cd '{self.cfg.deploy_dir}' && docker compose logs --tail=50 bot")


def parse_args() -> DeployConfig:
    parser = argparse.ArgumentParser(description="Deploy tradingbotcrypto to remote server over SSH.")
    parser.add_argument("--host", required=True, help="Server IP or hostname")
    parser.add_argument("--user", required=True, default="root", help="SSH username")
    parser.add_argument("--password", required=True, help="SSH password")
    parser.add_argument("--repo-url", required=True, help="Git repository URL")
    parser.add_argument("--branch", default="main", help="Git branch to deploy")
    parser.add_argument("--deploy-dir", default="/opt/tradingbotcrypto", help="Deploy directory on server")
    parser.add_argument("--bot-token", required=True, help="Telegram bot token")
    parser.add_argument("--signals-chat-id", default=0, type=int, help="Target Telegram chat ID for channel alerts")
    parser.add_argument("--api-port", default=8000, type=int, help="API published port")
    parser.add_argument("--postgres-port", default=5432, type=int, help="Postgres published port")
    parser.add_argument("--worker-interval-seconds", default=20, type=int, help="Worker loop interval")
    parser.add_argument("--feed-universe-size", default=100, type=int, help="Universe size for movers feed")
    parser.add_argument("--feed-movers-limit", default=20, type=int, help="Maximum movers in feed")
    parser.add_argument("--feed-min-change-pct", default=2.5, type=float, help="Min 24h change for movers")
    parser.add_argument("--worker-feed-cooldown-seconds", default=600, type=int, help="Cooldown per coin for feed alerts")
    args = parser.parse_args()

    return DeployConfig(
        host=args.host,
        user=args.user,
        password=args.password,
        repo_url=args.repo_url,
        branch=args.branch,
        deploy_dir=args.deploy_dir,
        bot_token=args.bot_token,
        signals_chat_id=args.signals_chat_id,
        api_port=args.api_port,
        postgres_port=args.postgres_port,
        worker_interval_seconds=args.worker_interval_seconds,
        feed_universe_size=args.feed_universe_size,
        feed_movers_limit=args.feed_movers_limit,
        feed_min_change_pct=args.feed_min_change_pct,
        worker_feed_cooldown_seconds=args.worker_feed_cooldown_seconds,
    )


def main() -> int:
    cfg = parse_args()
    deployer = Deployer(cfg)
    try:
        print("Connecting...")
        deployer.connect()
        print("Ensuring runtime...")
        deployer.ensure_runtime()
        print("Syncing repository...")
        deployer.sync_repo()
        print("Writing .env...")
        deployer.write_env()
        print("Starting containers...")
        deployer.up()
        print("\n=== Docker Compose Status ===")
        print(deployer.status())
        print("\n=== Bot Logs (tail) ===")
        print(deployer.bot_logs())
        print("\nDEPLOY_OK")
    finally:
        deployer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

