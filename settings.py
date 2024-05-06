from IMPORT import json


def update_setting(key, value):
    settings = load_settings()
    settings[key] = value
    save_settings(settings)


def save_settings(settings):
    with open('app_settings.json', 'w') as f:
        json.dump(settings, f)


def load_settings():
    try:
        with open('app_settings.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Return default settings if no settings file exists
        return {
            "groq_api_key": "default_groq_key",
            "llama_parse_key": "default_llama_key",
            "brave_api_key": "default_brave_key"
        }
