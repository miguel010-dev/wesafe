# WeSafe — ajustes aplicados

## 1. Erros no Render (127 e 1)
- **Erro 127** ("comando não encontrado"): faltava o `gunicorn` no `requirements.txt` e não havia `Procfile`/comando de start. Adicionei `gunicorn` às dependências e criei:
  - `Procfile` → `web: gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
  - `render.yaml` (opcional, para deploy via "Blueprint")
- **Erro 1** (app derruba ao subir): o `app.py` exige `JWT_SECRET_KEY` forte (`STRICT_SECRETS=true`) e falha de propósito se não estiver definida. No Render, configure as variáveis de ambiente em **Settings → Environment** (não bastam estar só no `.env` local, o Render não lê esse arquivo automaticamente a menos que você o suba no repositório).

No Render, configure pelo menos:
```
JWT_SECRET_KEY=<uma string aleatória forte, ex: python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=sqlite:///wesafe.db   (ou uma URL de Postgres, se preferir persistência real)
CORS_ORIGINS=https://seu-app.onrender.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASS=...
SMTP_USE_TLS=true
SMTP_FROM=WeSafe <...>
ADMIN_EMAIL=...
ADMIN_PASSWORD=...
```

> ⚠️ **Importante sobre o SQLite**: no plano gratuito do Render o disco é efêmero — o banco `wesafe.db` é apagado a cada novo deploy/restart. Para dados persistentes de verdade, use um Postgres gerenciado (Render oferece um) e aponte `DATABASE_URL` para ele.

## 2. Verificação de email por código OTP (SMTP)
O cadastro agora acontece em duas etapas, usando as credenciais SMTP do `.env`:
1. `POST /api/register` → valida os dados e envia um código de 6 dígitos por email (não cria a conta ainda).
2. `POST /api/register/verify-otp` → confirma o código e cria a conta (retorna o token de acesso).
3. `POST /api/register/resend-otp` → reenvia um novo código, se necessário.

O front-end (`registro.html`) já foi atualizado com a tela de verificação (usando o estilo `.otp-digit` que já existia no `theme.css`).

## 3. Segurança — troque a senha do Gmail
O arquivo `_env` enviado continha uma senha de app do Gmail (`SMTP_PASS`) já em texto puro. Como ela passou por este chat, **recomendo fortemente gerar uma nova senha de app no Google e atualizar o `.env`/variáveis do Render**, em vez de manter a antiga.

## 4. Estrutura do projeto
Reorganizei para o padrão esperado pelo Flask (o `app.py` já usa `render_template` e `url_for('static', ...)`):
```
app.py
requirements.txt
Procfile
render.yaml
.env              (local — NÃO commitar; já está no .gitignore)
templates/        (todos os .html)
static/css/       (theme.css, admin.css)
static/js/        (app.js, admin.js, profile.js)
```
Os arquivos `teste.html` e `_teste_referencia.html` eram duplicados idênticos ao `admin_dashboard`-like de teste e foram removidos por não serem usados por nenhuma rota do `app.py`.

## 5. Design da tela de mapa (`inicio.html`)
Adicionei uma camada de polimento visual sem tocar em nenhum ID usado pelo `app.js`:
- Badges circulares coloridos nos ícones de modo de transporte e de denúncia.
- Brilho/leve elevação ao passar o mouse/tocar nos painéis, chips e botões.
- Brilho pulsante suave no chip de risco da rota e no botão SOS.
- Entrada suave (fade-in) dos painéis principais ao carregar a tela.

## Rodando localmente
```bash
pip install -r requirements.txt
cp .env .env.local   # ou edite o .env já incluso
python app.py
```
