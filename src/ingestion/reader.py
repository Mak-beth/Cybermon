import os


def read_log_file(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Log file not found: {filepath}")
    with open(filepath, "r") as f:
        return [line.rstrip("\n") for line in f if line.strip()]
