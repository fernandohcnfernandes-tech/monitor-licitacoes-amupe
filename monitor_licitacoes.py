"""
Monitor de Licitações - Diário Municipal AMUPE
Município: Abreu e Lima - PE
Envia resumo diário por e-mail às 10h
Análise do PDF feita por Inteligência Artificial (Claude API)
"""

import os
import re
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
CLAUDE_MODEL  = "claude-sonnet-4-6"   # Sonnet: muito mais preciso que Haiku para classificacao
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
    """
    Extrai o texto do PDF respeitando o layout de DUAS COLUNAS do Diário AMUPE.

    O problema: pdfplumber.extract_text() juntava as duas colunas numa mesma
    linha, misturando conteúdo de municípios diferentes na mesma linha.
    Ex: "AVISO DE LICITAÇÃO - Município A    PORTARIA Nº 01 - Município B"

    A solução: divide cada página ao meio e extrai coluna esquerda e direita
    separadamente. Assim cada bloco de texto fica isolado e a regex consegue
    identificar os cabeçalhos sem interferência de outro município.
    """
    print("📖 Extraindo texto do PDF (modo duas colunas)...")
    blocos = []

    with pdfplumber.open(caminho_pdf) as pdf:
        total = len(pdf.pages)
        print(f"   Total de páginas: {total}")

        for i, pagina in enumerate(pdf.pages, 1):
            largura = pagina.width
            meio    = largura / 2

            col_esq = pagina.within_bbox((0,    0, meio,    pagina.height))
            col_dir = pagina.within_bbox((meio, 0, largura, pagina.height))

            for lado, col in [("E", col_esq), ("D", col_dir)]:
                txt = col.extract_text()
                if txt and txt.strip():
                    blocos.append(f"[PÁG {i}-{lado}]\n{txt.strip()}")

    texto_completo = "\n\n".join(blocos)
    print(f"   Blocos extraídos: {len(blocos)} (colunas separadas)")
    print(f"   Total de caracteres: {len(texto_completo):,}")
    return texto_completo


# ════════════════════════════════════════════════════════════
#  ETAPA 3 — Análise por Inteligência Artificial (Claude)
# ════════════════════════════════════════════════════════════

# Padrão regex que detecta EXATAMENTE o cabeçalho "AVISO DE LICITAÇÃO"
# A regex é a porteira: só passa quem tiver o cabeçalho correto.
# A IA entra DEPOIS — apenas para enriquecer blocos já confirmados.
_RE_AVISO = re.compile(
    r"AVISO\s+DE\s+LICITA[CÇ][AÃ]O",
    re.IGNORECASE
)

# Marcadores que indicam início de um NOVO ato (encerram o bloco atual)
_RE_NOVO_ATO = re.compile(
    r"^\s*(AVISO\s+DE|EXTRATO\s+DE|RESULTADO\s+DE|HOMOLOGA[CÇ][AÃ]O|"
    r"ADJUDICA[CÇ][AÃ]O|DISPENSA\s+DE|INEXIGIBILIDADE|RATIFIC|"
    r"PORTARIA\s+N|DECRETO\s+N|RESOLU[CÇ][AÃ]O\s+N|CONVOCA[CÇ][AÃ]O|"
    r"SELE[CÇ][AÃ]O\s+SIMPLIFICADA|CONCURSO\s+P[UÚ]BLICO|"
    r"TERMO\s+ADITIVO|RESCIS[AÃ]O\s+DE)",
    re.IGNORECASE
)


