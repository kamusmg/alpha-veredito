import requests
import pandas as pd
import json
from datetime import datetime

def get_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
    resp = requests.get(url)
    data = resp.json()
    return float(data['price'])

with open('sinais.json', 'r') as f:
    signals = json.load(f)

trades = []

for signal in signals:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    symbol = signal['symbol']
    side = signal['side']
    entry = signal['entry']
    target = signal['target']
    stop_loss = signal['stop_loss']
    
    try:
        current_price = get_price(symbol)
    except Exception as e:
        print(f"Erro ao buscar preço de {symbol}: {e}")
        current_price = None

    # Calcula lucro/prejuízo (%)
    if current_price is not None:
        if side.upper() == "BUY":
            profit_pct = ((current_price - entry) / entry) * 100
        else:  # SELL
            profit_pct = ((entry - current_price) / entry) * 100
        profit_pct = round(profit_pct, 2)
    else:
        profit_pct = None

    trade = {
        "timestamp": now,
        "symbol": symbol,
        "side": side,
        "preco_entrada": entry,
        "preco_atual": current_price,
        "alvo": target,
        "stop": stop_loss,
        "lucro_%": profit_pct
    }
    trades.append(trade)
    print(f"{now} - {side} {symbol} | Entrada: {entry} | Preço Atual: {current_price} | Lucro/Prejuízo: {profit_pct}%")

df = pd.DataFrame(trades)
df.to_csv("simulador_trades.csv", index=False)
print("Trades salvos em simulador_trades.csv")
