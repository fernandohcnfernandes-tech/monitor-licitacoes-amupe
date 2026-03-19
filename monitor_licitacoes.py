"""
Monitor de Licitações - Diário Municipal AMUPE
Município: Abreu e Lima - PE
Envia resumo diário por e-mail às 10h
Análise do PDF feita por Inteligência Artificial (Claude API)
"""

import os
import json
import smtplib
import requests
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import pdfplumber


# ════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES  —  só mexa aqui se quiser personalizar
# ════════════════════════════════════════════════════════════

MUNICIPIO = "Abreu e Lima"

DESTINATARIOS = [
    ("Fernando",     "fernandohcnfernandes@gmail.com"),
    ("Dra. Fabiana", "fabianakiuska@mppe.mp.br"),
]

# Credenciais lidas dos Secrets do GitHub (nunca coloque senhas direto aqui!)
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]

URL_AMUPE    = "https://www.diariomunicipal.com.br/amupe/"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
TAMANHO_BLOCO = 80_000


# ════════════════════════════════════════════════════════════
#  ETAPA 1 — Baixar o PDF do dia
# ════════════════════════════════════════════════════════════

def baixar_pdf_do_dia():
    print("📥 Acessando site da AMUPE...")
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.get(URL_AMUPE, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    pdf_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") or "download" in href.lower():
            pdf_url = href if href.startswith("http") else "https://www.diariomunicipal.com.br" + href
            break

    if not pdf_url:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(k in href.lower() for k in ["edicao", "diario", "publicacao"]):
                pdf_url = href if href.startswith("http") else "https://www.diariomunicipal.com.br" + href
                break

    if not pdf_url:
        raise Exception("Não foi possível encontrar o link do PDF na página da AMUPE.")

    print(f"📄 PDF encontrado: {pdf_url}")
    pdf_resp = requests.get(pdf_url, headers=headers, timeout=60)
    pdf_resp.raise_for_status()

    caminho = "/tmp/diario_amupe.pdf"
    with open(caminho, "wb") as f:
        f.write(pdf_resp.content)

    print(f"✅ PDF salvo ({len(pdf_resp.content) // 1024} KB)")
    return caminho


# ════════════════════════════════════════════════════════════
#  ETAPA 2 — Extrair texto do PDF
# ════════════════════════════════════════════════════════════

def extrair_texto_pdf(caminho_pdf):
    print("📖 Extraindo texto do PDF...")
    paginas = []

    with pdfplumber.open(caminho_pdf) as pdf:
        total = len(pdf.pages)
        print(f"   Total de páginas: {total}")
        for i, pagina in enumerate(pdf.pages, 1):
            texto = pagina.extract_text()
            if texto and texto.strip():
                paginas.append(f"[PÁGINA {i}]\n{texto.strip()}")

    texto_completo = "\n\n".join(paginas)
    print(f"   Texto extraído: {len(texto_completo):,} caracteres")
    return texto_completo


# ════════════════════════════════════════════════════════════
#  ETAPA 3 — Análise por Inteligência Artificial (Claude)
# ════════════════════════════════════════════════════════════

def analisar_com_ia(texto_diario):
    print("🤖 Enviando para análise da IA...")

    blocos = [
        texto_diario[i : i + TAMANHO_BLOCO]
        for i in range(0, len(texto_diario), TAMANHO_BLOCO)
    ]
    print(f"   Texto dividido em {len(blocos)} bloco(s) para análise")

    todos_avisos = []
    for idx, bloco in enumerate(blocos, 1):
        print(f"   Analisando bloco {idx}/{len(blocos)}...")
        avisos_do_bloco = _chamar_claude(bloco, idx, len(blocos))
        todos_avisos.extend(avisos_do_bloco)

    # Remove duplicatas
    vistos = set()
    avisos_unicos = []
    for av in todos_avisos:
        chave = av.get("numero", "") + av.get("objeto", "")[:40]
        if chave not in vistos:
            vistos.add(chave)
            avisos_unicos.append(av)

    print(f"✅ IA encontrou {len(avisos_unicos)} Aviso(s) de Licitação de {MUNICIPIO}")
    return avisos_unicos


def _chamar_claude(texto_bloco, num_bloco, total_blocos):
    prompt = f"""Você é um especialista em licitações públicas municipais brasileiras.

Analise o texto abaixo, extraído do Diário Oficial Municipal (AMUPE) — bloco {num_bloco} de {total_blocos}.

Sua tarefa:
1. Encontre TODOS os "Aviso de Licitação" que pertençam ao município de {MUNICIPIO} / Prefeitura Municipal de {MUNICIPIO}.
2. IGNORE completamente avisos de outros municípios.
3. Para cada aviso encontrado, extraia:
   - "numero": número e modalidade (ex: "Pregão Eletrônico nº 012/2025")
   - "modalidade": tipo de licitação (ex: "Pregão Eletrônico", "Tomada de Preços", "Dispensa")
   - "objeto": descrição do que está sendo licitado
   - "resumo": resumo claro em 2 a 4 frases, em português simples
   - "data_abertura": data de abertura das propostas (DD/MM/AAAA) ou "" se não informada
   - "valor_estimado": valor estimado ou "" se não informado

Responda SOMENTE com um JSON válido, sem nenhum texto antes ou depois.
Se não houver nenhum aviso de {MUNICIPIO} neste bloco, responda exatamente: []

Formato esperado:
[
  {{
    "numero": "Pregão Eletrônico nº 001/2025",
    "modalidade": "Pregão Eletrônico",
    "objeto": "Aquisição de materiais de limpeza",
    "resumo": "A Prefeitura de {MUNICIPIO} torna público que realizará pregão eletrônico para aquisição de materiais de limpeza destinados às secretarias municipais.",
    "data_abertura": "15/04/2025",
    "valor_estimado": "R$ 45.000,00"
  }}
]

TEXTO DO DIÁRIO:
{texto_bloco}
"""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()

    texto_resposta = resp.json()["content"][0]["text"].strip()

    # Remove blocos de código markdown se o modelo os incluir
    if texto_resposta.startswith("```"):
        linhas = texto_resposta.splitlines()
        texto_resposta = "\n".join(
            l for l in linhas if not l.strip().startswith("```")
        ).strip()

    try:
        avisos = json.loads(texto_resposta)
        return avisos if isinstance(avisos, list) else []
    except json.JSONDecodeError as e:
        print(f"   ⚠️  Erro ao interpretar resposta da IA no bloco {num_bloco}: {e}")
        return []


# ════════════════════════════════════════════════════════════
#  ETAPA 4 — Montar e enviar o e-mail
# ════════════════════════════════════════════════════════════

def montar_email_html(avisos, data_hoje):
    data_fmt   = data_hoje.strftime("%d/%m/%Y")
    total      = len(avisos)
    cor_badge  = "#1D9E75" if total > 0 else "#888888"

    if not avisos:
        corpo_tabela = """
        <tr>
          <td colspan="5" style="padding:28px 20px;text-align:center;color:#888;font-size:14px;">
            Nenhum Aviso de Licitação de Abreu e Lima publicado hoje.
          </td>
        </tr>"""
    else:
        linhas = ""
        CORES_MOD = {
            "pregão":       ("#e8f0fe", "#1a56db"),
            "tomada":       ("#fef3c7", "#92400e"),
            "concorrência": ("#f0fdf4", "#166534"),
            "dispensa":     ("#fce7f3", "#9d174d"),
            "chamada":      ("#ede9fe", "#5b21b6"),
            "inexigib":     ("#fff7ed", "#9a3412"),
        }
        for i, av in enumerate(avisos):
            bg       = "#ffffff" if i % 2 == 0 else "#f7f9fc"
            mod      = av.get("modalidade", "Licitação")
            chave_cor = next((k for k in CORES_MOD if k in mod.lower()), None)
            cor_bg, cor_txt = CORES_MOD.get(chave_cor, ("#f3f4f6", "#374151"))

            linhas += f"""
            <tr style="background:{bg};vertical-align:top;">
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;font-size:13px;font-weight:600;color:#1e3a5f;min-width:160px;">
                {av.get('numero','—')}
                <div style="margin-top:6px;">
                  <span style="display:inline-block;background:{cor_bg};color:{cor_txt};
                    font-size:11px;font-weight:600;padding:2px 8px;border-radius:12px;">{mod}</span>
                </div>
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;font-size:13px;color:#374151;">
                {av.get('objeto','—')}
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;font-size:12px;color:#6b7280;line-height:1.6;">
                {av.get('resumo','—')}
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;font-size:12px;color:#374151;white-space:nowrap;">
                {av.get('data_abertura','') or '—'}
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;font-size:12px;color:#374151;white-space:nowrap;">
                {av.get('valor_estimado','') or '—'}
              </td>
            </tr>"""
        corpo_tabela = linhas

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background:#f0f2f5;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:32px 0;">
<tr><td align="center">
<table width="700" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:10px;overflow:hidden;border:1px solid #dde1e7;">
  <tr>
    <td style="background:#1a4f8a;padding:28px 32px;">
      <p style="margin:0;color:#a8c8f0;font-size:11px;letter-spacing:2px;text-transform:uppercase;">Monitoramento Automático · AMUPE</p>
      <h1 style="margin:8px 0 4px;color:#fff;font-size:22px;font-weight:700;">Avisos de Licitação</h1>
      <p style="margin:0;color:#cce0f5;font-size:14px;">Município de {MUNICIPIO} &nbsp;·&nbsp; {data_fmt}</p>
    </td>
  </tr>
  <tr>
    <td style="padding:18px 32px;border-bottom:1px solid #eaecf0;background:#f8fafc;">
      <span style="display:inline-block;background:{cor_badge};color:#fff;font-size:14px;font-weight:700;padding:6px 18px;border-radius:20px;">
        {total} Aviso(s) de Licitação encontrado(s) hoje
      </span>
      <span style="margin-left:12px;font-size:12px;color:#9ca3af;">Análise por Inteligência Artificial</span>
    </td>
  </tr>
  <tr>
    <td style="padding:0 32px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0"
        style="margin-top:20px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f0f4f9;">
            <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;font-weight:700;border-bottom:2px solid #dce6f0;text-transform:uppercase;width:20%;">Número / Modalidade</th>
            <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;font-weight:700;border-bottom:2px solid #dce6f0;text-transform:uppercase;width:25%;">Objeto</th>
            <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;font-weight:700;border-bottom:2px solid #dce6f0;text-transform:uppercase;width:35%;">Resumo (IA)</th>
            <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;font-weight:700;border-bottom:2px solid #dce6f0;text-transform:uppercase;width:10%;">Abertura</th>
            <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;font-weight:700;border-bottom:2px solid #dce6f0;text-transform:uppercase;width:10%;">Valor est.</th>
          </tr>
        </thead>
        <tbody>{corpo_tabela}</tbody>
      </table>
    </td>
  </tr>
  <tr>
    <td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #eaecf0;">
      <p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.7;">
        Gerado automaticamente todos os dias úteis às <strong>10h</strong> (Brasília).<br>
        Fonte: <a href="{URL_AMUPE}" style="color:#1a4f8a;">{URL_AMUPE}</a> · Análise: Claude AI (Anthropic)
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""


def enviar_email(html, avisos, data_hoje):
    data_fmt = data_hoje.strftime("%d/%m/%Y")
    total    = len(avisos)
    assunto  = f"[Licitações {MUNICIPIO}] {total} aviso(s) — {data_fmt}"

    print(f"📧 Enviando e-mail para {len(DESTINATARIOS)} destinatário(s)...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        for nome, endereco in DESTINATARIOS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = assunto
            msg["From"]    = f"Monitor Licitações AMUPE <{GMAIL_USER}>"
            msg["To"]      = endereco
            msg.attach(MIMEText(html, "html", "utf-8"))
            smtp.sendmail(GMAIL_USER, endereco, msg.as_string())
            print(f"   ✅ Enviado para {nome} <{endereco}>")


# ════════════════════════════════════════════════════════════
#  EXECUÇÃO PRINCIPAL
# ════════════════════════════════════════════════════════════

def main():
    data_hoje = date.today()
    print("\n" + "═"*52)
    print(f"  Monitor AMUPE · {MUNICIPIO} · {data_hoje.strftime('%d/%m/%Y')}")
    print("═"*52 + "\n")

    caminho_pdf = baixar_pdf_do_dia()
    texto       = extrair_texto_pdf(caminho_pdf)
    avisos      = analisar_com_ia(texto)
    html        = montar_email_html(avisos, data_hoje)
    enviar_email(html, avisos, data_hoje)

    print("\n✅ Processo concluído com sucesso!")


if __name__ == "__main__":
    main()