def analisar_com_ia(texto_diario):
    """
    Nova estratégia em duas etapas bem separadas:

    ETAPA A — REGEX (porteira, 100% precisa):
      Percorre linha a linha o texto do diário.
      Só abre um bloco quando encontra "AVISO DE LICITAÇÃO" no cabeçalho.
      Fecha o bloco no próximo ato administrativo.
      Confirma que o bloco menciona Abreu e Lima.
      → Resultado: lista de trechos de texto, cada um GARANTIDAMENTE um Aviso de Licitação.

    ETAPA B — IA (enriquecedora, não porteira):
      Recebe apenas os trechos já confirmados pela regex.
      Tarefa: extrair número, modalidade, objeto, data e resumo.
      Não decide mais o que é ou não é aviso — isso já foi resolvido.
    """
    print("🔍 Etapa A: filtrando cabeçalhos com regex...")
    linhas = texto_diario.splitlines()
    municipio_upper = MUNICIPIO.upper()

    blocos_confirmados = []
    i = 0
    n = len(linhas)

    while i < n:
        linha = linhas[i].strip()

        if _RE_AVISO.search(linha):
            # Abre um novo bloco a partir daqui
            bloco_linhas = [linha]
            j = i + 1

            while j < n:
                prox = linhas[j].strip()
                # Fecha o bloco se encontrar início de novo ato (mínimo 3 linhas coletadas)
                if j > i + 2 and _RE_NOVO_ATO.match(prox):
                    break
                bloco_linhas.append(prox)
                j += 1

            bloco_texto = "\n".join(bloco_linhas)

            # Confirma que o bloco pertence a Abreu e Lima
            if municipio_upper in bloco_texto.upper():
                blocos_confirmados.append(bloco_texto.strip())
                print(f"   ✅ Bloco confirmado pela regex: {linha[:60]}")

            i = j
        else:
            i += 1

    total_regex = len(blocos_confirmados)
    print(f"   Regex encontrou {total_regex} bloco(s) com cabeçalho 'AVISO DE LICITAÇÃO' de {MUNICIPIO}")

    if not blocos_confirmados:
        print("   ℹ️  Nenhum Aviso de Licitação de Abreu e Lima publicado hoje.")
        return []

    print("🤖 Etapa B: IA extraindo campos dos blocos confirmados...")
    avisos = []
    for idx, bloco in enumerate(blocos_confirmados, 1):
        print(f"   Enriquecendo bloco {idx}/{total_regex}...")
        aviso = _enriquecer_com_ia(bloco)
        if aviso:
            avisos.append(aviso)

    print(f"✅ Resultado final: {len(avisos)} Aviso(s) de Licitação de {MUNICIPIO}")
    return avisos


def _enriquecer_com_ia(bloco_texto):
    """
    Recebe um trecho de texto JÁ CONFIRMADO como Aviso de Licitação pela regex.
    Pede à IA APENAS para extrair e estruturar os campos — não para classificar.
    """
    system_prompt = (
        "Você é um assistente especializado em extrair informações estruturadas "
        "de publicações do Diário Oficial Municipal. "
        "O texto fornecido já foi confirmado como um Aviso de Licitação. "
        "Sua única tarefa é extrair os campos solicitados com precisão."
    )

    user_prompt = f"""O texto abaixo é um Aviso de Licitação publicado no Diário Oficial de {MUNICIPIO}.
Extraia os seguintes campos e retorne SOMENTE um objeto JSON válido, sem texto antes ou depois:

  "numero"        : número e modalidade completos (ex: "Pregão Eletrônico nº 012/2025")
  "modalidade"    : tipo de licitação (ex: "Pregão Eletrônico", "Tomada de Preços", "Chamada Pública")
  "objeto"        : descrição objetiva do que a Prefeitura quer comprar ou contratar
  "data_abertura" : data de abertura das propostas no formato DD/MM/AAAA, ou "" se não constar
  "valor_estimado": valor estimado, ou "" se não constar
  "resumo"        : 2 a 3 frases em português claro resumindo o aviso para um leitor leigo

TEXTO DO AVISO:
{bloco_texto}"""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"      ⚠️  Erro na API: {e}")
        # Fallback: retorna campos básicos sem IA
        return {
            "numero": "Não identificado",
            "modalidade": "Aviso de Licitação",
            "objeto": "Ver texto original",
            "data_abertura": "",
            "valor_estimado": "",
            "resumo": bloco_texto[:300],
        }

    texto = resp.json()["content"][0]["text"].strip()

    # Remove blocos markdown se presentes
    if "```" in texto:
        texto = "\n".join(
            l for l in texto.splitlines()
            if not l.strip().startswith("```")
        ).strip()

    try:
        aviso = json.loads(texto)
        return aviso if isinstance(aviso, dict) else None
    except json.JSONDecodeError:
        # Fallback com texto bruto
        return {
            "numero": "Não identificado",
            "modalidade": "Aviso de Licitação",
            "objeto": "Ver texto original",
            "data_abertura": "",
            "valor_estimado": "",
            "resumo": bloco_texto[:300],
        }

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
