from functions.IMPORT import json


def update_setting(key, value):
    settings = load_settings()
    settings[key] = value
    save_settings(settings)


def save_settings(settings):
    with open('./assets/app_settings.json', 'w') as f:
        json.dump(settings, f)


def load_settings():
    try:
        with open('./assets/app_settings.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "groq_api_key": "",
            "llama_parse_key": "",
            "brave_api_key": ""
        }