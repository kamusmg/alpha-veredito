import csv
import os

def gerar_relatorio_html(csv_path, html_path):
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    html = """
    <html>
    <head>
        <meta charset="utf-8">
        <title>Relatório de Auditoria de Trades</title>
        <style>
            body { font-family: Arial, sans-serif; background: #101622; color: #e0e0e0; padding: 40px;}
            table { border-collapse: collapse; width: 100%; background: #181f30;}
            th, td { border: 1px solid #303a52; padding: 8px 12px; text-align: center;}
            th { background: #232c43; color: #62c4ff; }
            tr:nth-child(even) { background: #1e2539; }
            .lucro { color: #44ff6b; font-weight: bold; }
            .preju { color: #ff4664; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>Relatório de Auditoria de Trades</h1>
        <table>
            <tr>
    """

    # Cabeçalho
    for field in rows[0]:
        html += f"<th>{field}</th>"
    html += "</tr>"

    # Linhas
    for row in rows:
        html += "<tr>"
        for key, val in row.items():
            if key == "lucro_%":
                try:
                    perc = float(val)
                    css = "lucro" if perc >= 0 else "preju"
                    val = f'<span class="{css}">{perc:.2f}%</span>'
                except:
                    pass
            html += f"<td>{val}</td>"
        html += "</tr>"
    html += """
        </table>
        <p style="margin-top:40px;color:#888;">Gere novos relatórios sempre que quiser atualizar os resultados.<br>Feito por Tomoko 🦊</p>
    </body>
    </html>
    """

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Relatório HTML gerado com sucesso: {html_path}")

if __name__ == "__main__":
    csv_path = "resultado_auditoria.csv"
    html_path = "relatorio_auditoria.html"
    if not os.path.isfile(csv_path):
        print(f"Arquivo {csv_path} não encontrado.")
    else:
        gerar_relatorio_html(csv_path, html_path)
