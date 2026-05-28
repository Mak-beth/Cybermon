import yaml

def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    config = load_config()
    print("=== Cybermon Config ===")
    print(f"Failed login threshold : {config['detection']['failed_logins']['threshold']}")
    print(f"Time window (min)      : {config['detection']['failed_logins']['time_window_minutes']}")
    print(f"Restricted resources   : {config['detection']['unauthorized_access']['restricted_resources']}")
    print(f"Business hours         : {config['detection']['off_hours_logins']['business_hours_start']} - {config['detection']['off_hours_logins']['business_hours_end']}")
    print(f"DB path                : {config['storage']['db_path']}")
    print(f"Dashboard              : {config['dashboard']['host']}:{config['dashboard']['port']}")
    print("Config loaded successfully.")
