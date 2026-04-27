from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from datetime import datetime, timezone
import time
import traceback

app = FastAPI(title="Currency Proxy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

cache = {"data": None, "updated": 0}
errors_log = []

def log_error(source: str, error: Exception):
    msg = f"{source}: {str(error)}"
    errors_log.append(msg)
    print(f"❌ {msg}")
    if len(errors_log) > 10:
        errors_log.pop(0)

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/rates")
async def get_rates():
    global errors_log
    errors_log = []  # Очищаем логи при каждом запросе
    
    try:
        if cache["data"] and (time.time() - cache["updated"]) < 300:
            return cache["data"]
        
        all_rates = []
        
        # === 1. NBRB.BY (Нацбанк Беларуси) ===
        try:
            print("🔄 Запрос к NBRB.by...")
            async with httpx.AsyncClient(headers=HEADERS, timeout=10.0, follow_redirects=True) as client:
                
                for curr_code, curr_name in [("USD", "Доллар США"), ("EUR", "Евро"), ("RUB", "Российский рубль")]:
                    try:
                        resp = await client.get(f"https://www.nbrb.by/api/exrates/rates/{curr_code}?parammode=2")
                        print(f"NBRB {curr_code}: статус {resp.status_code}")
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            rate = data.get("Cur_OfficialRate")
                            
                            if rate and rate > 0:
                                # Для RUB курс за 100 единиц
                                if curr_code == "RUB":
                                    rate = rate / 100.0
                                
                                buy = round(rate * 0.98, 4)
                                sell = round(rate * 1.02, 4)
                                
                                all_rates.append({
                                    "bank": "Нацбанк Беларуси",
                                    "currency_from": curr_code,
                                    "currency_to": "BYN",
                                    "buy": buy,
                                    "sell": sell,
                                    "source": "nbrb_by"
                                })
                                all_rates.append({
                                    "bank": "Нацбанк Беларуси",
                                    "currency_from": "BYN",
                                    "currency_to": curr_code,
                                    "buy": round(1/sell, 6),
                                    "sell": round(1/buy, 6),
                                    "source": "nbrb_by"
                                })
                                print(f"✅ NBRB {curr_code}: добавлено 2 курса")
                        else:
                            log_error(f"NBRB {curr_code}", Exception(f"HTTP {resp.status_code}"))
                            
                    except Exception as e:
                        log_error(f"NBRB {curr_code}", e)
                        
        except Exception as e:
            log_error("NBRB общий", e)
        
        # === 2. ЦБ РФ ===
        try:
            print("🔄 Запрос к CBR.ru...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://www.cbr-xml-daily.ru/daily_json.js")
                
                if resp.status_code == 200:
                    data = resp.json()
                    for curr_code in ["USD", "EUR"]:
                        if curr_code in data.get("Valute", {}):
                            v = data["Valute"][curr_code]
                            rate = v["Value"]
                            
                            all_rates.append({
                                "bank": "ЦБ РФ",
                                "currency_from": curr_code,
                                "currency_to": "RUB",
                                "buy": round(rate * 0.98, 4),
                                "sell": round(rate * 1.02, 4),
                                "source": "cbr_ru"
                            })
                            all_rates.append({
                                "bank": "ЦБ РФ",
                                "currency_from": "RUB",
                                "currency_to": curr_code,
                                "buy": round(1/(rate*1.02), 6),
                                "sell": round(1/(rate*0.98), 6),
                                "source": "cbr_ru"
                            })
                    print(f"✅ CBR: добавлено курсов")
                    
        except Exception as e:
            log_error("CBR", e)
        
        # === 3. Currate.ru ===
        try:
            print("🔄 Запрос к Currate.ru...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://currate.ru/api/?get=rates&pairs=USDRUB,EURRUB,BYNRUB,USDBYN,EURBYN,RUBBYN&key=demo"
                )
                print(f"Currate: статус {resp.status_code}")
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "200":
                        for pair, rate in data.get("data", {}).items():
                            if len(pair) == 6 and rate and rate > 0:
                                from_c, to_c = pair[:3], pair[3:]
                                buy = round(rate * 0.985, 4)
                                sell = round(rate * 1.015, 4)
                                
                                all_rates.append({
                                    "bank": f"Currate",
                                    "currency_from": from_c,
                                    "currency_to": to_c,
                                    "buy": buy,
                                    "sell": sell,
                                    "source": "currate"
                                })
                                all_rates.append({
                                    "bank": f"Currate",
                                    "currency_from": to_c,
                                    "currency_to": from_c,
                                    "buy": round(1/sell, 6),
                                    "sell": round(1/buy, 6),
                                    "source": "currate"
                                })
                        print(f"✅ Currate: добавлено курсов")
                    else:
                        log_error("Currate", Exception(f"API статус: {data.get('status')}"))
                else:
                    log_error("Currate", Exception(f"HTTP {resp.status_code}"))
                    
        except Exception as e:
            log_error("Currate", e)
        
        result = {
            "status": "ok",
            "updated": datetime.now(timezone.utc).isoformat(),
            "total": len(all_rates),
            "rates": all_rates,
            "debug_errors": errors_log,
            "sources": {
                "nbrb_by": "Нацбанк Беларуси",
                "cbr_ru": "ЦБ РФ", 
                "currate": "Currate.ru"
            }
        }
        
        cache["data"] = result
        cache["updated"] = time.time()
        
        print(f"📊 Итого: {len(all_rates)} курсов, ошибок: {len(errors_log)}")
        return result
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "total": 0,
            "rates": [],
            "debug_errors": errors_log
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
