# audits_utils.py
import os, json
from datetime import datetime
from typing import Dict, Any, List, Optional

APP_VERSION = "live-1.3"   # atualize quando mexer em lógica relevante
AUDIT_DIRNAME = "audits"
AUDITS_FILENAME = "audits.jsonl"
FAILURES_FILENAME = "failures.jsonl"

# Códigos padronizados
E_NUM       = "E_NUM"        # campo numérico inválido
E_SIDE      = "E_SIDE"       # side inválido/fora de BUY|SELL
E_DATE      = "E_DATE"       # data inválida
E_SYMBOL    = "E_SYMBOL"     # símbolo não existe na Binance
E_PRICE_MISS= "E_PRICE_MISS" # faltou preço ao vivo depois de tentativas
E_RULE_BUY  = "E_RULE_BUY"   # regra de BUY violada
E_RULE_SELL = "E_RULE_SELL"  # regra de SELL violada
E_NET       = "E_NET"        # falha de rede/API
E_UNKNOWN   = "E_UNKNOWN"

def _ensure_paths(app_dir: str) -> Dict[str, str]:
    audits_dir = os.path.join(app_dir, AUDIT_DIRNAME)
    os.makedirs(audits_dir, exist_ok=True)
    return {
        "dir": audits_dir,
        "audits": os.path.join(audits_dir, AUDITS_FILENAME),
        "fails":  os.path.join(audits_dir, FAILURES_FILENAME),
    }

def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def audit_log(app_dir: str, record: Dict[str, Any], failure_only: bool=False) -> None:
    paths = _ensure_paths(app_dir)
    path  = paths["fails"] if failure_only else paths["audits"]
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # manter silencioso para não quebrar UI
        pass

def build_audit_record(
    app_dir: str,
    signal: Dict[str, Any],
    *,
    model_version: Optional[str] = None,
    prompt_id: Optional[str] = None,
    source: Optional[Dict[str, Any]] = None,
    validation_errors: Optional[List[str]] = None,
    symbol_exists: Optional[bool] = None,
    numeric_ok: Optional[bool] = None,
    date_ok: Optional[bool] = None,
    rule_ok: Optional[bool] = None,
    price_source: Optional[str] = None,
    live_price: Optional[float] = None,
    pnl_pct_live: Optional[float] = None,
    verdict_state: str = "LIVE",        # "LIVE" | "FINAL"
    verdict_result: Optional[str] = None,  # "ACERTOU"|"ERROU"|"NEUTRO"|None
    price_exit: Optional[float] = None,
    pnl_pct_final: Optional[float] = None,
    latency_ms: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    rec = {
        "ts": _utc_now(),
        "app_version": APP_VERSION,
        "model_version": model_version or "n/a",
        "prompt_id": prompt_id or "n/a",
        "source": source or {"type": "json", "origin_id": "watchlist"},
        "signal": {
            "symbol": signal.get("symbol"),
            "side": signal.get("side"),
            "entry": signal.get("entry"),
            "target": signal.get("target"),
            "stop_loss": signal.get("stop_loss"),
            "entrada_datahora": signal.get("entrada_datahora"),
            "saida_datahora": signal.get("saida_datahora"),
        },
        "validation": {
            "symbol_exists": symbol_exists,
            "numeric_ok": numeric_ok,
            "date_ok": date_ok,
            "rule_ok": rule_ok,
            "errors": validation_errors or [],
        },
        "market": {
            "price_source": price_source,
            "live_price": live_price,
            "pnl_pct_live": pnl_pct_live,
        },
        "verdict": {
            "state": verdict_state,
            "result": verdict_result,
            "price_exit": price_exit,
            "pnl_pct_final": pnl_pct_final,
        },
        "latency_ms": latency_ms or {},
    }
    return rec
