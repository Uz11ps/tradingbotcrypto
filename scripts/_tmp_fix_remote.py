from __future__ import annotations

import sys

import paramiko


def main() -> int:
    host = "72.56.121.150"
    user = "root"
    password = "b^nvnWDD2YQ.d_"
    command = (
        "cd /opt/tradingbotcrypto && "
        "git remote set-url origin https://github.com/Uz11ps/tradingbotcrypto.git && "
        "git fetch origin && git checkout main && git pull --ff-only origin main"
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30)
    try:
        _, stdout, stderr = client.exec_command(command)
        code = stdout.channel.recv_exit_status()
        sys.stdout.write(stdout.read().decode("utf-8", errors="replace"))
        sys.stderr.write(stderr.read().decode("utf-8", errors="replace"))
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
