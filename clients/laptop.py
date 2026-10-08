"""One-command launcher. Default: typed pet. --voice: microphone and speaker."""

import argparse
import subprocess
import sys
import time

import httpx

from clients.doctor import main as doctor
from server.config import ROOT, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--say", action="append", default=[])
    args = parser.parse_args()
    if doctor():
        return 1
    cfg = settings()
    host = "127.0.0.1" if cfg.host == "0.0.0.0" else cfg.host
    url = f"http://{host}:{cfg.port}/health"
    process = None
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            try:
                health = client.get(url).json()
            except (httpx.HTTPError, ValueError):
                health = None
            if health is None:
                process = subprocess.Popen(
                    [sys.executable, "-m", "server.app"], cwd=ROOT
                )
                for _ in range(100):
                    if process.poll() is not None:
                        print("The server could not start. Check its message above.")
                        return 1
                    try:
                        health = client.get(url).json()
                        break
                    except (httpx.HTTPError, ValueError):
                        time.sleep(0.1)
            if (
                not health
                or health.get("app") != "robopet-brain"
                or health.get("pet_id") != cfg.pet_id
            ):
                print(
                    "The configured port is unavailable or belongs to another app/pet."
                )
                return 1
            if not health.get("ok"):
                print(
                    "The running server needs setup. Stop it and run the setup doctor."
                )
                return 1
        command = [
            sys.executable,
            "-m",
            "clients.fake_robot" if args.voice else "clients.text_robot",
            "--url",
            f"ws://{host}:{cfg.port}/ws",
        ]
        if not args.voice:
            for prompt in args.say:
                command.extend(["--say", prompt])
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 0
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
