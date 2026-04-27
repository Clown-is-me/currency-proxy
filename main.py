from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

def clean_rate(val: str) -> float:
    try:
        if not val:
            return 0.0
        cleaned = re.sub(r'[^\d.]', '', val.replace(',', '.'))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

cache = {"data": None, "updated": 0}

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/rates")
async def get_rates():
    try:
        if cache["data"] and (time.time() - cache["updated"]) < 300:
            return cache["data"]
        
        all_rates = []
        errors = []
        
        # === MYFIN.BY ===
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
                resp = await client.get("https://myfin.by/currency/minsk")
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Пробуем разные селекторы
                rows = soup.find_all('tr')
                print(f"Myfin: найдено {len(rows)} строк в таблицах")
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 5:
                        try:
                            # Пробуем извлечь данные
                            bank_text = cells[0].get_text(strip=True)
                            curr_text = cells[1].get_text(strip=True).upper()
                            
                            # Проверяем, похоже ли на валюту
                            if curr_text in ['USD', 'EUR', 'RUB', 'BYN']:
                                buy_text = cells[3].get_text(strip=True)
                                sell_text = cells[4].get_text(strip=True)
                                
                                buy = clean_rate(buy_text)
                                sell = clean_rate(sell_text)
                                
                                if buy > 0 and sell > 0:
                                    all_rates.append({
                                        "bank": bank_text,
                                        "currency_from": curr_text,
                                        "currency_to": "BYN",
                                        "buy": round(buy, 4),
                                        "sell": round(sell, 4),
                                        "source": "myfin_by"
                                    })
                                    # Обратная пара
                                    all_rates.append({
                                        "bank": bank_text,
                                        "currency_from": "BYN",
                                        "currency_to": curr_text,
                                        "buy": round(1/sell, 6),
                                        "sell": round(1/buy, 6),
                                        "source": "myfin_by"
                                    })
                        except Exception as e:
                            continue
                            
        except Exception as e:
            errors.append(f"Myfin: {str(e)}")
            print(f"Myfin error: {e}")
        
        # === BANKI.RU ===
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
                resp = await client.get("https://www.banki.ru/products/currency/cb/")
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                rows = soup.find_all('tr')
                print(f"Banki: найдено {len(rows)} строк")
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 5:
                        try:
                            bank_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                            curr_text = cells[0].get_text(strip=True).upper() if len(cells) > 0 else ""
                            
                            if curr_text in ['USD', 'EUR', 'RUB']:
                                buy_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                                sell_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                                
                                buy = clean_rate(buy_text)
                                sell = clean_rate(sell_text)
                                
                                if buy > 0 and sell > 0:
                                    all_rates.append({
                                        "bank": bank_text,
                                        "currency_from": curr_text,
                                        "currency_to": "RUB",
                                        "buy": round(buy, 4),
                                        "sell": round(sell, 4),
                                        "source": "banki_ru"
                                    })
                                    all_rates.append({
                                        "bank": bank_text,
                                        "currency_from": "RUB",
                                        "currency_to": curr_text,
                                        "buy": round(1/sell, 6),
                                        "sell": round(1/buy, 6),
                                        "source": "banki_ru"
                                    })
                        except:
                            continue
                            
        except Exception as e:
            errors.append(f"Banki: {str(e)}")
            print(f"Banki error: {e}")
        
        result = {
            "status": "ok",
            "updated": datetime.now(timezone.utc).isoformat(),
            "total": len(all_rates),
            "rates": all_rates,
            "debug": {
                "errors": errors,
                "myfin_rows": len(soup.find_all('tr')) if 'soup' in dir() else 0
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
