#!/usr/bin/env python3

import os
import pathlib
import re
import shlex
import subprocess
import sys
import urllib.request


PASARGOD_PATH = pathlib.Path(__file__).parent.resolve()
ENV_FILE = PASARGOD_PATH / ".env"
REQUIREMENTS_FILE = PASARGOD_PATH / "requirements.txt"
MAIN_FILE = PASARGOD_PATH / "main.py"
CLI_FILE = PASARGOD_PATH / "pasarguard-cli.py"
PYTHON314 = pathlib.Path("/usr/bin/python3.14")
SYSTEMD_DIRECTORY = pathlib.Path("/etc/systemd/system")


def step(message: str) -> None:
    print(f"\n\033[1;36m==>\033[0m {message}")


def error(message: str, exit_code: int = 1) -> None:
    print(f"\n\033[1;31mERROR:\033[0m {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def run(
    command: list[str],
    cwd: pathlib.Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    printable = " ".join(shlex.quote(str(part)) for part in command)
    print(f"\033[0;33m$ {printable}\033[0m")

    try:
        return subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd) if cwd else None,
            check=check,
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

    if not CLI_FILE.is_file():
        missing.append("pasarguard-cli.py")

    if missing:
        error(
            "Put this installer in the Pasargod project directory. "
            f"Missing files: {', '.join(missing)}"
        )


def ask_value(title: str, default: str) -> str:
    value = input(f"{title} [default: {default}]: ").strip()
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


def install_system_dependencies() -> None:
    step("Installing Python 3.14 and build dependencies")

    commands = [
        ["apt-get", "update"],
        [
            "apt-get",
            "install",
            "-y",
            "software-properties-common",
            "ca-certificates",
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

    if not PYTHON314.is_file():
        error("Python 3.14 installation failed: /usr/bin/python3.14 not found.")

    run([str(PYTHON314), "--version"])


def set_python314_as_command_default() -> None:
    step("Setting Python 3.14 as the default shell Python")

    # /usr/bin/python3 remains untouched because Ubuntu system tools depend on it.
    # /usr/local/bin normally comes before /usr/bin in PATH.
    run(
        [
            "ln",
            "-sfn",
            str(PYTHON314),
            "/usr/local/bin/python3",
        ]
    )
    run(
        [
            "ln",
            "-sfn",
            str(PYTHON314),
            "/usr/local/bin/python",
        ]
    )

    pip_wrapper = """#!/bin/sh
exec /usr/bin/python3.14 -m pip "$@"
"""

    for wrapper_path in (
        pathlib.Path("/usr/local/bin/pip3"),
        pathlib.Path("/usr/local/bin/pip"),
    ):
        wrapper_path.write_text(pip_wrapper, encoding="utf-8")
        os.chmod(wrapper_path, 0o755)

    # Verify the command defaults using the same PATH expected for normal shells.
    command_env = os.environ.copy()
    command_env["PATH"] = (
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )

    for command in (
        ["python3", "--version"],
        ["python", "--version"],
        ["pip3", "--version"],
        ["pip", "--version"],
    ):
        printable = " ".join(shlex.quote(part) for part in command)
        print(f"\033[0;33m$ {printable}\033[0m")
        try:
            subprocess.run(
                command,
                check=True,
                text=True,
                env=command_env,
            )
        except FileNotFoundError:
            error(f"Command not found after configuring defaults: {command[0]}")
        except subprocess.CalledProcessError as exc:
            error(
                f"Default command verification failed with exit code "
                f"{exc.returncode}: {printable}"
            )


def prepare_python314_packaging_tools() -> None:
    step("Preparing pip, setuptools and wheel for Python 3.14")

    pip_check = run(
        [str(PYTHON314), "-m", "pip", "--version"],
        check=False,
    )

    if pip_check.returncode != 0:
        print("pip is not available for Python 3.14; installing it with get-pip.py.")

        get_pip_file = pathlib.Path("/tmp/get-pip.py")

        try:
            urllib.request.urlretrieve(
                "https://bootstrap.pypa.io/get-pip.py",
                get_pip_file,
            )
        except Exception as exc:
            error(f"Could not download get-pip.py: {exc}")

        run(
            [
                str(PYTHON314),
                str(get_pip_file),
                "--ignore-installed",
                "--break-system-packages",
            ]
        )

    # Install a clean, current packaging toolchain into /usr/local.
    # --ignore-installed prevents pip from trying to uninstall Debian packages
    # that do not contain pip RECORD metadata.
    run(
        [
            str(PYTHON314),
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--break-system-packages",
            "--no-cache-dir",
            "pip",
            "setuptools",
            "wheel",
            "build",
        ]
    )

    run([str(PYTHON314), "-m", "pip", "--version"])

    run(
        [
            str(PYTHON314),
            "-c",
            (
                "import pip, setuptools, wheel; "
                "print('pip:', pip.__version__, pip.__file__); "
                "print('setuptools:', setuptools.__version__, setuptools.__file__); "
                "print('wheel:', wheel.__version__, wheel.__file__)"
            ),
        ]
    )


def install_requirements() -> None:
    step("Installing requirements with Python 3.14")

    run(
        [
            "env",
            "SETUPTOOLS_USE_DISTUTILS=local",
            str(PYTHON314),
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
            "--break-system-packages",
            "--ignore-installed",
            "--use-pep517",
            "--no-cache-dir",
        ],
        cwd=PASARGOD_PATH,
    )


def run_database_migrations() -> None:
    step("Applying Alembic database migrations")

    run(
        [
            "python3",
            "-m",
            "alembic",
            "upgrade",
            "head",
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
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStartPre=python3 -m alembic upgrade head
ExecStart=python3 main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

    service_file.write_text(service_content, encoding="utf-8")
    os.chmod(service_file, 0o644)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", service_name])

    return service_name


def generate_owner_temp_key() -> None:
    step("Generating owner temporary access key")

    run(
        [
            "python3.14",
            "pasarguard-cli.py",
            "generate-temp-key",
        ],
        cwd=PASARGOD_PATH,
    )


def main() -> None:
    require_root()
    check_required_files()

    panel_name, settings = collect_settings()

    write_env(settings)
    install_system_dependencies()
    prepare_python314_packaging_tools()
    set_python314_as_command_default()
    install_requirements()
    run_database_migrations()
    service_name = create_systemd_service(panel_name)
    generate_owner_temp_key()

    print("\n\033[1;32mInstallation completed successfully.\033[0m")
    print(f"Python: {PYTHON314}")
    print(f"Project path: {PASARGOD_PATH}")
    print(f"Service: {service_name}")
    print(f"Status: systemctl status {service_name} --no-pager -l")
    print(f"Logs: journalctl -u {service_name} -f")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error("Installation cancelled.", 130)
