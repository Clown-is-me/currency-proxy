from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

def clean_rate(val: str) -> float:
    """Превращает '3,250' или '3.25' в 3.25"""
    return float(re.sub(r'[^\d.]', '', val.replace(',', '.')))

async def fetch_myfin() -> list[dict]:
    """Парсим myfin.by (таблица курсов банков)"""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get("https://myfin.by/currency/minsk")
        soup = BeautifulSoup(resp.text, "lxml")
    
    rates = []
    # Селекторы могут меняться. Если вернёт пусто, откройте DevTools → Elements и обновите .class
    for row in soup.select("table.currency-table tbody tr"):
        cols = row.select("td")
        if len(cols) < 6: continue
        
        bank = cols[0].get_text(strip=True)
        curr = cols[1].get_text(strip=True).upper()
        if curr not in ("USD", "EUR", "RUB"): continue
        
        buy = clean_rate(cols[3].get_text(strip=True))
        sell = clean_rate(cols[4].get_text(strip=True))
        if buy == 0 or sell == 0: continue
        
        rates.append({
            "bank": bank,
            "currency_from": curr,
            "currency_to": "BYN",
            "buy": buy,    # Банк покупает вашу валюту за BYN
            "sell": sell,  # Банк продаёт вам валюту за BYN
            "source": "myfin_by"
        })
        # Обратная пара: BYN → Валюта
        rates.append({
            "bank": bank,
            "currency_from": "BYN",
            "currency_to": curr,
            "buy": 1/sell,
            "sell": 1/buy,
            "source": "myfin_by"
        })
    return rates

async def fetch_banki() -> list[dict]:
    """Парсим banki.ru (виджет курсов)"""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get("https://www.banki.ru/products/currency/cb/")
        soup = BeautifulSoup(resp.text, "lxml")
    
    rates = []
    for row in soup.select("table.js-cb-table tbody tr"):
        cols = row.select("td")
        if len(cols) < 5: continue
        
        bank = cols[1].get_text(strip=True)
        curr = cols[0].get_text(strip=True).upper()
        if curr not in ("USD", "EUR", "RUB"): continue
        
        buy = clean_rate(cols[3].get_text(strip=True))
        sell = clean_rate(cols[4].get_text(strip=True))
        if buy == 0 or sell == 0: continue
        
        rates.append({
            "bank": bank,
            "currency_from": curr,
            "currency_to": "RUB",
            "buy": buy,
            "sell": sell,
            "source": "banki_ru"
        })
        rates.append({
            "bank": bank,
            "currency_from": "RUB",
            "currency_to": curr,
            "buy": 1/sell,
            "sell": 1/buy,
            "source": "banki_ru"
        })
    return rates

# Простое кэширование на 5 минут, чтобы не парсить при каждом запросе
_cache = {"data": None, "updated": 0}

@app.get("/api/rates")
async def get_rates():
    import time
    if _cache["data"] and (time.time() - _cache["updated"]) < 300:
        return _cache["data"]
    
    try:
        by = await fetch_myfin()
        ru = await fetch_banki()
        all_rates = by + ru
        
        _cache["data"] = {
            "status": "ok",
            "updated": datetime.now(timezone.utc).isoformat(),
            "total": len(all_rates),
            "rates": all_rates
        }
        _cache["updated"] = time.time()
        return _cache["data"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка парсинга: {str(e)}")

@app.get("/health")
async def health(): return {"status": "running"}