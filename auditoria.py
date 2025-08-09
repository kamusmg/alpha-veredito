import requests
import pandas as pd
import json
from datetime import datetime
import sys

def get_historical_price(symbol, date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    timestamp = int(dt.timestamp()) * 1000
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval=1h&startTime={timestamp}&endTime={timestamp + 3600*1000}"
    resp = requests.get(url)
    data = resp.json()
    if data and isinstance(data, list):
        close_price = float(data[0][4])  # Preço de fechamento da vela
        return close_price
    return None

if len(sys.argv) < 2:
    print("Uso: python auditoria.py sinais-2025-08-08.json")
    exit(1)

sinais_arquivo = sys.argv[1]

with open(sinais_arquivo, 'r') as f:
    signals = json.load(f)

results = []

for signal in signals:
    symbol = signal['symbol']
    side = signal['side']
    entry = signal['entry']
    target = signal['target']
    stop_loss = signal['stop_loss']
    saida_datahora = signal.get('saida_datahora')  # Pode ser None se não preencher

    if not saida_datahora:
        print(f"Sinal {symbol} está sem 'saida_datahora', pulei.")
        continue

    final_price = get_historical_price(symbol, saida_datahora)

    if final_price:
        if side.upper() == "BUY":
            profit_pct = ((final_price - entry) / entry) * 100
            hit_target = final_price >= target
            hit_stop = final_price <= stop_loss
        else:  # SELL
            profit_pct = ((entry - final_price) / entry) * 100
            hit_target = final_price <= target
            hit_stop = final_price >= stop_loss
        profit_pct = round(profit_pct, 2)
    else:
        profit_pct = None
        hit_target = hit_stop = None

    result = {
        "symbol": symbol,
        "side": side,
        "entrada": entry,
        "saida_datahora": saida_datahora,
        "preco_saida": final_price,
        "target": target,
        "stop_loss": stop_loss,
        "lucro_%": profit_pct,
        "bateu_alvo": hit_target,
        "bateu_stop": hit_stop
    }
    results.append(result)
    print(result)

df = pd.DataFrame(results)
df.to_csv("resultado_auditoria.csv", index=False)
print("Resultado salvo em resultado_auditoria.csv")
