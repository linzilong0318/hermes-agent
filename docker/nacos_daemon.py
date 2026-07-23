"""
Nacos service registration and heartbeat daemon for Hermes Docker container.

Designed to run as an s6-overlay supervised longrun service.  Registers the
container as a Nacos instance and sends periodic heartbeats until terminated.

Environment variables (all optional except NACOS_SERVER_ADDRESSES):
    NACOS_SERVER_ADDRESSES     Nacos server address (e.g. "10.120.7.99:8848")
    NACOS_NAMESPACE            Nacos namespace id
    NACOS_GROUP_NAME           Group name (default: DEFAULT_GROUP)
    NACOS_SERVICE_NAME         Service name (default: hermes-agent)
    NACOS_SERVICE_PORT         Service port (default: 8642)
    NACOS_USERNAME             Nacos username  (default: nacos)
    NACOS_PASSWORD             Nacos password  (default: nacos)
    NACOS_HEARTBEAT_INTERVAL   Heartbeat interval in seconds (default: 5)
"""

import logging
import os
import socket
import sys
import time
from dataclasses import dataclass, field

import nacos

logger = logging.getLogger("nacos-daemon")
_LOG_FORMAT = "%(asctime)s [nacos-daemon] %(levelname)s %(message)s"


@dataclass
class NacosConfig:
    server_addresses: str = field(
        default_factory=lambda: os.getenv("NACOS_SERVER_ADDRESSES", "127.0.0.1:8848")
    )
    namespace: str = field(default_factory=lambda: os.getenv("NACOS_NAMESPACE", ""))
    group_name: str = field(
        default_factory=lambda: os.getenv("NACOS_GROUP_NAME", "DEFAULT_GROUP")
    )
    service_name: str = field(
        default_factory=lambda: os.getenv("NACOS_SERVICE_NAME", "hermes-agent")
    )
    service_port: int = field(
        default_factory=lambda: int(os.getenv("NACOS_SERVICE_PORT", "8642"))
    )
    username: str = field(default_factory=lambda: os.getenv("NACOS_USERNAME", "nacos"))
    password: str = field(default_factory=lambda: os.getenv("NACOS_PASSWORD", "nacos"))
    heartbeat_interval: int = field(
        default_factory=lambda: int(os.getenv("NACOS_HEARTBEAT_INTERVAL", "5"))
    )
    heartbeat_retry_interval: int = field(default=1)


def _container_ip() -> str:
    """Discover the container's routable IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        stream=sys.stderr,  # s6 captures stderr into its log system
    )


def main() -> None:
    _setup_logging()
    cfg = NacosConfig()
    service_ip = _container_ip()

    logger.info(
        "Registering %s -> %s:%d (namespace=%s, group=%s)",
        cfg.service_name,
        service_ip,
        cfg.service_port,
        cfg.namespace or "(public)",
        cfg.group_name,
    )

    # --- Nacos client ---
    try:
        client = nacos.NacosClient(
            server_addresses=cfg.server_addresses,
            namespace=cfg.namespace,
            username=cfg.username,
            password=cfg.password,
        )
        logger.info("Nacos client connected")
    except Exception as e:
        logger.error("Failed to connect to Nacos: %s", e)
        sys.exit(1)

    # --- Register instance ---
    try:
        ok = client.add_naming_instance(
            service_name=cfg.service_name,
            ip=service_ip,
            port=cfg.service_port,
            group_name=cfg.group_name,
            healthy=True,
            metadata={"version": "1.0.0", "weight": "1"},
        )
        if ok:
            logger.info(
                "Registered %s (%s:%d)",
                cfg.service_name,
                service_ip,
                cfg.service_port,
            )
        else:
            logger.error("Registration returned False — instance may already exist")
    except Exception as e:
        logger.error("Registration failed: %s", e)
        sys.exit(1)

    # --- Heartbeat loop ---
    instance_info = {
        "service_name": cfg.service_name,
        "ip": service_ip,
        "port": cfg.service_port,
        "cluster_name": "DEFAULT",
        "group_name": cfg.group_name,
        "metadata": {"version": "1.0.0", "weight": 1},
    }

    logger.info(
        "Entering heartbeat loop (interval=%ds)", cfg.heartbeat_interval
    )
    while True:
        try:
            client.send_heartbeat(**instance_info)
            time.sleep(cfg.heartbeat_interval)
        except Exception as e:
            logger.error("Heartbeat failed: %s — retrying in %ds", e, cfg.heartbeat_retry_interval)
            time.sleep(cfg.heartbeat_retry_interval)


if __name__ == "__main__":
    main()
