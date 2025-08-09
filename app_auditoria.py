import os
import time
import json
import math
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

# =========================
# Config
# =========================
BINANCE_BASE = "https://api.binance.com"   # Spot
INTERVAL = "1m"
USER_AGENT = "LucraAuditor/2.0 (+https://lucra.local)"
APP_DIR = os.path.dirname(__file__)
WATCH_PATH = os.path.join(APP_DIR, "watchlist.json")
HIST_PATH  = os.path.join(APP_DIR, "historico.json")

st.set_page_config(page_title="Lucra Auditor — Live", layout="wide")
st.title("Lucra Auditor — Live Tracking (simples)")
st.caption("Status limpo: EM ABERTO, ✓ ALVO, ✕ STOP ou FECHADO POR TEMPO. Preço em 1m (Binance).")

# =========================
# Util
# =========================
def to_ms(dt_str: str) -> int:
    # Trata as datas como UTC. Se suas datas forem BRT, ajuste aqui.
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def fetch_klines(symbol: str, start_ms: int, end_ms: int, interval: str = INTERVAL) -> pd.DataFrame:
    rows, limit, cur = [], 1000, start_ms
    headers = {"User-Agent": USER_AGENT}
    while cur <= end_ms:
        url = f"{BINANCE_BASE}/api/v3/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": cur,
            "endTime": min(end_ms, cur + (limit-1)*60_000),
            "limit": limit,
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data: break
        rows.extend(data)
        cur = data[-1][6] + 1   # próximo após close_time
        if len(data) < limit: break
        time.sleep(0.03)        # respeitar rate limit
    if not rows:
        return pd.DataFrame(columns=["open_time","open","high","low","close","close_time"])
    df = pd.DataFrame(rows, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","num_trades","taker_base","taker_quote","ignore"
    ])
    df = df[["open_time","open","high","low","close","close_time"]].copy()
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def eval_interval(symbol, side, entry, target, stop, start_ms, end_ms):
    """
    Avalia status no intervalo [start_ms, end_ms].
    Retorna dict: {status, preco_ref, lucro_pct, bateu_alvo, bateu_stop}
    """
    df = fetch_klines(symbol, start_ms, end_ms)
    if df.empty:
        return dict(status="SEM DADOS", preco_ref=None, lucro_pct=None, bateu_alvo=None, bateu_stop=None)

    # Caminho candle a candle: STOP tem prioridade se vem antes do ALVO (para BUY; inverso em SELL)
    bateu_alvo = False
    bateu_stop = False
    preco_exec = None

    for _, r in df.iterrows():
        h, l = r["high"], r["low"]
        if side == "BUY":
            if l <= stop:
                preco_exec = stop; bateu_stop = True; break
            if h >= target:
                preco_exec = target; bateu_alvo = True; break
        else:  # SELL
            if h >= stop:
                preco_exec = stop; bateu_stop = True; break
            if l <= target:
                preco_exec = target; bateu_alvo = True; break

    # Se atingiu alvo/stop no caminho:
    if preco_exec is not None:
        if side == "BUY":
            lucro = ((preco_exec - entry) / entry) * 100 if entry else math.nan
        else:
            lucro = ((entry - preco_exec) / entry) * 100 if entry else math.nan
        return dict(
            status=("✓ ALVO" if bateu_alvo else "✕ STOP"),
            preco_ref=round(preco_exec, 8),
            lucro_pct=None if math.isnan(lucro) else round(lucro, 2),
            bateu_alvo=bateu_alvo,
            bateu_stop=bateu_stop
        )

    # Não bateu: usa close do último candle do intervalo
    last_close = float(df.iloc[-1]["close"])
    if side == "BUY":
        lucro = ((last_close - entry) / entry) * 100 if entry else math.nan
    else:
        lucro = ((entry - last_close) / entry) * 100 if entry else math.nan
    return dict(
        status="EM ABERTO",
        preco_ref=round(last_close, 8),
        lucro_pct=None if math.isnan(lucro) else round(lucro, 2),
        bateu_alvo=False,
        bateu_stop=False
    )

