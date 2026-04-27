from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from datetime import datetime, timezone
import time

app = FastAPI(title="Currency Proxy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Заголовки, которые обходят базовую защиту
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://www.nbrb.by/",
    "Origin": "https://www.nbrb.by",
}

cache = {"data": None, "updated": 0}

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

def add_pair(rates: list, bank: str, from_c: str, to_c: str, mid_rate: float, source: str):
    """Добавляет прямую и обратную пару с фиксированным спредом ±2%"""
    if mid_rate <= 0:
        return
    buy = round(mid_rate * 0.98, 4)
    sell = round(mid_rate * 1.02, 4)
    rates.append({
        "bank": bank,
        "currency_from": from_c,
        "currency_to": to_c,
        "buy": buy,
        "sell": sell,
        "source": source
    })
    # Обратная пара
    if buy > 0 and sell > 0:
        rates.append({
            "bank": bank,
            "currency_from": to_c,
            "currency_to": from_c,
            "buy": round(1/sell, 6),
            "sell": round(1/buy, 6),
            "source": source
        })

@app.get("/api/rates")
async def get_rates():
    try:
        # Кэш на 5 минут
        if cache["data"] and (time.time() - cache["updated"]) < 300:
            return cache["data"]
        
        all_rates = []
        errors = []
        
        # === 1. NBRB.BY (с правильными заголовками) ===
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
                for curr_code in ["USD", "EUR", "RUB"]:
                    try:
                        url = f"https://www.nbrb.by/api/exrates/rates/{curr_code}?parammode=2"
                        resp = await client.get(url)
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            rate = data.get("Cur_OfficialRate")
                            if rate and rate > 0:
                                # RUB идёт за 100 единиц
                                if curr_code == "RUB":
                                    rate = rate / 100.0
                                add_pair(all_rates, "Нацбанк Беларуси", curr_code, "BYN", rate, "nbrb_by")
                                print(f"✅ NBRB {curr_code}: {rate}")
                            else:
                                errors.append(f"NBRB {curr_code}: пустой курс")
                        else:
                            errors.append(f"NBRB {curr_code}: HTTP {resp.status_code}")
                    except Exception as e:
                        errors.append(f"NBRB {curr_code}: {str(e)}")
        except Exception as e:
            errors.append(f"NBRB общий: {str(e)}")
        
        # === 2. ЦБ РФ ===
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://www.cbr-xml-daily.ru/daily_json.js")
                if resp.status_code == 200:
                    data = resp.json()
                    for curr_code in ["USD", "EUR"]:
                        if curr_code in data.get("Valute", {}):
                            rate = data["Valute"][curr_code]["Value"]
                            add_pair(all_rates, "ЦБ РФ", curr_code, "RUB", rate, "cbr_ru")
                    print(f"✅ CBR: добавлены курсы")
                else:
                    errors.append(f"CBR: HTTP {resp.status_code}")
        except Exception as e:
            errors.append(f"CBR: {str(e)}")
        
        # === 3. АВТО-КРОСС-КУРСЫ (если есть и BYN, и RUB курсы) ===
        # Считаем: USD→BYN = (USD→RUB) / (BYN→RUB)
        rub_to_byn = None  # 1 RUB = X BYN
        usd_to_rub = None
        eur_to_rub = None
        
        for r in all_rates:
            if r["currency_from"] == "RUB" and r["currency_to"] == "BYN":
                rub_to_byn = (r["buy"] + r["sell"]) / 2  # Средний курс
            if r["currency_from"] == "USD" and r["currency_to"] == "RUB":
                usd_to_rub = (r["buy"] + r["sell"]) / 2
            if r["currency_from"] == "EUR" and r["currency_to"] == "RUB":
                eur_to_rub = (r["buy"] + r["sell"]) / 2
        
        # Если есть оба компонента — считаем кросс
        if rub_to_byn and usd_to_rub:
            usd_to_byn = usd_to_rub * rub_to_byn
            add_pair(all_rates, "Расчётный кросс", "USD", "BYN", usd_to_byn, "cross_calc")
            print(f"✅ Кросс USD→BYN: {usd_to_byn:.4f}")
        
        if rub_to_byn and eur_to_rub:
            eur_to_byn = eur_to_rub * rub_to_byn
            add_pair(all_rates, "Расчётный кросс", "EUR", "BYN", eur_to_byn, "cross_calc")
            print(f"✅ Кросс EUR→BYN: {eur_to_byn:.4f}")
        
        # === 4. Currate (опционально, с обработкой 403) ===
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://currate.ru/api/?get=rates&pairs=USDRUB,EURRUB,BYNRUB&key=demo"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "200":
                        for pair, rate in data.get("data", {}).items():
                            if len(pair) == 6 and rate > 0:
                                add_pair(all_rates, "Currate", pair[:3], pair[3:], rate, "currate")
        except:
            pass  # Игнорируем ошибки Currate, он не критичен
        
        # Убираем дубликаты (оставляем первый найденный курс для каждой пары)
        seen = set()
        unique_rates = []
        for r in all_rates:
            key = (r["currency_from"], r["currency_to"], r["source"])
            if key not in seen:
                seen.add(key)
                unique_rates.append(r)
        
        result = {
            "status": "ok",
            "updated": datetime.now(timezone.utc).isoformat(),
            "total": len(unique_rates),
            "rates": unique_rates,
            "debug": {
                "errors": errors[:5],  # Последние 5 ошибок
                "sources_used": list(set(r["source"] for r in unique_rates))
            }
        }
        
        cache["data"] = result
        cache["updated"] = time.time()
        
        print(f"📊 Итого: {len(unique_rates)} уникальных курсов")
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "total": 0,
            "rates": []
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
