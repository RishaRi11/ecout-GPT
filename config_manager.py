import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "language": "ru",
        "fonts": {
        "sync": True,
        "common":  {"family": "Arial", "size": 16, "bold": False, "italic": False, "color": "#ffffff"},
        "speaker": {"family": "Arial", "size": 16, "bold": False, "italic": False, "color": "#ffffff"},
        "user":    {"family": "Arial", "size": 16, "bold": False, "italic": False, "color": "#ffffff"},
        "gpt":     {"family": "Arial", "size": 16, "bold": False, "italic": False, "color": "#ffffff"}
    }
}

def load_config():
    
    """
    Загружает конфиг и «дополняет» недостающие поля значениями по умолчанию.
    В итоге всегда возвращается полный набор ключей,
    включая fonts / language и т.д.
    """
    cfg = DEFAULT_CONFIG.copy()

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                # верхний уровень
                cfg.update({k: v for k, v in user_cfg.items() if k != "fonts"})
                # deep-merge для fonts
                if isinstance(user_cfg.get("fonts"), dict):
                    fonts = cfg["fonts"].copy()
                    fonts.update(user_cfg["fonts"])
                    cfg["fonts"] = fonts
        except Exception:
            # повреждённый JSON – игнорируем, берём дефолт
            pass

    # сразу сохраняем дополнённый файл, чтобы не терять изменения
    save_config(cfg)
    return cfg

def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)