# =========================
# Storage
# =========================
def load_json(path, default):
    if not os.path.isfile(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# Sidebar — Controles
# =========================
with st.sidebar:
    st.header("Importar sinais")
    up = st.file_uploader("JSON de sinais", type=["json"])
    add_btn = st.button("Adicionar ao Watchlist", type="primary")
    st.divider()
    st.header("Atualização")
    show_closed = st.checkbox("Mostrar fechados por tempo", value=True)
    refresh_now = st.button("🔄 Atualizar agora", type="secondary")
    st.caption("Dica: deixe a página aberta e clique em Atualizar quando quiser.")

# =========================
# Watchlist
# =========================
watch = load_json(WATCH_PATH, [])  # lista de sinais
hist  = load_json(HIST_PATH,  [])

# Adicionar novos sinais ao watchlist
if add_btn:
    if not up:
        st.sidebar.error("Envie um arquivo JSON antes.")
    else:
        try:
            data = json.loads(up.read().decode("utf-8"))
            if not isinstance(data, list):
                st.sidebar.error("JSON deve ser uma lista de sinais.")
            else:
                # validação mínima e merge
                required = {"symbol","side","entry","target","stop_loss","entrada_datahora","saida_datahora"}
                added = 0
                for s in data:
                    if not required.issubset(s.keys()):
                        continue
                    s["symbol"] = s["symbol"].upper()
                    # dedupe simples: symbol + entrada + saída
                    key = (s["symbol"], s["entrada_datahora"], s["saida_datahora"])
                    if not any((w.get("symbol"), w.get("entrada_datahora"), w.get("saida_datahora")) == key for w in watch):
                        watch.append(s); added += 1
                save_json(WATCH_PATH, watch)
                st.sidebar.success(f"{added} sinal(is) adicionados ao Watchlist.")
        except Exception as e:
            st.sidebar.error(f"Erro no JSON: {e}")

# =========================
# Live Tracking — simples
# =========================
st.subheader("Watchlist (ao vivo, 1m)")
if not watch:
    st.info("Watchlist vazio. Adicione sinais pelo JSON na barra lateral.")
else:
    now_ms = int(datetime.now(timezone.utc).timestamp()*1000)
    rows = []
    closed_to_archive = []

    if refresh_now:
        st.toast("Atualizando…", icon="⏳")

    for s in watch:
        try:
            symbol = s["symbol"].upper()
            side   = s["side"].upper()
            entry  = float(s["entry"])
            target = float(s["target"])
            stop   = float(s["stop_loss"])
            start_ms = to_ms(s["entrada_datahora"])
            end_ms   = to_ms(s["saida_datahora"])

            end_eval = min(now_ms, end_ms)
            res = eval_interval(symbol, side, entry, target, stop, start_ms, end_eval)

            status = res["status"]
            preco  = res["preco_ref"]
            lucro  = res["lucro_pct"]

            # Se passou da saída e não bateu alvo/stop, fecha por tempo usando close do fim do período
            if now_ms >= end_ms and status == "EM ABERTO":
                res_final = eval_interval(symbol, side, entry, target, stop, start_ms, end_ms)
                status = "FECHADO POR TEMPO"
                preco  = res_final["preco_ref"]
                lucro  = res_final["lucro_pct"]

                # manda pro histórico e marca para remover do watchlist
                closed_to_archive.append({
                    **s,
                    "preco_saida": preco,
                    "lucro_pct": lucro,
                    "bateu_alvo": res_final["bateu_alvo"],
                    "bateu_stop": res_final["bateu_stop"],
                    "status_final": status,
                    "fechado_em": ms_to_iso(end_ms),
                })

            rows.append({
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "target": target,
                "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"],
                "saida_datahora": s["saida_datahora"],
                "status": status,
                "preco_ref": preco,
                "lucro_pct": lucro,
                "ultima_atualizacao": ms_to_iso(now_ms)
            })

        except Exception as e:
            rows.append({
                "symbol": s.get("symbol"),
                "side": s.get("side"),
                "entry": s.get("entry"),
                "target": s.get("target"),
                "stop_loss": s.get("stop_loss"),
                "entrada_datahora": s.get("entrada_datahora"),
                "saida_datahora": s.get("saida_datahora"),
                "status": f"ERRO: {e}",
                "preco_ref": None,
                "lucro_pct": None,
                "ultima_atualizacao": ms_to_iso(now_ms)
            })

    df = pd.DataFrame(rows)

    # Mostrar/ocultar fechados por tempo
    if not show_closed:
        df = df[df["status"] != "FECHADO POR TEMPO"]

    # Ordenar: primeiro em aberto, depois alvo/stop, depois fechados
    order_map = {"EM ABERTO": 0, "✓ ALVO": 1, "✕ STOP": 1, "FECHADO POR TEMPO": 2}
    df["__ord"] = df["status"].map(lambda x: order_map.get(x, 99))
    df = df.sort_values(["__ord","symbol"]).drop(columns="__ord")

    st.dataframe(
        df[
            ["symbol","side","status","preco_ref","lucro_pct",
             "entry","target","stop_loss","entrada_datahora","saida_datahora","ultima_atualizacao"]
        ],
        use_container_width=True
    )

    # Arquivar fechados por tempo (remove do watchlist)
    if closed_to_archive:
        hist.extend(closed_to_archive)
        save_json(HIST_PATH, hist)
        # remove do watchlist
        keys_to_remove = {(x["symbol"], x["entrada_datahora"], x["saida_datahora"]) for x in closed_to_archive}
        watch = [w for w in watch if (w["symbol"], w["entrada_datahora"], w["saida_datahora"]) not in keys_to_remove]
        save_json(WATCH_PATH, watch)
        st.success(f"{len(closed_to_archive)} trade(s) fechados por tempo e enviados ao histórico.")

# =========================
# Histórico (somente leitura)
# =========================
st.subheader("Histórico")
if not hist:
    st.caption("Vazio por enquanto.")
else:
    dfh = pd.DataFrame(hist)
    # colunas padrão se existirem
    cols = [c for c in [
        "symbol","side","status_final","preco_saida","lucro_pct",
        "entrada_datahora","saida_datahora","fechado_em"
    ] if c in dfh.columns]
    st.dataframe(dfh[cols].sort_values("fechado_em", ascending=False), use_container_width=True)

    st.download_button(
        "Baixar Histórico (CSV)",
        data=dfh.to_csv(index=False).encode("utf-8"),
        file_name="historico.csv",
        mime="text/csv"
    )
