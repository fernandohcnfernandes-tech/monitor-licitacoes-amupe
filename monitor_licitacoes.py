"""
Monitor de Licitações - Diário Municipal AMUPE
Município: Abreu e Lima - PE
Envia resumo diário por e-mail às 10h
"""

import os
import re
import smtplib
import requests
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import pdfplumber


# ── Configurações ─────────────────────────────────────────────────────────────

MUNICIPIO = "ABREU E LIMA"

DESTINATARIOS = [
    ("Fernando", "fernandohcnfernandes@gmail.com"),
    ("Dra. Fabiana", "fabianakiuska@mppe.mp.br"),
]

REMETENTE_EMAIL = os.environ["GMAIL_USER"]      # ex: seuemail@gmail.com
REMETENTE_SENHA = os.environ["GMAIL_APP_PASS"]  # Senha de app do Gmail

URL_AMUPE = "https://www.diariomunicipal.com.br/amupe/"

PALAVRAS_LICITACAO = [
    "licitação", "licitacao", "aviso de licitação", "aviso de licitacao",
    "pregão", "pregao", "tomada de preço", "tomada de preco",
    "concorrência", "concorrencia", "chamada pública", "chamada publica",
    "dispensa", "inexigibilidade", "edital", "resultado de licitação",
    "resultado de licitacao", "homologação", "homologacao", "adjudicação",
    "adjudicacao", "contrato", "adesão", "adesao"
]


# ── Funções ───────────────────────────────────────────────────────────────────

