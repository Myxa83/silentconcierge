import os
import json

# 📂 Шлях до папки config
CONFIG_DIR = os.path.dirname(__file__)

# 🟢 Кеш для зчитаних json
_configs = {}

def load_json(filename: str):
    """
    Завантажує JSON з папки config. 
    Використовуй: load_json("status_phrases.json")
    """
    global _configs
    if filename in _configs:
        return _configs[filename]

    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ JSON {filename} не знайдено в {CONFIG_DIR}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        _configs[filename] = data
        return data


def reload_json(filename: str):
    """
    Примусово перечитати JSON (якщо треба оновити без рестарту бота).
    """
    path = os.path.join(CONFIG_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        _configs[filename] = data
        return data