"""Entry point for CyberMonAgent (.exe when packaged with PyInstaller).

Reads agent_config.yaml (next to the exe) for server details and log path.
Creates the file with safe defaults if it does not exist, then starts the agent.

The agent runs with a visible console window so the user can see status output:
  - One startup line showing the log file and server address
  - One line per batch of lines sent to the server
"""
import argparse
import logging
import os
import sys

import yaml


# ---------------------------------------------------------------------------
# Path helper — all writable files (config, log) live next to the exe
# ---------------------------------------------------------------------------

def _exe_dir() -> str:
    """Directory containing the running exe (or the script in development)."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Logging — always next to the exe / script
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(_exe_dir(), "agent.log"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

# ---------------------------------------------------------------------------
# Config — lives next to the exe, created from defaults on first run
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_FILE = os.path.join(_exe_dir(), "agent_config.yaml")

_DEFAULTS = {
    "server_ip":            "127.0.0.1",
    "server_port":          5001,
    "log_path":             "logs/auth.log",
    "host_id":              "agent-machine-1",
    "api_key":              "CHANGE_ME_BEFORE_DEPLOY",
    "retry_attempts":       3,
    "retry_delay_seconds":  2,
}


def _load_or_create_config(config_file: str) -> dict:
    if not os.path.exists(config_file):
        with open(config_file, "w", encoding="utf-8") as fh:
            yaml.dump(_DEFAULTS, fh, default_flow_style=False)
        print(f"[CyberMonAgent] Created default config at {config_file}")
        print("[CyberMonAgent] Edit server_ip, log_path, and host_id, then restart.")
    with open(config_file, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CyberMonAgent — tails a log file and POSTs new lines to the ingest server."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help="Path to the agent config YAML (default: agent_config.yaml next to the exe). "
             "Give each agent its own config file to run several at once — e.g. to "
             "simulate multiple hosts from one machine.",
    )
    args = parser.parse_args()
    cfg = _load_or_create_config(args.config)

    # Ensure src/ is on the path when running from source
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

    from src.agent.agent import CyberMonAgent

    server_ip   = cfg.get("server_ip",           _DEFAULTS["server_ip"])
    server_port = int(cfg.get("server_port",      _DEFAULTS["server_port"]))
    log_path    = cfg.get("log_path",             _DEFAULTS["log_path"])
    host_id     = cfg.get("host_id",              _DEFAULTS["host_id"])
    api_key     = cfg.get("api_key",              "")

    if not api_key:
        print("[CyberMonAgent] WARNING: no api_key configured — server will reject requests.")
        print("Edit agent_config.yaml and set api_key to match the server's api_key.")

    agent = CyberMonAgent(
        server_ip=server_ip,
        server_port=server_port,
        log_path=log_path,
        host_id=host_id,
        api_key=api_key,
        retry_attempts=int(cfg.get("retry_attempts",      _DEFAULTS["retry_attempts"])),
        retry_delay_seconds=int(cfg.get("retry_delay_seconds", _DEFAULTS["retry_delay_seconds"])),
    )

    try:
        agent.run()
    except KeyboardInterrupt:
        print("\n[CyberMonAgent] Keyboard interrupt — shutting down.")
        agent.stop()