def baixar_pdf_do_dia():
    """Acessa o site da AMUPE e baixa o PDF do diário do dia atual."""
    print("📥 Acessando site da AMUPE...")
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(URL_AMUPE, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Busca link do PDF mais recente (primeiro link .pdf na página)
    pdf_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") or "download" in href.lower():
            pdf_url = href if href.startswith("http") else "https://www.diariomunicipal.com.br" + href
            break

    # Fallback: busca qualquer link que contenha "edicao" ou "diario"
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

    print(f"✅ PDF salvo em {caminho}")
    return caminho


def extrair_avisos_licitacao(caminho_pdf):
    """
    Lê o PDF e extrai blocos de texto relacionados a licitações
    do município de Abreu e Lima.
    Retorna lista de dicts: {numero, objeto, resumo}
    """
    print("🔍 Analisando PDF...")
    avisos = []

    with pdfplumber.open(caminho_pdf) as pdf:
        texto_completo = ""
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                texto_completo += t + "\n"

    # Divide em blocos por município
    # Estratégia: encontra seções que mencionam Abreu e Lima
    linhas = texto_completo.splitlines()
    municipio_upper = MUNICIPIO.upper()

    # Coleta índices de linhas onde aparece "Abreu e Lima"
    indices_municipio = [
        i for i, l in enumerate(linhas)
        if municipio_upper in l.upper()
    ]

    if not indices_municipio:
        print("ℹ️  Nenhuma menção a Abreu e Lima encontrada no diário de hoje.")
        return []

    # Para cada ocorrência, captura um bloco de até 60 linhas ao redor
    blocos_vistos = set()
    for idx in indices_municipio:
        inicio = max(0, idx - 5)
        fim = min(len(linhas), idx + 60)
        bloco = "\n".join(linhas[inicio:fim])

        # Verifica se o bloco contém palavras de licitação
        bloco_lower = bloco.lower()
        if not any(p in bloco_lower for p in PALAVRAS_LICITACAO):
            continue

        # Evita duplicatas
        chave = bloco[:80]
        if chave in blocos_vistos:
            continue
        blocos_vistos.add(chave)

        aviso = parsear_bloco(bloco)
        if aviso:
            avisos.append(aviso)

    print(f"✅ {len(avisos)} aviso(s) de licitação encontrado(s).")
    return avisos


def parsear_bloco(bloco):
    """Extrai número, objeto e resumo de um bloco de texto."""
    numero = "Não identificado"
    objeto = "Não identificado"

    # Tenta extrair número da licitação (ex: Pregão 001/2025, Edital nº 003/2024)
    padroes_numero = [
        r"(?:pregão|tomada de preço|concorrência|chamada pública|dispensa|inexigibilidade|edital)[^\d]*(\d{1,4}[\/\-]\d{4})",
        r"(?:processo|proc\.?)[^\d]*(\d{3,}[\/\-]\d{4})",
        r"n[°º\.]\s*(\d{1,4}[\/\-]\d{4})",
    ]
    for padrao in padroes_numero:
        m = re.search(padrao, bloco, re.IGNORECASE)
        if m:
            # Pega a linha inteira que contém esse padrão como "número"
            for linha in bloco.splitlines():
                if m.group(0)[:10] in linha:
                    numero = linha.strip()
                    break
            break

    # Tenta extrair objeto
    m_obj = re.search(
        r"objeto[:\s]+(.{10,200}?)(?:\n|valor|prazo|data|processo|$)",
        bloco, re.IGNORECASE | re.DOTALL
    )
    if m_obj:
        objeto = m_obj.group(1).strip().replace("\n", " ")
        objeto = re.sub(r"\s{2,}", " ", objeto)

    # Resumo: primeiras 400 caracteres do bloco limpo
    resumo = re.sub(r"\s{2,}", " ", bloco.replace("\n", " ")).strip()[:400]

    return {
        "numero": numero,
        "objeto": objeto,
        "resumo": resumo,
    }


def montar_email_html(avisos, data_hoje):
    """Monta o corpo HTML do e-mail."""
    data_fmt = data_hoje.strftime("%d/%m/%Y")

    if not avisos:
        corpo_avisos = """
        <tr>
          <td colspan="3" style="padding:20px; text-align:center; color:#666;">
            Nenhum aviso de licitação de Abreu e Lima encontrado no diário de hoje.
          </td>
        </tr>
        """
    else:
        linhas = ""
        for i, av in enumerate(avisos):
            bg = "#ffffff" if i % 2 == 0 else "#f9f9f9"
            linhas += f"""
            <tr style="background:{bg};">
              <td style="padding:10px 12px; border-bottom:1px solid #eee; vertical-align:top; font-size:13px;">
                {av['numero']}
              </td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee; vertical-align:top; font-size:13px;">
                {av['objeto']}
              </td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee; vertical-align:top; font-size:12px; color:#555;">
                {av['resumo']}
              </td>
            </tr>
            """
        corpo_avisos = linhas

    total = len(avisos)
    cor_badge = "#1D9E75" if total > 0 else "#888"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0; padding:0; font-family:Arial,sans-serif; background:#f4f4f4;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4; padding:30px 0;">
        <tr><td align="center">
          <table width="650" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.08);">

            <!-- Cabeçalho -->
            <tr>
              <td style="background:#1a4f8a; padding:24px 30px;">
                <p style="margin:0; color:#ffffff; font-size:11px; text-transform:uppercase; letter-spacing:1px;">Monitoramento Diário</p>
                <h1 style="margin:6px 0 0; color:#ffffff; font-size:20px; font-weight:600;">
                  Diário Municipal AMUPE
                </h1>
                <p style="margin:4px 0 0; color:#aac4e8; font-size:13px;">
                  Avisos de Licitação — Abreu e Lima · {data_fmt}
                </p>
              </td>
            </tr>

            <!-- Badge resumo -->
            <tr>
              <td style="padding:16px 30px; border-bottom:1px solid #eee;">
                <span style="display:inline-block; background:{cor_badge}; color:#fff; font-size:13px; font-weight:600; padding:5px 14px; border-radius:20px;">
                  {total} aviso(s) encontrado(s)
                </span>
              </td>
            </tr>

            <!-- Tabela de avisos -->
            <tr>
              <td style="padding:0 30px 20px;">
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px; border:1px solid #eee; border-radius:6px; overflow:hidden;">
                  <thead>
                    <tr style="background:#f0f4f9;">
                      <th style="padding:10px 12px; text-align:left; font-size:12px; color:#444; font-weight:600; border-bottom:2px solid #dce6f0; width:25%;">Número / Modalidade</th>
                      <th style="padding:10px 12px; text-align:left; font-size:12px; color:#444; font-weight:600; border-bottom:2px solid #dce6f0; width:30%;">Objeto</th>
                      <th style="padding:10px 12px; text-align:left; font-size:12px; color:#444; font-weight:600; border-bottom:2px solid #dce6f0; width:45%;">Resumo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {corpo_avisos}
                  </tbody>
                </table>
              </td>
            </tr>

            <!-- Rodapé -->
            <tr>
              <td style="padding:16px 30px; background:#f9f9f9; border-top:1px solid #eee;">
                <p style="margin:0; font-size:11px; color:#999;">
                  Este e-mail é gerado automaticamente todos os dias às 10h.<br>
                  Fonte: <a href="{URL_AMUPE}" style="color:#1a4f8a;">{URL_AMUPE}</a>
                </p>
              </td>
            </tr>

          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """
    return html


def enviar_email(html, avisos, data_hoje):
    """Envia o e-mail para todos os destinatários."""
    data_fmt = data_hoje.strftime("%d/%m/%Y")
    total = len(avisos)
    assunto = f"[Licitações Abreu e Lima] {total} aviso(s) — {data_fmt}"

    print(f"📧 Enviando e-mail para {len(DESTINATARIOS)} destinatário(s)...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(REMETENTE_EMAIL, REMETENTE_SENHA)

        for nome, email in DESTINATARIOS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = assunto
            msg["From"] = f"Monitor Licitações AMUPE <{REMETENTE_EMAIL}>"
            msg["To"] = email

            msg.attach(MIMEText(html, "html", "utf-8"))
            smtp.sendmail(REMETENTE_EMAIL, email, msg.as_string())
            print(f"  ✅ Enviado para {nome} <{email}>")


# ── Execução principal ─────────────────────────────────────────────────────────

def main():
    data_hoje = date.today()
    print(f"\n{'='*50}")
    print(f"Monitor AMUPE — {data_hoje.strftime('%d/%m/%Y')}")
    print(f"{'='*50}\n")

    try:
        caminho_pdf = baixar_pdf_do_dia()
        avisos = extrair_avisos_licitacao(caminho_pdf)
        html = montar_email_html(avisos, data_hoje)
        enviar_email(html, avisos, data_hoje)
        print("\n✅ Processo concluído com sucesso!")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        raise


if __name__ == "__main__":
    main()
