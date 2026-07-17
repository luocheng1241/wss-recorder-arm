#!/usr/bin/env python3
"""Deploy wss-recorder-arm to remote host via SSH/SFTP."""
from __future__ import annotations

import os
import sys
import time

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "192.168.6.204")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASS", "xinzhong1241")
REMOTE_DIR = os.environ.get("DEPLOY_DIR", "/opt/wss-recorder-arm")
CONSOLE_PASSWORD = os.environ.get("WSS_CONSOLE_PASSWORD", "xinzhong1241")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_TGZ = os.path.join(ROOT, "deploy.tgz")


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="ignore")
    err = stderr.read().decode(errors="ignore")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    return code, out, err


def main() -> int:
    if not os.path.isfile(LOCAL_TGZ):
        print("missing deploy.tgz", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"connecting {USER}@{HOST} ...")
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    print("SSH ok")

    run(client, f"mkdir -p {REMOTE_DIR}/data/recordings")

    sftp = client.open_sftp()
    remote_tgz = f"{REMOTE_DIR}/deploy.tgz"
    print(f"uploading {LOCAL_TGZ} -> {remote_tgz}")
    sftp.put(LOCAL_TGZ, remote_tgz)
    sftp.close()

    # extract (overwrite app sources, keep data)
    code, _, _ = run(
        client,
        f"cd {REMOTE_DIR} && tar -xzf deploy.tgz && rm -f deploy.tgz && "
        f"if [ ! -f data/config.yaml ]; then cp config.example.yaml data/config.yaml; fi && "
        f"ls -la && ls -la app | head",
    )
    if code != 0:
        return code

    # write env file for compose
    env_content = (
        f"WSS_CONSOLE_PASSWORD={CONSOLE_PASSWORD}\n"
        f"WSS_SESSION_SECRET=orangepi-{int(time.time())}-wss-recorder\n"
        f"WSS_DEVICE_ID=14eaa12a154e\n"
    )
    sftp = client.open_sftp()
    with sftp.file(f"{REMOTE_DIR}/.env", "w") as f:
        f.write(env_content)
    sftp.close()

    # docker compose build & up
    # prefer docker compose plugin; fallback docker-compose
    code, out, _ = run(client, "docker compose version 2>/dev/null || docker-compose version 2>/dev/null")
    compose = "docker compose" if "Docker Compose" in out or "v2" in out or "version" in out.lower() else "docker-compose"

    # free some space / stop old
    run(client, f"cd {REMOTE_DIR} && {compose} down 2>/dev/null || true", timeout=120)

    code, _, _ = run(
        client,
        f"cd {REMOTE_DIR} && {compose} build --pull 2>&1",
        timeout=1200,
    )
    if code != 0:
        print("build failed", file=sys.stderr)
        return code

    code, _, _ = run(
        client,
        f"cd {REMOTE_DIR} && {compose} up -d 2>&1",
        timeout=300,
    )
    if code != 0:
        print("up failed", file=sys.stderr)
        return code

    time.sleep(3)
    run(client, f"cd {REMOTE_DIR} && {compose} ps")
    run(client, "docker ps --filter name=recorder --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")
    run(client, "curl -sS http://127.0.0.1:8080/api/health || true")
    run(client, f"cd {REMOTE_DIR} && {compose} logs --tail 40")

    print("\n=== DEPLOY DONE ===")
    print(f"URL: http://{HOST}:8080")
    print(f"Password: {CONSOLE_PASSWORD}")
    print(f"Remote dir: {REMOTE_DIR}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
