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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

cache = {"data": None, "updated": 0}

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/rates")
async def get_rates():
    try:
        # Возвращаем кэш если моложе 10 минут
        if cache["data"] and (time.time() - cache["updated"]) < 600:
            return cache["data"]
        
        all_rates = []
        
        # === 1. NBRB.BY (Официальный курс Нацбанка Беларуси) ===
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # USD
                resp = await client.get("https://www.nbrb.by/api/exrates/rates/USD?parammode=2")
                usd_data = resp.json()
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "USD",
                    "currency_to": "BYN",
                    "buy": round(usd_data["Cur_OfficialRate"] * 0.98, 4),
                    "sell": round(usd_data["Cur_OfficialRate"] * 1.02, 4),
                    "source": "nbrb_by"
                })
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "BYN",
                    "currency_to": "USD",
                    "buy": round(1/(usd_data["Cur_OfficialRate"] * 1.02), 6),
                    "sell": round(1/(usd_data["Cur_OfficialRate"] * 0.98), 6),
                    "source": "nbrb_by"
                })
                
                # EUR
                resp = await client.get("https://www.nbrb.by/api/exrates/rates/EUR?parammode=2")
                eur_data = resp.json()
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "EUR",
                    "currency_to": "BYN",
                    "buy": round(eur_data["Cur_OfficialRate"] * 0.98, 4),
                    "sell": round(eur_data["Cur_OfficialRate"] * 1.02, 4),
                    "source": "nbrb_by"
                })
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "BYN",
                    "currency_to": "EUR",
                    "buy": round(1/(eur_data["Cur_OfficialRate"] * 1.02), 6),
                    "sell": round(1/(eur_data["Cur_OfficialRate"] * 0.98), 6),
                    "source": "nbrb_by"
                })
                
                # RUB (за 100 рублей)
                resp = await client.get("https://www.nbrb.by/api/exrates/rates/RUB?parammode=2")
                rub_data = resp.json()
                rub_rate = rub_data["Cur_OfficialRate"] / 100.0  # Нормализуем к 1 RUB
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "RUB",
                    "currency_to": "BYN",
                    "buy": round(rub_rate * 0.98, 4),
                    "sell": round(rub_rate * 1.02, 4),
                    "source": "nbrb_by"
                })
                all_rates.append({
                    "bank": "Нацбанк Беларуси",
                    "currency_from": "BYN",
                    "currency_to": "RUB",
                    "buy": round(1/(rub_rate * 1.02), 6),
                    "sell": round(1/(rub_rate * 0.98), 6),
                    "source": "nbrb_by"
                })
                
        except Exception as e:
            print(f"NBRB error: {e}")
        
        # === 2. ЦБ РФ (Официальный курс) ===
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://www.cbr-xml-daily.ru/daily_json.js")
                cbr_data = resp.json()
                
                # USD
                if "USD" in cbr_data["Valute"]:
                    usd = cbr_data["Valute"]["USD"]
                    all_rates.append({
                        "bank": "ЦБ РФ",
                        "currency_from": "USD",
                        "currency_to": "RUB",
                        "buy": round(usd["Value"] * 0.98, 4),
                        "sell": round(usd["Value"] * 1.02, 4),
                        "source": "cbr_ru"
                    })
                    all_rates.append({
                        "bank": "ЦБ РФ",
                        "currency_from": "RUB",
                        "currency_to": "USD",
                        "buy": round(1/(usd["Value"] * 1.02), 6),
                        "sell": round(1/(usd["Value"] * 0.98), 6),
                        "source": "cbr_ru"
                    })
                
                # EUR
                if "EUR" in cbr_data["Valute"]:
                    eur = cbr_data["Valute"]["EUR"]
                    all_rates.append({
                        "bank": "ЦБ РФ",
                        "currency_from": "EUR",
                        "currency_to": "RUB",
                        "buy": round(eur["Value"] * 0.98, 4),
                        "sell": round(eur["Value"] * 1.02, 4),
                        "source": "cbr_ru"
                    })
                    all_rates.append({
                        "bank": "ЦБ РФ",
                        "currency_from": "RUB",
                        "currency_to": "EUR",
                        "buy": round(1/(eur["Value"] * 1.02), 6),
                        "sell": round(1/(eur["Value"] * 0.98), 6),
                        "source": "cbr_ru"
                    })
                    
        except Exception as e:
            print(f"CBR error: {e}")
        
        # === 3. Currate.ru (Коммерческие курсы) ===
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://currate.ru/api/?get=rates&pairs=USDRUB,EURRUB,BYNRUB,USDBYN,EURBYN,RUBBYN&key=demo"
                )
                data = resp.json()
                
                if data.get("status") == "200":
                    for pair, rate in data.get("data", {}).items():
                        if len(pair) == 6:
                            from_curr = pair[:3]
                            to_curr = pair[3:]
                            buy = round(rate * 0.985, 4)
                            sell = round(rate * 1.015, 4)
                            
                            all_rates.append({
                                "bank": f"Currate ({from_curr}/{to_curr})",
                                "currency_from": from_curr,
                                "currency_to": to_curr,
                                "buy": buy,
                                "sell": sell,
                                "source": "currate"
                            })
                            # Обратная пара
                            all_rates.append({
                                "bank": f"Currate ({to_curr}/{from_curr})",
                                "currency_from": to_curr,
                                "currency_to": from_curr,
                                "buy": round(1/sell, 6),
                                "sell": round(1/buy, 6),
                                "source": "currate"
                            })
                            
        except Exception as e:
            print(f"Currate error: {e}")
        
        result = {
            "status": "ok",
            "updated": datetime.now(timezone.utc).isoformat(),
            "total": len(all_rates),
            "rates": all_rates,
            "sources": {
                "nbrb_by": "Нацбанк Беларуси (официальный)",
                "cbr_ru": "ЦБ РФ (официальный)",
                "currate": "Currate.ru (коммерческие)"
            }
        }
        
        cache["data"] = result
        cache["updated"] = time.time()
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "total": 0,
            "rates": []
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
