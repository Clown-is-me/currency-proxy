import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("currency-api")

app = FastAPI(title="EUR->BYN Arbitrage Calculator", version="1.0.0")

# CORS для локальной разработки и мобильного приложения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене замените на конкретный домен/packagename
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Конфигурация ---
CACHE_FILE = Path("rates_cache.json")
CACHE_TTL_SECONDS = 15 * 60  # Кэш живёт 15 минут
RENDER_PORT = int(os.environ.get("PORT", 8000))

# --- Pydantic модели ---
class ChainResult(BaseModel):
    bank_name: str
    eur_rub_buy: float
    rub_byn_buy: float
    eur_byn_direct: float
    cross_rate: float
    profit_coeff: float  # (cross / direct) - 1
    link: Optional[str] = None

class APIResponse(BaseModel):
    chains: List[ChainResult]
    last_updated: str
    is_cached: bool
    source_status: str = "ok"

# --- Менеджер кэша ---
class CacheManager:
    def __init__(self, ttl: int = CACHE_TTL_SECONDS):
        self.ttl = ttl

    def load(self) -> Optional[APIResponse]:
        if not CACHE_FILE.exists():
            return None
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Проверка срока жизни
            if time.time() - data.get("timestamp", 0) > self.ttl:
                logger.info("⏳ Кэш истёк, требуется обновление")
                return None
            return APIResponse(**data["payload"])
        except Exception as e:
            logger.warning(f"⚠️ Ошибка чтения кэша: {e}")
            return None

    def save(self, response: APIResponse):
        try:
            payload = response.model_dump()
            data = {"timestamp": time.time(), "payload": payload}
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("💾 Кэш успешно сохранён")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения кэша: {e}")

cache_mgr = CacheManager()

# --- Заглушка для Шага 2 и 3 ---
# Здесь будет подключаться реальный парсер + калькулятор
async def fetch_and_calculate() -> APIResponse:
    logger.info("🔍 Запуск парсинга и расчётов...")
    # TODO: Step 2 → Парсинг banki.ru и myfin.by
    # TODO: Step 3 → Фильтрация, расчёт cross_rate, сортировка топ-10
    
    # Временные моковые данные для проверки работы API
    mock_chains = [
        ChainResult(
            bank_name="ПримерБанк",
            eur_rub_buy=98.45,
            rub_byn_buy=0.0318,
            eur_byn_direct=3.12,
            cross_rate=98.45 * 0.0318,
            profit_coeff=(98.45 * 0.0318 / 3.12) - 1,
            link="https://example.com"
        )
    ]
    return APIResponse(
        chains=mock_chains,
        last_updated=datetime.now(timezone.utc).isoformat(),
        is_cached=False,
        source_status="mock_data"
    )

# --- Эндпоинты ---
@app.get("/api/chains", response_model=APIResponse)
async def get_chains(force_refresh: bool = Query(False, description="Принудительное обновление")):
    # 1. Проверяем кэш
    cached = cache_mgr.load()
    if cached and not force_refresh:
        cached.is_cached = True
        cached.source_status = "cached"
        return cached

    # 2. Пытаемся получить свежие данные
    try:
        fresh_data = await fetch_and_calculate()
        cache_mgr.save(fresh_data)
        return fresh_data
    except Exception as e:
        logger.error(f"🔥 Ошибка парсинга: {e}")
        # 3. Fallback: если парсинг упал, отдаём последний кэш (даже если просрочен)
        fallback = cache_mgr.load()
        if fallback:
            fallback.is_cached = True
            fallback.source_status = "error_fallback_to_cache"
            return fallback
        raise HTTPException(status_code=502, detail="Не удалось получить курсы и нет сохранённого кэша")

@app.post("/api/refresh", response_model=APIResponse)
async def force_refresh():
    return await get_chains(force_refresh=True)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cache_exists": CACHE_FILE.exists(),
        "port": RENDER_PORT
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=RENDER_PORT, reload=True)
