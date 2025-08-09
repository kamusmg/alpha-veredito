# prompt_builder.py
import os, json, datetime
from typing import List, Dict, Any

APP_DIR = os.path.dirname(__file__)
AUDIT_DIR = os.path.join(APP_DIR, "audits")
AUDITS = os.path.join(AUDIT_DIR, "audits.jsonl")
FAILS  = os.path.join(AUDIT_DIR, "failures.jsonl")

SCHEMA_SNIPPET = """Campos obrigatórios por sinal:
{
  "symbol": "TICKERUSDT",
  "side": "BUY|SELL",
  "entry": number,
  "target": number,
  "stop_loss": number,
  "entrada_datahora": "YYYY-MM-DD HH:MM:SS",
  "saida_datahora":   "YYYY-MM-DD HH:MM:SS"
}
Regras:
- BUY: target > entry e stop_loss < entry
- SELL: target < entry e stop_loss > entry
- Datas válidas (UTC) no formato acima
- Símbolo deve existir na Binance (exchangeInfo=status TRADING)
Erros padronizados: E_NUM, E_SIDE, E_DATE, E_SYMBOL, E_PRICE_MISS, E_RULE_BUY, E_RULE_SELL, E_NET
"""

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def _hint_for_code(code: str) -> str:
    return {
        "E_NUM": "Converta strings numéricas com ponto (.) e remova %, vírgulas e símbolos.",
        "E_SIDE": "Normalize para BUY/SELL (converter COMPRA→BUY, VENDA→SELL).",
        "E_DATE": "Produza datas no formato YYYY-MM-DD HH:MM:SS (UTC).",
        "E_SYMBOL": "Use o par negociado na Binance (ex.: BTCUSDT).",
        "E_PRICE_MISS": "Não invente preço. Retorne apenas os campos do sinal.",
        "E_RULE_BUY": "Para BUY: target > entry e stop_loss < entry.",
        "E_RULE_SELL": "Para SELL: target < entry e stop_loss > entry.",
        "E_NET": "Tente novamente; evite ruído/artefatos no OCR.",
    }.get(code, "Siga o schema e corrija campos inconsistentes.")

def build_training_packet(max_fail_examples: int = 12, days_window: int = 7) -> Dict[str, Any]:
    audits = _read_jsonl(AUDITS)
    fails  = _read_jsonl(FAILS)

    cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(days=days_window)
    cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

    def _recent(rec: Dict[str, Any]) -> bool:
        ts = rec.get("ts") or ""
        return ts >= cutoff

    audits_recent = [a for a in audits if _recent(a)]
    fails_recent  = [f for f in fails if _recent(f)]

    total = len(audits_recent)
    invalids = sum(1 for a in audits_recent if a.get("validation", {}).get("errors"))
    price_cov = sum(1 for a in audits_recent if a.get("market", {}).get("live_price") is not None)
    finals = [a for a in audits_recent if a.get("verdict", {}).get("state") == "FINAL"]
    acc = sum(1 for a in finals if (a.get("verdict", {}).get("result") == "ACERTOU")) if finals else 0

    metrics = {
        "window_days": days_window,
        "total_samples": total,
        "invalid_rate": round(invalids / total, 4) if total else 0.0,
        "price_coverage": round(price_cov / total, 4) if total else 0.0,
        "final_count": len(finals),
        "final_accuracy": round(acc / len(finals), 4) if finals else None,
    }

    err_counts: Dict[str, int] = {}
    for a in audits_recent:
        for e in a.get("validation", {}).get("errors", []):
            err_counts[e] = err_counts.get(e, 0) + 1
    top_errors = sorted(err_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for f in fails_recent:
        codes = f.get("validation", {}).get("errors", [])
        if not codes:
            codes = ["E_UNKNOWN"]
        for c in codes:
            by_code.setdefault(c, []).append(f)

    examples: List[Dict[str, Any]] = []
    for code, arr in by_code.items():
        for ex in arr[:3]:
            sig = ex.get("signal", {}) or {}
            examples.append({
                "error_code": code,
                "signal": {k: sig.get(k) for k in ["symbol", "side", "entry", "target", "stop_loss", "entrada_datahora", "saida_datahora"]},
                "auditor_feedback": ex.get("validation", {}).get("errors", []),
                "hint": _hint_for_code(code)
            })
    examples = examples[:max_fail_examples]

    return {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_version": "live-1.3",
        "schema_rules": SCHEMA_SNIPPET.strip(),
        "metrics": metrics,
        "top_errors": [{"code": c, "count": n} for c, n in top_errors],
        "examples": examples
    }

def build_prompt_markdown(packet: Dict[str, Any]) -> str:
    metrics = packet.get("metrics", {})
    top_errs_list = packet.get("top_errors", []) or []
    top_errs = "\n".join([f"- {e['code']}: {e['count']}" for e in top_errs_list]) or "- (sem dados)"

    ex_lines = []
    for i, ex in enumerate(packet.get("examples", []), 1):
        errs = ", ".join(ex.get("auditor_feedback", [])) or "—"
        sig = ex.get("signal", {}) or {}
        sig_json = json.dumps(sig, ensure_ascii=False, indent=2)

        bloco = ""
        bloco += f"### Exemplo {i} — {ex.get('error_code','')}\n"
        bloco += "Sinal:\n```json\n"
        bloco += sig_json + "\n```\n"
        bloco += f"Erros do auditor: {errs}\n"
        bloco += f"Dica: {ex.get('hint','—')}\n\n"
        bloco += "Saída esperada:\n"
        bloco += "- Gerar JSON exatamente no schema abaixo, com valores coerentes às regras (BUY/SELL) e datas válidas.\n"
        bloco += "- Não incluir campos extras nem preço ao vivo.\n"

        ex_lines.append(bloco)

    examples_md = "\n".join(ex_lines) if ex_lines else "_Sem exemplos recentes_"

    prompt = ""
    prompt += "# Lucra — Correção de Extração (Studio AI)\n\n"
    prompt += "## Contexto\n"
    prompt += "Você irá **extrair sinais de trade** de prints/JSON e devolvê-los neste **schema imutável**. O auditor do Lucra valida todos os campos e rotula erros.\n\n"

    prompt += "## Schema e Regras\n```\n"
    prompt += packet.get("schema_rules","") + "\n```\n\n"

    prompt += f"## Métricas recentes (janela {metrics.get('window_days','?')}d)\n"
    prompt += f"- Amostras: {metrics.get('total_samples',0)}\n"
    prompt += f"- Inválidos: {metrics.get('invalid_rate',0)*100:.1f}%\n"
    prompt += f"- Cobertura de preço (informativo): {metrics.get('price_coverage',0)*100:.1f}%\n"
    prompt += f"- Finalizados: {metrics.get('final_count',0)}\n"
    prompt += f"- Acurácia final (proxy): {metrics.get('final_accuracy','—')}\n\n"

    prompt += "## Top erros\n"
    prompt += top_errs + "\n\n"

    prompt += "## Tarefa\n"
    prompt += "1. **Produza o JSON do sinal** exatamente no schema.\n"
    prompt += "2. **Normalize** side (BUY/SELL), numéricos (ponto decimal) e datas (YYYY-MM-DD HH:MM:SS UTC).\n"
    prompt += "3. **Valide regras** (BUY/SELL) antes de responder.\n"
    prompt += "4. **Não inclua** campos extras nem preço ao vivo.\n"
    prompt += "5. **Se o input estiver ambíguo**, responda com um objeto contendo `__issue` e uma explicação curta.\n\n"

    prompt += "## Exemplos de falha e como corrigir\n"
    prompt += examples_md

    return prompt
