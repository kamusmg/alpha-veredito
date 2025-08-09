# Alpha Veredito — Guia de Restauração

📌 **Função:**  
Sistema para validar e auditar sinais do **Alpha Engine**, com integração à API da Binance, auditoria automática e visualização via Streamlit.

---

## 🔄 Prompt para reativar o projeto no futuro
Cole isso no GPT:

Você é meu assistente e precisa me ajudar a restaurar o projeto Alpha Veredito hospedado no GitHub.
O projeto foi feito em Python e usa Streamlit, integração com a API da Binance e scripts de auditoria.
Ele está disponível no repositório:
https://github.com/kamusmg/alpha-veredito

Tarefas:

Me passe os comandos para clonar o repositório.

Ensine como criar e ativar o ambiente virtual Python.

Liste e instale as dependências corretas (use um requirements.txt ou me peça para gerar um).

Me diga como iniciar a aplicação (principalmente o app_live.py).

Explique onde configurar as chaves da Binance no .env.

Teste localmente se o sistema abre no navegador.

Confirme que a auditoria e coleta de sinais está funcionando.

yaml
Copiar
Editar

---

## 📦 Passo a passo rápido (sem GPT)
```bash
# 1. Clonar
git clone https://github.com/kamusmg/alpha-veredito.git
cd alpha-veredito

# 2. Criar ambiente virtual
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Criar .env e colocar:
BINANCE_API_KEY=SUACHAVEAQUI
BINANCE_SECRET_KEY=SUACHAVEAQUI

# 5. Rodar
streamlit run app_live.py
📂 Estrutura importante
app_live.py → Interface Streamlit (tempo real).

app_auditoria.py → Auditoria offline.

sinais/ → Arquivos JSON de sinais.

audits/ → Logs de auditoria.

utils/ → Funções auxiliares.

.env → Configurações de API.

💡 Obs:
O .gitignore já ignora cache e arquivos temporários.
O código está pronto pra ser rodado em qualquer máquina com Python 3.9+.

yaml
Copiar
Editar

---

Se quiser, eu já subo esse README no repositório pra você agora e ele já fica guardado no backup. Quer que 