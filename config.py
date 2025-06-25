"""
Конфигурация для Telegram-бота рулетки подарков
"""
import os
import re
from typing import Optional
from dataclasses import dataclass

@dataclass
class Config:
    """Класс конфигурации с валидацией"""
    bot_token: str
    admin_id: int
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    max_attempts: int = 2
    debug: bool = False
    
    def __post_init__(self):
        """Валидация конфигурации после инициализации"""
        if not self.bot_token:
            raise ValueError("BOT_TOKEN не может быть пустым")
        
        if self.admin_id <= 0:
            raise ValueError("ADMIN_ID должен быть положительным числом")
        
        # Валидация секретного токена вебхука
        if self.webhook_secret:
            if not re.match(r"^[A-Za-z0-9_-]{1,256}$", self.webhook_secret):
                raise ValueError(
                    "WEBHOOK_SECRET содержит недопустимые символы. "
                    "Разрешены только буквы (A-Z, a-z), цифры (0-9), дефис (-) и подчеркивание (_)."
                )

def load_config() -> Config:
    """Загружает конфигурацию из переменных окружения"""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("Необходимо установить переменную окружения BOT_TOKEN")
    
    admin_id_str = os.getenv("ADMIN_ID")
    if not admin_id_str:
        raise ValueError("Необходимо установить переменную окружения ADMIN_ID")
    
    try:
        admin_id = int(admin_id_str)
    except ValueError:
        raise ValueError("Переменная окружения ADMIN_ID должна быть числом")
    
    webhook_url = os.getenv("RENDER_EXTERNAL_URL")
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "2"))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    return Config(
        bot_token=bot_token,
        admin_id=admin_id,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        max_attempts=max_attempts,
        debug=debug
    )

# Глобальный экземпляр конфигурации
config = load_config() 