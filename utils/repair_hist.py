# utils/repair_hist.py
import os, json, re

# raiz do projeto: ...\Lucra Crypto - Versão de teste
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR  = os.path.dirname(UTILS_DIR)
SCRIPT_DIR = os.path.join(ROOT_DIR, "script")

# tente historico.json e historico (sem extensão)
CANDIDATES = [os.path.join(SCRIPT_DIR, "historico.json"),
              os.path.join(SCRIPT_DIR, "historico")]

def safe_float(x):
    try:
        if x is None: return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except:
        return None

def main():
    hist_path = None
    for p in CANDIDATES:
        if os.path.isfile(p):
            hist_path = p
            break

    if not hist_path:
        print("[repair] Arquivo historico não encontrado.")
        print("Procurado em:", CANDIDATES)
        return

    with open(hist_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # troca tokens NaN por null antes do json.loads
    raw = re.sub(r'\bNaN\b', 'null', raw)

    try:
        hist = json.loads(raw)
    except Exception as e:
        print("[repair] Falha ao parsear JSON:", e)
        print("Arquivo:", hist_path)
        return

    if not isinstance(hist, list):
        print("[repair] Formato inesperado; esperando lista.")
        return

    cleaned = []
    seen = set()
    for r in hist:
        if not isinstance(r, dict):
            continue

        # dedup (symbol, entrada_datahora, saida_datahora)
        key = (r.get("symbol"), r.get("entrada_datahora"), r.get("saida_datahora"))
        if key in seen:
            continue
        seen.add(key)

        r["preco_saida"] = safe_float(r.get("preco_saida"))
        r["lucro_pct"]   = safe_float(r.get("lucro_pct"))

        for k in ("bateu_alvo", "bateu_stop"):
            v = r.get(k)
            if isinstance(v, str):
                r[k] = v.lower() in ("true","1","yes","sim")

        cleaned.append(r)

    # salva como historico.json (padroniza)
    out_path = os.path.join(SCRIPT_DIR, "historico.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"[repair] OK! Itens: {len(cleaned)}")
    print(f"[repair] Arquivo salvo: {out_path}")

if __name__ == "__main__":
    main()
