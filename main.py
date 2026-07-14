import ipaddress
import os
import socket
import ssl

import click
import uvicorn
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from app import create_app
from app.nats import require_nats_if_multiworker
from app.utils.logger import LOGGING_CONFIG, get_logger
from config import logging_settings, runtime_settings, server_settings

logger = get_logger("uvicorn-main")

workers = server_settings.workers or 1
if workers < 1:
    logger.warning(f"Invalid UVICORN_WORKERS value '{server_settings.workers}', defaulting to 1.")
    workers = 1
elif workers > 1:
    require_nats_if_multiworker(workers)


if __name__ == "__main__":
    bind_args = {}

    if server_settings.ssl_certfile and server_settings.ssl_keyfile:
        bind_args["ssl_certfile"] = server_settings.ssl_certfile
        bind_args["ssl_keyfile"] = server_settings.ssl_keyfile

    if server_settings.uds:
        bind_args["uds"] = server_settings.uds
    else:
        bind_args["host"] = server_settings.host
        bind_args["port"] = server_settings.port
        
    effective_log_level = logging_settings.level
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        LOGGING_CONFIG["loggers"][logger_name]["level"] = effective_log_level

    try:
        uvicorn.run(
            "main:create_app",
            factory=True,
            **bind_args,
            workers=workers,
            reload=runtime_settings.debug,
            log_config=LOGGING_CONFIG,
            log_level=effective_log_level.lower(),
            loop=server_settings.loop,
            proxy_headers=server_settings.proxy_headers,
            forwarded_allow_ips=server_settings.forwarded_allow_ips,
        )
    except FileNotFoundError:
        pass