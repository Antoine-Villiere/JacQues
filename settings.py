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
            "groq_api_key": "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",
            "llama_parse_key": "llx-sdVBP1nuIQh2S8T5oLRzu5hncCrmRjbWcT2s1q3zflHV0YtS",
            "brave_api_key": "BSA6vLQFcC_DmOqaTk4Nm8jLF1sqTxe"
        }
