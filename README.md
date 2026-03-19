[README.md](https://github.com/user-attachments/files/26103666/README.md)
# Monitor de Licitações — Diário Municipal AMUPE
### Município: Abreu e Lima · PE

Automação que roda todos os dias às **10h (Brasília)**, baixa o PDF do Diário Municipal da AMUPE, busca avisos de licitação de Abreu e Lima e envia um resumo por e-mail.

---

## Passo a passo de configuração

### 1. Criar conta no GitHub (gratuito)
Acesse https://github.com e crie uma conta gratuita se ainda não tiver.

---

### 2. Criar um repositório no GitHub

1. Clique em **"New repository"**
2. Nome: `monitor-licitacoes-amupe`
3. Deixe como **Privado** (Private)
4. Clique em **"Create repository"**

---

### 3. Fazer upload dos arquivos

Envie estes 3 arquivos para o repositório:
- `monitor_licitacoes.py`
- `requirements.txt`
- `.github/workflows/monitor.yml`

**Forma mais fácil (sem precisar de Git):**
1. No repositório, clique em **"Add file" → "Upload files"**
2. Faça upload de `monitor_licitacoes.py` e `requirements.txt`
3. Para o workflow, você precisará criar a pasta `.github/workflows/` manualmente:
   - Clique em **"Add file" → "Create new file"**
   - No campo do nome, digite: `.github/workflows/monitor.yml`
   - Cole o conteúdo do arquivo `monitor.yml`
   - Clique em **"Commit new file"**

---

### 4. Configurar a Senha de App do Gmail

> ⚠️ Não use sua senha normal do Gmail. Use uma "Senha de App" específica.

1. Acesse sua conta Google: https://myaccount.google.com
2. Vá em **Segurança** → ative a **Verificação em duas etapas** (se ainda não tiver)
3. Ainda em Segurança, procure **"Senhas de app"**
4. Em "Selecionar app", escolha **"Outro (nome personalizado)"** → digite "Monitor AMUPE"
5. Clique em **Gerar** → anote a senha de 16 caracteres gerada (ex: `abcd efgh ijkl mnop`)

---

### 5. Adicionar as Secrets no GitHub

1. No repositório, vá em **Settings → Secrets and variables → Actions**
2. Clique em **"New repository secret"** e adicione:

| Nome | Valor |
|------|-------|
| `GMAIL_USER` | seu e-mail do Gmail (ex: `seuemail@gmail.com`) |
| `GMAIL_APP_PASS` | a senha de app de 16 dígitos gerada no passo 4 |

---

### 6. Testar manualmente

1. No repositório, vá em **Actions** (menu superior)
2. Clique em **"Monitor Licitações AMUPE - Abreu e Lima"**
3. Clique em **"Run workflow" → "Run workflow"**
4. Aguarde ~1 minuto e verifique se o e-mail chegou

---

### 7. Pronto! A automação está ativa

A partir de agora, **todo dia útil às 10h** o script será executado automaticamente.

Você pode acompanhar cada execução em **Actions** no GitHub.

---

## Agendamento

| Configuração | Horário |
|---|---|
| Padrão | Segunda a sexta, 10h (Brasília) |
| Para incluir fim de semana | Edite o cron no arquivo `monitor.yml` para `"0 13 * * *"` |

---

## Dúvidas frequentes

**O e-mail não chegou. O que faço?**
→ Verifique em Actions se houve erro. O erro mais comum é a senha de app incorreta.

**Quero adicionar mais destinatários?**
→ Edite a lista `DESTINATARIOS` no arquivo `monitor_licitacoes.py`.

**Quero monitorar outro município também?**
→ Altere ou adicione ao campo `MUNICIPIO` no script.

---

*Gerado por Claude · Anthropic*
