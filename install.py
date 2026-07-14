#!/usr/bin/env python3

import getpass
import os
import pathlib
import re
import shlex
import subprocess
import sys


PASARGOD_PATH = pathlib.Path(__file__).parent.resolve()
ENV_FILE = PASARGOD_PATH / ".env"
REQUIREMENTS_FILE = PASARGOD_PATH / "requirements.txt"
MAIN_FILE = PASARGOD_PATH / "main.py"
SYSTEMD_DIRECTORY = pathlib.Path("/etc/systemd/system")


def step(message: str) -> None:
    print(f"\n\033[1;36m==>\033[0m {message}")


def error(message: str, exit_code: int = 1) -> None:
    print(f"\n\033[1;31mERROR:\033[0m {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def run(command: list[str], cwd: pathlib.Path | None = None) -> None:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"\033[0;33m$ {printable}\033[0m")

    try:
        subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        error(f"Command not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        error(f"Command failed with exit code {exc.returncode}: {printable}")


def require_root() -> None:
    if os.geteuid() != 0:
        error("Run the installer as root: sudo python3 install.py")


def check_required_files() -> None:
    missing: list[str] = []

    if not MAIN_FILE.is_file():
        missing.append("main.py")

    if not REQUIREMENTS_FILE.is_file():
        missing.append("requirements.txt")

    if missing:
        error(
            "Put the installer inside the Pasargod project directory. "
            f"Missing files: {', '.join(missing)}"
        )


def ask_value(title: str, default: str) -> str:
    value = input(f"{title} [default: {default}]: ").strip()
    return value or default


def ask_password(title: str, default: str) -> str:
    value = getpass.getpass(
        f"{title} [default: {default}; hidden input]: "
    )
    return value or default


def ask_panel_name() -> str:
    while True:
        panel_name = input("Panel name for pasargod-{Name}: ").strip()

        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", panel_name):
            return panel_name

        print(
            "Panel name must contain only letters, numbers, dots, "
            "underscores or hyphens."
        )


def ask_port() -> str:
    while True:
        value = ask_value("UVICORN_PORT", "3000")

        try:
            port = int(value)
        except ValueError:
            print("Port must be a number.")
            continue

        if 1 <= port <= 65535:
            return str(port)

        print("Port must be between 1 and 65535.")


def ask_boolean() -> str:
    while True:
        value = ask_value(
            "DISABLE_RECORDING_NODE_USAGE",
            "False",
        ).lower()

        if value in {"false", "0", "no", "n", "off"}:
            return "False"

        if value in {"true", "1", "yes", "y", "on"}:
            return "True"

        print("Enter True or False.")


def dotenv_escape(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def collect_settings() -> tuple[str, dict[str, str]]:
    step("Pasargod configuration")

    panel_name = ask_panel_name()

    settings = {
        "UVICORN_HOST": ask_value("UVICORN_HOST", "0.0.0.0"),
        "UVICORN_PORT": ask_port(),
        "DISABLE_RECORDING_NODE_USAGE": ask_boolean(),
        "SUDO_USERNAME": ask_value("SUDO_USERNAME", "root"),
        "SUDO_PASSWORD": ask_password("SUDO_PASSWORD", "12345"),
    }

    return panel_name, settings


def write_env(settings: dict[str, str]) -> None:
    step(f"Writing {ENV_FILE}")

    content = "\n".join(
        f"{key}={dotenv_escape(value)}"
        for key, value in settings.items()
    ) + "\n"

    temporary_file = PASARGOD_PATH / ".env.tmp"
    temporary_file.write_text(content, encoding="utf-8")
    os.chmod(temporary_file, 0o600)
    temporary_file.replace(ENV_FILE)
    os.chmod(ENV_FILE, 0o600)


def install_dependencies() -> None:
    step("Installing system dependencies")

    commands = [
        ["apt-get", "update"],
        [
            "apt-get",
            "install",
            "-y",
            "software-properties-common",
        ],
        [
            "add-apt-repository",
            "-y",
            "ppa:deadsnakes/ppa",
        ],
        ["apt-get", "update"],
        [
            "apt-get",
            "install",
            "-y",
            "python3.14",
            "libpq-dev",
            "python3-dev",
            "python3.14-venv",
            "python3.14-dev",
            "build-essential",
            "libssl-dev",
            "libffi-dev",
            "python3-full",
            "python3-pip",
        ],
    ]

    for command in commands:
        run(command)


def install_requirements() -> None:
    step("Installing requirements globally with pip3")

    run(
        [
            "pip3",
            "install",
            "-r",
            "requirements.txt",
            "--break-system-packages",
            "--ignore-installed",
        ],
        cwd=PASARGOD_PATH,
    )


def create_systemd_service(panel_name: str) -> str:
    service_name = f"pasargod-{panel_name}.service"
    service_file = SYSTEMD_DIRECTORY / service_name

    step(f"Creating systemd service: {service_name}")

    service_content = f"""[Unit]
Description=Pasargod Panel ({panel_name})
Wants=network-online.target
After=network-online.target

[Service]
WorkingDirectory={PASARGOD_PATH}
ExecStart=python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
"""

    service_file.write_text(service_content, encoding="utf-8")
    os.chmod(service_file, 0o644)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", service_name])

    return service_name


def main() -> None:
    require_root()
    check_required_files()

    panel_name, settings = collect_settings()

    write_env(settings)
    install_dependencies()
    install_requirements()
    service_name = create_systemd_service(panel_name)

    print("\n\033[1;32mInstallation completed successfully.\033[0m")
    print(f"Project path: {PASARGOD_PATH}")
    print(f"Service: {service_name}")
    print(f"Status: systemctl status {service_name} --no-pager -l")
    print(f"Logs: journalctl -u {service_name} -f")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error("Installation cancelled.", 130)
