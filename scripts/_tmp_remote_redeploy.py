from __future__ import annotations

import sys

import paramiko


def run_command(client: paramiko.SSHClient, command: str) -> int:
    _, stdout, stderr = client.exec_command(command)
    code = stdout.channel.recv_exit_status()
    sys.stdout.write(stdout.read().decode("utf-8", errors="replace"))
    sys.stderr.write(stderr.read().decode("utf-8", errors="replace"))
    return code


def main() -> int:
    host = "72.56.121.150"
    user = "root"
    password = "b^nvnWDD2YQ.d_"
    commands = [
        "cd /opt/tradingbotcrypto && docker compose down || true",
        "cd /opt/tradingbotcrypto_clean && docker compose --profile worker up -d --build --remove-orphans",
        "cd /opt/tradingbotcrypto_clean && docker compose ps",
    ]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30)
    try:
        for command in commands:
            print(f"$ {command}")
            code = run_command(client, command)
            if code != 0:
                return code
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
