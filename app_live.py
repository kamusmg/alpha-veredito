# app_live.py
import os
import io
import time
import json
import math
import base64
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from time import perf_counter
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Set, List
from zoneinfo import ZoneInfo  # <<< FUSO

# Export de prompt/dataset
from prompt_builder import build_training_packet, build_prompt_markdown

# Auditor
from audits_utils import (
    audit_log, build_audit_record,
    E_NUM, E_SIDE, E_DATE, E_SYMBOL, E_PRICE_MISS, E_RULE_BUY, E_RULE_SELL, E_NET, E_UNKNOWN
)

# =========================
# Config
# =========================
BINANCE_BASE = "https://api.binance.com"   # Spot
INTERVAL = "1m"
USER_AGENT = "LucraLive/1.3 (+https://lucra.local)"
APP_DIR = os.path.dirname(__file__)
WATCH_PATH = os.path.join(APP_DIR, "watchlist.json")
HIST_PATH  = os.path.join(APP_DIR, "historico.json")
LOG_DIR    = os.path.join(APP_DIR, "logs")
LOG_PATH   = os.path.join(LOG_DIR, "lucra.log")

# Pasta para exportações (prompt/packet)
EXPORT_DIR = os.path.join(APP_DIR, "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

# Versões (para auditoria)
APP_VERSION    = "live-1.3"
MODEL_VERSION  = "n/a"
PROMPT_ID      = "extract_v1"

# FUSO local das strings de data do JSON
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

st.set_page_config(page_title="Lucra — Veredito AO VIVO", layout="wide")

# =========================
# Estilo
# =========================
st.markdown("""
<style>
:root { --ok:#22c55e; --bad:#ef4444; --warn:#f59e0b; --muted:#94a3b8; }
[data-testid="stHeader"] { background: transparent; }
.badge{display:inline-flex;align-items:center;gap:.5rem;padding:.35rem .6rem;border-radius:999px;font-weight:700;letter-spacing:.3px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.06)}
.blink{animation:blink 1.4s linear infinite}@keyframes blink{50%{opacity:.45}}
.card{background:rgba(17,24,39,.55);border:1px solid rgba(148,163,184,.18);border-radius:16px;padding:18px}
.kpi{text-align:center;border-radius:16px;padding:18px;border:1px solid rgba(148,163,184,.18);background:linear-gradient(180deg,rgba(15,23,42,.7),rgba(2,6,23,.6))}
.kpi h3{font-size:14px;color:#94a3b8;margin:0 0 6px 0;font-weight:600}.kpi .val{font-size:30px;font-weight:900}
.pill{padding:.2rem .5rem;border-radius:.6rem;font-weight:700;border:1px solid rgba(255,255,255,.1)}
.pill-live-pos{color:var(--ok);background:rgba(34,197,94,.12);border-color:rgba(34,197,94,.25)}
.pill-live-neg{color:var(--bad);background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.25)}
.pill-live-neu{color:var(--warn);background:rgba(245,158,11,.12);border-color:rgba(245,158,11,.25)}
.pill-invalid{color:#eab308;background:rgba(234,179,8,.12);border-color:rgba(234,179,8,.25)}
.spark{display:flex;align-items:center;gap:.4rem}.spark img{border-radius:6px;border:1px solid rgba(148,163,184,.18)}
</style>
""", unsafe_allow_html=True)

# =========================
# Utils comuns
# =========================
def log_event(tipo: str, payload: dict):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        rec = {"ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "tipo": tipo, **payload}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def to_ms(dt_str: str) -> int:
    """
    As strings do JSON estão em America/Sao_Paulo.
    Converte BR -> UTC em ms.
    """
    dt_local = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    dt_utc = dt_local.astimezone(timezone.utc)
    return int(dt_utc.timestamp() * 1000)

def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def load_json(path, default):
    if not os.path.isfile(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_bytes(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

def req_with_backoff(method: str, url: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers["User-Agent"] = USER_AGENT
    timeout = kwargs.pop("timeout", 15)
    backoff = [0, 0.5, 1.5]
    last_exc = None
    for i, wait in enumerate(backoff, 1):
        try:
            r = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            if i < len(backoff):
                time.sleep(wait)
    raise last_exc

def map_validation_errors(struct_ok: bool, struct_msg: str, symbol_ok: bool, price_available: bool) -> list[str]:
    errs = []
    msg_low = (struct_msg or "").lower()
    if not struct_ok:
        if "num" in msg_low: errs.append(E_NUM)
        if "side" in msg_low: errs.append(E_SIDE)
        if "data" in msg_low: errs.append(E_DATE)
        if "buy inválido" in msg_low or "buy invalido" in msg_low: errs.append(E_RULE_BUY)
        if "sell inválido" in msg_low or "sell invalido" in msg_low: errs.append(E_RULE_SELL)
        if not errs: errs.append(E_UNKNOWN)
    if not symbol_ok: errs.append(E_SYMBOL)
    if not price_available: errs.append(E_PRICE_MISS)
    seen = set(); out = []
    for e in errs:
        if e not in seen: out.append(e); seen.add(e)
    return out

# =========================
# Cache e dados de mercado
# =========================
@st.cache_data(ttl=3600)
def get_exchange_info() -> Set[str]:
    url = f"{BINANCE_BASE}/api/v3/exchangeInfo"
    r = req_with_backoff("GET", url)
    data = r.json()
    syms = {s["symbol"].upper() for s in data.get("symbols", []) if s.get("status") == "TRADING"}
    return syms

@st.cache_data(ttl=5)
def get_all_prices() -> Dict[str, float]:
    url = f"{BINANCE_BASE}/api/v3/ticker/price"
    r = req_with_backoff("GET", url)
    arr = r.json()
    out = {}
    for it in arr:
        try:
            out[it["symbol"].upper()] = float(it["price"])
        except Exception:
            continue
    return out

@st.cache_data(ttl=5)
def get_price_single(symbol: str) -> Optional[float]:
    url = f"{BINANCE_BASE}/api/v3/ticker/price"
    r = req_with_backoff("GET", url, params={"symbol": symbol.upper()})
    try:
        return float(r.json()["price"])
    except Exception:
        return None

def resolve_live_price(symbol: str, prices_map: Dict[str, float]) -> Optional[float]:
    sym = symbol.upper()
    if sym in prices_map:
        return prices_map[sym]
    return get_price_single(sym)

# =========================
# Kliness e sparklines
# =========================
@st.cache_data(ttl=30)
def fetch_klines(symbol: str, start_ms: int, end_ms: int, interval: str = INTERVAL) -> pd.DataFrame:
    rows, limit, cur = [], 1000, start_ms
    while cur <= end_ms:
        url = f"{BINANCE_BASE}/api/v3/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": cur,
            "endTime": min(end_ms, cur + (limit-1)*60_000),
            "limit": limit,
        }
        r = req_with_backoff("GET", url, params=params)
        data = r.json()
        if not data: break
        rows.extend(data)
        cur = data[-1][6] + 1
        if len(data) < limit: break
        time.sleep(0.02)
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

@st.cache_data(ttl=60)
def fetch_recent_closes(symbol: str, minutes: int = 60) -> List[float]:
    end_ms = int(datetime.now(timezone.utc).timestamp()*1000)
    start_ms = end_ms - minutes*60_000
    df = fetch_klines(symbol, start_ms, end_ms, "1m")
    if df.empty:
        return []
    return df["close"].astype(float).tolist()

def sparkline_img(closes: List[float], width=140, height=28) -> str:
    if not closes:
        return ""
    fig = plt.figure(figsize=(width/100, height/100), dpi=100)
    ax = fig.add_axes([0,0,1,1])
    ax.plot(closes, linewidth=1.5)
    ax.axis('off')
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" width="{width}" height="{height}"/>'

# =========================
# Validações, eventos, PnL
# =========================
def validate_signal_numeric_side(s: dict) -> Tuple[bool, str]:
    try:
        side   = (s["side"] or "").upper()
        entry  = float(s["entry"])
        target = float(s["target"])
        stop   = float(s["stop_loss"])
    except Exception:
        return False, "Campos numéricos inválidos"

    if side == "BUY":
        if not (target > entry and stop < entry):
            return False, "BUY inválido (target > entry e stop < entry)"
    elif side == "SELL":
        if not (target < entry and stop > entry):
            return False, "SELL inválido (target < entry e stop > entry)"
    else:
        return False, "Side inválido"
    try:
        to_ms(s["entrada_datahora"])
        to_ms(s["saida_datahora"])
    except Exception:
        return False, "Datas inválidas (YYYY-MM-DD HH:MM:SS)"
    return True, ""

def is_signal_valid(sig: dict, exchange_symbols: Set[str]) -> Tuple[bool, Optional[str]]:
    ok, msg = validate_signal_numeric_side(sig)
    if not ok: return False, msg
    symbol = (sig.get("symbol") or "").upper()
    if symbol not in exchange_symbols:
        return False, "Símbolo inexistente na Binance"
    return True, None

def hit_events(symbol, side, entry, target, stop, start_ms, end_ms):
    df = fetch_klines(symbol, start_ms, end_ms)
    if df.empty:
        return False, False, None, None
    bateu_alvo = bateu_stop = False
    preco_exec = None
    for _, r in df.iterrows():
        h, l = float(r["high"]), float(r["low"])
        if side == "BUY":
            if l <= stop:
                bateu_stop = True; preco_exec = stop; break
            if h >= target:
                bateu_alvo = True; preco_exec = target; break
        else:  # SELL
            if h >= stop:
                bateu_stop = True; preco_exec = stop; break
            if l <= target:
                bateu_alvo = True; preco_exec = target; break
    last_close = float(df.iloc[-1]["close"])
    return bateu_alvo, bateu_stop, preco_exec, last_close

def compute_live_pnl(side: str, entry: float, last_price: Optional[float]) -> Optional[float]:
    if entry is None or last_price is None:
        return None
    if side == "BUY":
        return ((last_price - entry) / entry) * 100
    else:
        return ((entry - last_price) / entry) * 100

def timed_hit_events(*args, **kwargs):
    t0 = perf_counter()
    res = hit_events(*args, **kwargs)
    lat = int((perf_counter() - t0) * 1000)
    return res, lat

# ===== Detectar "bateu a entry" (candle toca a entry) =====
def hit_entry(symbol: str, side: str, entry: float, start_ms: int, end_ms: int) -> tuple[bool, Optional[int], Optional[float], Optional[float]]:
    df = fetch_klines(symbol, start_ms, end_ms)
    if df.empty:
        return False, None, None, None
    entry_hit = False
    hit_ms = None
    for _, r in df.iterrows():
        h, l = float(r["high"]), float(r["low"])
        if l <= entry <= h:
            entry_hit = True
            hit_ms = int(r["close_time"])  # aproximação
            break
    last_close = float(df.iloc[-1]["close"])
    return entry_hit, hit_ms, entry, last_close

# =========================
# Sidebar
# =========================
with st.sidebar:
    st.markdown('<div class="badge blink">🔴 AO VIVO</div>', unsafe_allow_html=True)
    st.subheader("Sinais")
    up = st.file_uploader("JSON dos sinais", type=["json"])
    col_sb1, col_sb2 = st.columns(2)
    add_btn = col_sb1.button("➕ Adicionar")
    clear_btn = col_sb2.button("🗑️ Limpar Watchlist")
    st.divider()
    st.subheader("Atualização")
    auto = st.toggle("Auto-refresh", value=True)
    interval = st.slider("Intervalo (seg)", 5, 60, 15, step=5)
    st.subheader("Sparklines")
    enable_spark = st.toggle("Ativar sparklines (mais requests)", value=True)
    spark_minutes = st.slider("Janela (min)", 15, 180, 60, step=15, help="Janela de preço usada nos mini-gráficos.")
    st.caption("Use Auto-refresh para acompanhar em tempo real.")

# =========================
# Estado
# =========================
if "invalid_hits" not in st.session_state:
    st.session_state.invalid_hits = {}
invalid_hits: Dict[str, int] = st.session_state.invalid_hits

watch = load_json(WATCH_PATH, [])
hist  = load_json(HIST_PATH,  [])

if clear_btn:
    watch = []
    save_json(WATCH_PATH, watch)
    st.sidebar.success("Watchlist limpo.")

if add_btn:
    if not up:
        st.sidebar.error("Envie um JSON primeiro.")
    else:
        try:
            data = json.loads(up.read().decode("utf-8"))
            if not isinstance(data, list):
                st.sidebar.error("O JSON deve ser uma lista.")
            else:
                required = {"symbol","side","entry","target","stop_loss","entrada_datahora","saida_datahora"}
                added, invalid = 0, 0
                for s in data:
                    if not required.issubset(s.keys()):
                        invalid += 1
                        continue
                    s["symbol"] = s["symbol"].upper()
                    key = (s["symbol"], s["entrada_datahora"], s["saida_datahora"])
                    if not any((w.get("symbol"), w.get("entrada_datahora"), w.get("saida_datahora")) == key for w in watch):
                        watch.append(s); added += 1
                save_json(WATCH_PATH, watch)
                st.sidebar.success(f"{added} sinal(is) adicionado(s).")
                if invalid:
                    st.sidebar.warning(f"{invalid} sinal(is) ignorado(s) por faltar campos.")
        except Exception as e:
            st.sidebar.error(f"JSON inválido: {e}")

# =========================
# Header
# =========================
now_ms = int(datetime.now(timezone.utc).timestamp()*1000)
st.markdown(f"""
<div class="card" style="display:flex; align-items:center; justify-content:space-between;">
  <div style="display:flex; align-items:center; gap:12px;">
    <div class="badge blink">🔴 AO VIVO</div>
    <div class="badge">Binance 1m</div>
    <div class="badge">Veredito do Lucra</div>
  </div>
  <div style="color:#94a3b8; font-weight:600;">Atualizado: {ms_to_iso(now_ms)}</div>
</div>
""", unsafe_allow_html=True)
st.markdown("&nbsp;")

# =========================
# Função: remoção permanente de inválidos
# =========================
def prune_watchlist(watch_list: List[dict], historico_path: str, threshold: int = 2) -> List[dict]:
    to_remove_keys = [k for k, c in invalid_hits.items() if c >= threshold]
    if not to_remove_keys:
        return watch_list
    hist_local = load_json(historico_path, [])
    new_watch = []
    for s in watch_list:
        key = f"{s.get('symbol')}|{s.get('entrada_datahora')}|{s.get('saida_datahora')}"
        if key in to_remove_keys:
            motivo = "Sem preço ao vivo/erro de validação após múltiplas tentativas"
            hist_local.append({**s, "status_final": "INVALIDO_REMOVIDO", "motivo": motivo, "fechado_em": ms_to_iso(now_ms)})
            log_event("remocao_invalido", {"key": key, "motivo": motivo})
        else:
            new_watch.append(s)
    save_json(historico_path, hist_local)
    save_json(WATCH_PATH, new_watch)
    for k in to_remove_keys:
        invalid_hits.pop(k, None)
    return new_watch

# =========================
# Live loop
# =========================
if not watch:
    st.info("Watchlist vazio. Adicione seus sinais na lateral (JSON).")
else:
    rows = []
    finalized_records = []

    # 1) cache de símbolos válidos & preços batelados
    try:
        exchange_syms = get_exchange_info()
    except Exception as e:
        exchange_syms = set()
        st.warning("Falha ao buscar exchangeInfo. Validação de símbolo desativada neste ciclo.")
        log_event("erro_exchange_info", {"erro": str(e)})

    prices_map = {}
    lat_batch_ms = None
    try:
        t0 = perf_counter()
        prices_map = get_all_prices()
        lat_batch_ms = int((perf_counter() - t0) * 1000)
    except Exception as e:
        prices_map = {}
        st.warning("Falha ao buscar preços em batch. Tentando fallback por-símbolo se necessário.")
        log_event("erro_batch_prices", {"erro": str(e)})

    for s in watch:
        symbol = (s.get("symbol") or "").upper()
        side   = (s.get("side") or "").upper()
        key    = f"{symbol}|{s.get('entrada_datahora')}|{s.get('saida_datahora')}"

        # Validação estrutural
        ok_struct, msg = validate_signal_numeric_side(s)
        if not ok_struct:
            rows.append({
                "symbol": symbol, "side": side, "status": "CONFIG INVÁLIDA",
                "live_pnl_pct": None, "live_price": None,
                "entry": s.get("entry"), "target": s.get("target"), "stop_loss": s.get("stop_loss"),
                "entrada_datahora": s.get("entrada_datahora"), "saida_datahora": s.get("saida_datahora"),
                "detalhe": msg, "spark": ""
            })
            invalid_hits[key] = invalid_hits.get(key, 0) + 1

            symbol_ok = (symbol in exchange_syms) if exchange_syms else True
            val_errors = map_validation_errors(False, msg or "invalid", symbol_ok, price_available=False)
            audit_rec = build_audit_record(
                APP_DIR, s,
                model_version=MODEL_VERSION, prompt_id=PROMPT_ID,
                source={"type":"json","origin_id":"watchlist"},
                validation_errors=val_errors,
                symbol_exists=symbol_ok,
                numeric_ok=(E_NUM not in val_errors),
                date_ok=(E_DATE not in val_errors),
                rule_ok=(E_RULE_BUY not in val_errors and E_RULE_SELL not in val_errors),
                price_source=None, live_price=None, pnl_pct_live=None,
                verdict_state="LIVE", verdict_result=None,
                price_exit=None, pnl_pct_final=None,
                latency_ms={"batch_prices": lat_batch_ms}
            )
            audit_log(APP_DIR, audit_rec)
            audit_log(APP_DIR, audit_rec, failure_only=True)
            continue

        entry  = float(s["entry"]); target = float(s["target"]); stop = float(s["stop_loss"])
        start_ms = to_ms(s["entrada_datahora"]); end_ms = to_ms(s["saida_datahora"])

        # Validação de símbolo
        if exchange_syms and symbol not in exchange_syms:
            rows.append({
                "symbol": symbol, "side": side, "status": "CONFIG INVÁLIDA",
                "live_pnl_pct": None, "live_price": None,
                "entry": entry, "target": target, "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
                "detalhe": "Símbolo inexistente na Binance", "spark": ""
            })
            invalid_hits[key] = invalid_hits.get(key, 0) + 1

            val_errors = [E_SYMBOL]
            audit_rec = build_audit_record(
                APP_DIR, s,
                model_version=MODEL_VERSION, prompt_id=PROMPT_ID,
                source={"type":"json","origin_id":"watchlist"},
                validation_errors=val_errors,
                symbol_exists=False, numeric_ok=True, date_ok=True, rule_ok=True,
                price_source=None, live_price=None, pnl_pct_live=None,
                verdict_state="LIVE", verdict_result=None,
                price_exit=None, pnl_pct_final=None,
                latency_ms={"batch_prices": lat_batch_ms}
            )
            audit_log(APP_DIR, audit_rec)
            audit_log(APP_DIR, audit_rec, failure_only=True)
            continue

        # Preço ao vivo
        live_price = resolve_live_price(symbol, prices_map)

        # ===== Estado + gatilho entry =====
        end_eval = min(now_ms, end_ms)

        # Antes da janela -> AGENDADO
        if now_ms < start_ms:
            rows.append({
                "symbol": symbol, "side": side, "status": "⏳ AGENDADO",
                "live_pnl_pct": None, "live_price": live_price,
                "entry": entry, "target": target, "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
                "alvo_bateu_ate_agora": False, "stop_bateu_ate_agora": False,
                "spark": ""
            })
            continue

        # Checa se bateu a ENTRY até agora
        entry_ok, entry_hit_ms, entry_fill_px, last_close_entry = hit_entry(symbol, side, entry, start_ms, end_eval)

        # Não bateu a entry e ainda não terminou -> ARMADO
        if (not entry_ok) and (now_ms < end_ms):
            if key in invalid_hits: invalid_hits[key] = 0
            if enable_spark:
                try:
                    closes = fetch_recent_closes(symbol, minutes=spark_minutes)
                    spark_html = f'<div class="spark">{sparkline_img(closes)}</div>' if closes else ""
                except Exception as e:
                    spark_html = ""
                    log_event("erro_spark", {"symbol": symbol, "erro": str(e)})
            else:
                spark_html = ""
            rows.append({
                "symbol": symbol, "side": side, "status": "🟠 ARMADO",
                "live_pnl_pct": None,
                "live_price": live_price if live_price is not None else last_close_entry,
                "entry": entry, "target": target, "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
                "alvo_bateu_ate_agora": False, "stop_bateu_ate_agora": False,
                "spark": spark_html
            })
            continue

        # Entrou e janela ainda ativa -> AO_VIVO (targets/stops a partir da entrada)
        if entry_ok and now_ms < end_ms:
            (res_live, lat_k_ms_live) = timed_hit_events(symbol, side, entry, target, stop, entry_hit_ms, end_eval)
            bateu_alvo, bateu_stop, _, last_close_calc = res_live
            last_ref_price = live_price if live_price is not None else last_close_calc
            pnl = compute_live_pnl(side, entry, last_ref_price)
            if enable_spark:
                try:
                    closes = fetch_recent_closes(symbol, minutes=spark_minutes)
                    spark_html = f'<div class="spark">{sparkline_img(closes)}</div>' if closes else ""
                except Exception as e:
                    spark_html = ""
                    log_event("erro_spark", {"symbol": symbol, "erro": str(e)})
            else:
                spark_html = ""
            rows.append({
                "symbol": symbol, "side": side, "status": "🟡 AO VIVO",
                "live_pnl_pct": None if pnl is None or (isinstance(pnl, float) and math.isnan(pnl)) else round(pnl, 2),
                "live_price": last_ref_price,
                "entry": entry, "target": target, "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
                "alvo_bateu_ate_agora": bateu_alvo, "stop_bateu_ate_agora": bateu_stop,
                "spark": spark_html
            })

            price_source = "batch" if (symbol in prices_map) else ("fallback" if live_price is not None else ("kline_proxy" if last_close_calc is not None else None))
            pnl_val = None if pnl is None or (isinstance(pnl, float) and math.isnan(pnl)) else float(pnl)
            audit_rec = build_audit_record(
                APP_DIR, s,
                model_version=MODEL_VERSION, prompt_id=PROMPT_ID,
                source={"type":"json","origin_id":"watchlist"},
                validation_errors=[],
                symbol_exists=(symbol in exchange_syms) if exchange_syms else None,
                numeric_ok=True, date_ok=True, rule_ok=True,
                price_source=price_source, live_price=last_ref_price, pnl_pct_live=pnl_val,
                verdict_state="LIVE", verdict_result=None,
                price_exit=None, pnl_pct_final=None,
                latency_ms={"batch_prices": lat_batch_ms, "klines": lat_k_ms_live}
            )
            audit_log(APP_DIR, audit_rec)
            continue

        # Janela encerrou -> FINALIZADO
        if not entry_ok and now_ms >= end_ms:
            rows.append({
                "symbol": symbol, "side": side, "status": "⏹ TIMEOUT (SEM ENTRADA)",
                "live_pnl_pct": None, "live_price": None,
                "entry": entry, "target": target, "stop_loss": stop,
                "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
                "alvo_bateu_ate_agora": False, "stop_bateu_ate_agora": False,
                "spark": ""
            })
            finalized_records.append({
                **s,
                "status_final": "TIMEOUT_SEM_ENTRADA",
                "preco_saida": None,
                "lucro_pct": None,
                "bateu_alvo": False,
                "bateu_stop": False,
                "fechado_em": ms_to_iso(end_ms)
            })
            continue

        (res_end, lat_k2_ms) = timed_hit_events(symbol, side, entry, target, stop, entry_hit_ms or start_ms, end_ms)
        bateu_alvo, bateu_stop, preco_exec, last_close_end = res_end

        if bateu_alvo or bateu_stop:
            status_final = "✅ ACERTOU" if bateu_alvo else "❌ ERROU"
            preco_saida = preco_exec
            if side == "BUY":
                lucro = ((preco_saida - entry) / entry) * 100
            else:
                lucro = ((entry - preco_saida) / entry) * 100
        else:
            status_final = "⏹ TIMEOUT"
            preco_saida = last_close_end
            if side == "BUY":
                lucro = ((preco_saida - entry) / entry) * 100
            else:
                lucro = ((entry - preco_saida) / entry) * 100

        lucro = None if (lucro is None or (isinstance(lucro, float) and math.isnan(lucro))) else round(float(lucro), 2)

        rows.append({
            "symbol": symbol, "side": side, "status": status_final,
            "live_pnl_pct": None, "live_price": None,
            "entry": entry, "target": target, "stop_loss": stop,
            "entrada_datahora": s["entrada_datahora"], "saida_datahora": s["saida_datahora"],
            "alvo_bateu_ate_agora": bateu_alvo, "stop_bateu_ate_agora": bateu_stop,
            "preco_saida": preco_saida, "lucro_pct": lucro,
            "spark": ""
        })

        audit_rec = build_audit_record(
            APP_DIR, s,
            model_version=MODEL_VERSION, prompt_id=PROMPT_ID,
            source={"type":"json","origin_id":"watchlist"},
            validation_errors=[],
            symbol_exists=(symbol in exchange_syms) if exchange_syms else None,
            numeric_ok=True, date_ok=True, rule_ok=True,
            price_source="klines", live_price=None, pnl_pct_live=None,
            verdict_state="FINAL",
            verdict_result=("ACERTOU" if status_final.startswith("✅") else ("ERROU" if status_final.startswith("❌") else "TIMEOUT")),
            price_exit=preco_saida, pnl_pct_final=(None if lucro is None else float(lucro)),
            latency_ms={"batch_prices": lat_batch_ms, "klines": lat_k2_ms}
        )
        audit_log(APP_DIR, audit_rec)

        finalized_records.append({
            **s,
            "status_final": status_final,
            "preco_saida": preco_saida,
            "lucro_pct": lucro,
            "bateu_alvo": bateu_alvo,
            "bateu_stop": bateu_stop,
            "fechado_em": ms_to_iso(end_ms)
        })

    df = pd.DataFrame(rows)

    # KPIs
    ao_vivo = (df["status"] == "🟡 AO VIVO").sum() if "status" in df else 0
    ag_arm = df["status"].isin(["⏳ AGENDADO","🟠 ARMADO"]).sum() if "status" in df else 0
    acc = (df["status"] == "✅ ACERTOU").sum() if "status" in df else 0
    err = (df["status"] == "❌ ERROU").sum() if "status" in df else 0
    tout = df["status"].isin(["⏹ TIMEOUT","⏹ TIMEOUT (SEM ENTRADA)"]).sum() if "status" in df else 0
    inv = (df["status"] == "CONFIG INVÁLIDA").sum() if "status" in df else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f'<div class="kpi"><h3>AO VIVO</h3><div class="val" style="color:var(--warn)">{ao_vivo}</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="kpi"><h3>Acertos</h3><div class="val" style="color:var(--ok)">{acc}</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="kpi"><h3>Erros</h3><div class="val" style="color:var(--bad)">{err}</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="kpi"><h3>Timeout/Inválidos</h3><div class="val" style="color:#eab308">{tout + inv}</div></div>', unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # Ordenação
    if "status" in df.columns:
        live_mask = df["status"] == "🟡 AO VIVO"
        fin_mask  = df["status"].isin(["✅ ACERTOU","❌ ERROU","⏹ TIMEOUT","⏹ TIMEOUT (SEM ENTRADA)"])
        pend_mask = df["status"].isin(["⏳ AGENDADO","🟠 ARMADO"])
        inv_mask  = df["status"] == "CONFIG INVÁLIDA"

        live_part = df[live_mask].copy()
        if "live_pnl_pct" in live_part.columns:
            live_part = live_part.sort_values("live_pnl_pct", ascending=False, na_position="last")

        fin_part  = df[fin_mask].copy()
        pend_part = df[pend_mask].copy()
        inv_part  = df[inv_mask].copy()

        df = pd.concat([live_part, fin_part, pend_part, inv_part], ignore_index=True)

    # Badge AO VIVO
    def live_pill(row):
        if row["status"] != "🟡 AO VIVO":
            return ""
        v = row.get("live_pnl_pct")
        if v is None or not isinstance(v, (int, float)):
            return '<span class="pill pill-live-neu">AO VIVO</span>'
        cls = "pill-live-pos" if v >= 0 else "pill-live-neg"
        arrow = "↑" if v > 0 else ("↓" if v < 0 else "—")
        return f'<span class="pill {cls}">AO VIVO • {arrow} {v:.2f}%</span>'

    # Tabela HTML
    view = df.copy()
    if "live_pnl_pct" in view.columns:
        view["ao_vivo"] = view.apply(live_pill, axis=1)

    if "spark" in view.columns:
        view.insert(1, "sparkline", view.pop("spark"))

    show_cols = ["symbol","sparkline","side","status","ao_vivo","live_price","entry","target","stop_loss","entrada_datahora","saida_datahora","preco_saida","lucro_pct"]
    show_cols = [c for c in show_cols if c in view.columns]

    st.write(
        view[show_cols].to_html(escape=False, index=False),
        unsafe_allow_html=True
    )

    # Persistência do histórico + limpeza de finalizados
    if finalized_records:
        hist.extend(finalized_records)
        save_json(HIST_PATH, hist)
        keys_to_remove = {(x["symbol"], x["entrada_datahora"], x["saida_datahora"]) for x in finalized_records}
        watch = [w for w in watch if (w["symbol"], w["entrada_datahora"], w["saida_datahora"]) not in keys_to_remove]
        save_json(WATCH_PATH, watch)
        st.success(f"{len(finalized_records)} trade(s) finalizado(s) → enviados ao histórico.")

    # PRUNE inválidos reincidentes
    watch = prune_watchlist(watch, HIST_PATH, threshold=2)

# =========================
# Histórico (discreto)
# =========================
with st.expander("Histórico (finalizados)"):
    if not hist:
        st.caption("Ainda vazio.")
    else:
        dfh = pd.DataFrame(hist)
        for col in ["status_final", "preco_saida", "lucro_pct", "fechado_em"]:
            if col not in dfh.columns:
                dfh[col] = None
        if "fechado_em" in dfh.columns and dfh["fechado_em"].notna().any():
            dfh_sorted = dfh.sort_values("fechado_em", ascending=False, na_position="last")
        else:
            dfh_sorted = dfh
        cols = ["symbol","side","status_final","preco_saida","lucro_pct","entrada_datahora","saida_datahora","fechado_em","motivo"]
        cols = [c for c in cols if c in dfh_sorted.columns]
        st.dataframe(dfh_sorted[cols], use_container_width=True, hide_index=True)
        st.download_button(
            "Baixar CSV",
            data=dfh_sorted.to_csv(index=False).encode("utf-8"),
            file_name="historico.csv",
            mime="text/csv"
        )

# =========================
# Exportar pacote para Studio AI
# =========================
with st.expander("Exportar pacote para Studio AI", expanded=False):
    st.caption("Gera um prompt pronto + pacote JSON com métricas/exemplos a partir dos logs do auditor (audits/*.jsonl).")

    c1, c2 = st.columns(2)
    with c1:
        max_ex = st.slider("Exemplos máximos", 3, 30, 12, step=1)
    with c2:
        days   = st.slider("Janela (dias)", 1, 30, 7, step=1)

    gen = st.button("📤 Gerar pacote agora", type="primary", use_container_width=True)

    if gen:
        try:
            packet = build_training_packet(max_fail_examples=max_ex, days_window=days)
            prompt_md = build_prompt_markdown(packet)

            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            fname_md   = f"prompt_studio_ai-{ts}.md"
            fname_json = f"training_packet-{ts}.json"
            path_md    = os.path.join(EXPORT_DIR, fname_md)
            path_json  = os.path.join(EXPORT_DIR, fname_json)

            b_md   = prompt_md.encode("utf-8")
            b_json = json.dumps(packet, ensure_ascii=False, indent=2).encode("utf-8")

            save_bytes(path_md, b_md)
            save_bytes(path_json, b_json)

            st.success(f"Pacote gerado e salvo em: {EXPORT_DIR}")
            st.write("**Arquivos:**")
            st.code(f"{path_md}\n{path_json}", language="bash")

            st.markdown("**Preview do prompt (primeiras ~5000 chars):**")
            st.code(prompt_md[:5000], language="markdown")

            d1, d2 = st.columns(2)
            with d1:
                st.download_button("⬇️ Baixar prompt_studio_ai.md", data=b_md, file_name=fname_md, mime="text/markdown", use_container_width=True)
            with d2:
                st.download_button("⬇️ Baixar training_packet.json", data=b_json, file_name=fname_json, mime="application/json", use_container_width=True)

            m = packet.get("metrics", {})
            st.markdown(
                f"- Amostras: **{m.get('total_samples',0)}** · "
                f"Inválidos: **{(m.get('invalid_rate',0)*100):.1f}%** · "
                f"Cobertura de preço: **{(m.get('price_coverage',0)*100):.1f}%** · "
                f"Finalizados: **{m.get('final_count',0)}**"
            )

        except Exception as e:
            st.error(f"Falha ao gerar pacote: {e}")
            st.exception(e)

# =========================
# Auto-refresh
# =========================
if 'last_auto' not in st.session_state:
    st.session_state.last_auto = 0

if auto:
    time.sleep(interval)
    st.rerun()
