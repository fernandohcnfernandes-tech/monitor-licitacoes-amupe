"""
Monitor de Licitações - Diário Municipal AMUPE
Município: Abreu e Lima - PE
Envia resumo diário por e-mail às 10h
VERSÃO: 5.0 — baseada na análise do PDF real
"""

import os, re, json, smtplib, requests
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import pdfplumber

# ════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES
# ════════════════════════════════════════════════════════════

MUNICIPIO    = "Abreu e Lima"
DESTINATARIOS = [
    ("Fernando",     "fernandohcnfernandes@gmail.com"),
    ("Dra. Fabiana", "fabianakiuska@mppe.mp.br"),
]
GMAIL_USER    = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
URL_AMUPE     = "https://www.diariomunicipal.com.br/amupe/"
CLAUDE_MODEL  = "claude-sonnet-4-6"

# ════════════════════════════════════════════════════════════
#  ETAPA 1 — Baixar PDF
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
        raise Exception("PDF não encontrado na página da AMUPE.")
    print(f"📄 PDF: {pdf_url}")
    r = requests.get(pdf_url, headers=headers, timeout=60)
    r.raise_for_status()
    caminho = "/tmp/diario_amupe.pdf"
    with open(caminho, "wb") as f:
        f.write(r.content)
    print(f"✅ PDF salvo ({len(r.content)//1024} KB)")
    return caminho

# ════════════════════════════════════════════════════════════
#  ETAPA 2 — Extrair texto por colunas
# ════════════════════════════════════════════════════════════

def extrair_texto_pdf(caminho_pdf):
    """
    O PDF tem duas colunas por página.
    Extraímos coluna esquerda e direita separadamente
    para não misturar publicações de municípios diferentes.
    """
    print("📖 Extraindo texto (modo duas colunas)...")
    blocos = []
    with pdfplumber.open(caminho_pdf) as pdf:
        print(f"   Páginas: {len(pdf.pages)}")
        for i, pag in enumerate(pdf.pages, 1):
            meio = pag.width / 2
            for lado, bbox in [("E", (0, 0, meio, pag.height)),
                                ("D", (meio, 0, pag.width, pag.height))]:
                txt = pag.within_bbox(bbox).extract_text()
                if txt and txt.strip():
                    blocos.append(f"[PÁG {i}-{lado}]\n{txt.strip()}")
    texto = "\n\n".join(blocos)
    print(f"   {len(blocos)} blocos | {len(texto):,} caracteres")
    return texto

# ════════════════════════════════════════════════════════════
#  ETAPA 3 — Isolar seção de Abreu e Lima e extrair avisos
# ════════════════════════════════════════════════════════════

# Cabeçalho que o PDF usa para separar municípios:
#   ESTADO DE PERNAMBUCO
#   MUNICÍPIO DE ABREU E LIMA
_RE_CAB_ABREU = re.compile(
    r"MUNIC[IÍ]PIO\s+DE\s+ABREU\s+E\s+LIMA",
    re.IGNORECASE
)

# Cabeçalho de OUTRO município (encerra a seção de Abreu e Lima)
_RE_CAB_OUTRO = re.compile(
    r"^ESTADO\s+DE\s+PERNAMBUCO\s*$|^MUNIC[IÍ]PIO\s+DE\s+(?!ABREU)",
    re.IGNORECASE | re.MULTILINE
)

# Aviso de Licitação — deve estar em linha própria (cabeçalho do ato)
_RE_AVISO = re.compile(
    r"^AVISO\s+DE\s+LICITA[CÇ][AÃ]O",
    re.IGNORECASE
)

# Início de novo ato administrativo (fecha o bloco do aviso atual)
_RE_NOVO_ATO = re.compile(
    r"^(AVISO\s+DE|EXTRATO\s+DE|RESULTADO\s+DA?|HOMOLOGA[CÇ][AÃ]O|"
    r"ADJUDICA[CÇ][AÃ]O|DISPENSA\s+N|INEXIGIBILIDADE|RATIFIC|"
    r"PORTARIA|DECRETO|RESOLU[CÇ][AÃ]O|CONVOCA[CÇ][AÃ]O|"
    r"SELE[CÇ][AÃ]O\s+SIMPLIFICADA|CONCURSO|TERMO\s+ADITIVO|"
    r"RESCIS[AÃ]O|ESTADO\s+DE\s+PERNAMBUCO|MUNIC[IÍ]PIO\s+DE)",
    re.IGNORECASE
)


def extrair_secao_abreu_e_lima(texto):
    """
    Localiza o cabeçalho 'MUNICÍPIO DE ABREU E LIMA' no texto
    e retorna apenas as linhas entre esse cabeçalho e o início
    do próximo município. Pode haver mais de uma seção por PDF.
    """
    linhas = texto.splitlines()
    n = len(linhas)
    secoes = []

    i = 0
    while i < n:
        if _RE_CAB_ABREU.search(linhas[i]):
            secao = []
            j = i
            while j < n:
                linha = linhas[j].strip()
                # Encerra se encontrar "ESTADO DE PERNAMBUCO" seguido de outro município
                # (padrão real do PDF: "ESTADO DE PERNAMBUCO" na linha, município na próxima)
                if j > i + 3:
                    if (re.match(r"^ESTADO\s+DE\s+PERNAMBUCO\s*$", linha, re.IGNORECASE) and
                            j + 1 < n and _RE_CAB_ABREU.search(linhas[j+1]) is None and
                            re.search(r"MUNIC[IÍ]PIO\s+DE", linhas[j+1], re.IGNORECASE)):
                        break
                secao.append(linhas[j])
                j += 1
            if secao:
                secoes.append(secao)
                print(f"   ✅ Seção de Abreu e Lima: {len(secao)} linhas (a partir da linha {i})")
            i = j
        else:
            i += 1

    return secoes


def extrair_avisos_da_secao(secao_linhas):
    """
    Dentro da seção já isolada de Abreu e Lima,
    procura linhas que começam com 'AVISO DE LICITAÇÃO'
    e captura o bloco até o próximo ato.
    """
    avisos_texto = []
    n = len(secao_linhas)
    i = 0

    while i < n:
        linha = secao_linhas[i].strip()
        if _RE_AVISO.match(linha):
            bloco = [linha]
            j = i + 1
            while j < n:
                prox = secao_linhas[j].strip()
                # Fecha bloco ao encontrar início de novo ato (após mínimo 3 linhas)
                if j > i + 2 and _RE_NOVO_ATO.match(prox):
                    break
                bloco.append(prox)
                j += 1
            texto_bloco = "\n".join(bloco).strip()
            avisos_texto.append(texto_bloco)
            print(f"   📋 Aviso encontrado: {linha[:70]}")
            i = j
        else:
            i += 1

    return avisos_texto


def analisar_com_ia(texto_diario):
    print("🔍 Etapa A: isolando seção de Abreu e Lima...")
    secoes = extrair_secao_abreu_e_lima(texto_diario)

    if not secoes:
        print("   ℹ️  Cabeçalho 'MUNICÍPIO DE ABREU E LIMA' não encontrado hoje.")
        return []

    print(f"🔍 Etapa B: buscando 'AVISO DE LICITAÇÃO' nas {len(secoes)} seção(ões)...")
    todos_blocos = []
    for secao in secoes:
        blocos = extrair_avisos_da_secao(secao)
        todos_blocos.extend(blocos)

    total = len(todos_blocos)
    print(f"   Total de avisos encontrados pela regex: {total}")

    if not todos_blocos:
        print("   ℹ️  Nenhum 'AVISO DE LICITAÇÃO' publicado hoje para Abreu e Lima.")
        return []

    print("🤖 Etapa C: IA redigindo resumos em linguagem natural...")
    avisos = []
    for idx, bloco in enumerate(todos_blocos, 1):
        print(f"   Redigindo aviso {idx}/{total}...")
        aviso = _enriquecer_com_ia(bloco)
        if aviso:
            avisos.append(aviso)

    print(f"✅ {len(avisos)} Aviso(s) de Licitação de {MUNICIPIO}")
    return avisos


def _enriquecer_com_ia(bloco_texto):
    system_prompt = (
        "Você é um assistente especializado em extrair informações de publicações "
        "do Diário Oficial Municipal. O texto já foi confirmado como um Aviso de Licitação. "
        "Extraia os campos solicitados com precisão e redija o resumo em linguagem simples."
    )
    user_prompt = f"""Texto de um Aviso de Licitação do Diário Oficial de {MUNICIPIO}.
Retorne SOMENTE um objeto JSON válido, sem texto antes ou depois.

Campos:
  "numero"        : número e modalidade (ex: "Pregão Eletrônico nº 012/2025")
  "modalidade"    : tipo de licitação (ex: "Pregão Eletrônico", "Chamada Pública")
  "objeto"        : em UMA frase clara o que a Prefeitura quer contratar. Não copie o original.
  "data_abertura" : data de abertura das propostas (DD/MM/AAAA) ou ""
  "valor_estimado": valor estimado ou ""
  "resumo"        : 3 a 4 frases em linguagem simples explicando: o que será contratado,
                    para qual finalidade, como participar e prazo. NÃO copie o texto original.
                    Escreva como se explicasse para alguém que não conhece licitações.

TEXTO:
{bloco_texto}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json",
                     "x-api-key": ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01"},
            json={"model": CLAUDE_MODEL, "max_tokens": 1024,
                  "system": system_prompt,
                  "messages": [{"role": "user", "content": user_prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        texto = resp.json()["content"][0]["text"].strip()
        if "```" in texto:
            texto = "\n".join(l for l in texto.splitlines()
                              if not l.strip().startswith("```")).strip()
        aviso = json.loads(texto)
        return aviso if isinstance(aviso, dict) else None
    except Exception as e:
        print(f"      ⚠️  Erro na IA: {e}")
        return {"numero": "Não identificado", "modalidade": "Aviso de Licitação",
                "objeto": "Ver diário original", "data_abertura": "",
                "valor_estimado": "", "resumo": bloco_texto[:300]}

# ════════════════════════════════════════════════════════════
#  ETAPA 4 — Montar e-mail HTML
# ════════════════════════════════════════════════════════════

def montar_email_html(avisos, data_hoje):
    data_fmt  = data_hoje.strftime("%d/%m/%Y")
    total     = len(avisos)
    cor_badge = "#1D9E75" if total > 0 else "#888888"

    CORES = {
        "pregão":       ("#e8f0fe", "#1a56db"),
        "tomada":       ("#fef3c7", "#92400e"),
        "concorrência": ("#f0fdf4", "#166534"),
        "chamada":      ("#ede9fe", "#5b21b6"),
        "dispensa":     ("#fce7f3", "#9d174d"),
        "inexigib":     ("#fff7ed", "#9a3412"),
    }

    if not avisos:
        corpo = """<tr><td colspan="5" style="padding:28px;text-align:center;
            color:#888;font-size:14px;">
            Nenhum Aviso de Licitação de Abreu e Lima publicado hoje.</td></tr>"""
    else:
        corpo = ""
        for i, av in enumerate(avisos):
            bg  = "#ffffff" if i % 2 == 0 else "#f7f9fc"
            mod = av.get("modalidade", "Licitação")
            k   = next((c for c in CORES if c in mod.lower()), None)
            cbg, ctxt = CORES.get(k, ("#f3f4f6", "#374151"))
            corpo += f"""
            <tr style="background:{bg};vertical-align:top;">
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;
                font-size:13px;font-weight:600;color:#1e3a5f;min-width:160px;">
                {av.get('numero','—')}
                <div style="margin-top:6px;">
                  <span style="background:{cbg};color:{ctxt};font-size:11px;
                    font-weight:600;padding:2px 8px;border-radius:12px;
                    display:inline-block;">{mod}</span>
                </div>
              </td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;
                font-size:13px;color:#374151;">{av.get('objeto','—')}</td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;
                font-size:12px;color:#6b7280;line-height:1.6;">{av.get('resumo','—')}</td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;
                font-size:12px;color:#374151;white-space:nowrap;">
                {av.get('data_abertura','') or '—'}</td>
              <td style="padding:14px 12px;border-bottom:1px solid #eaecf0;
                font-size:12px;color:#374151;white-space:nowrap;">
                {av.get('valor_estimado','') or '—'}</td>
            </tr>"""

    return f"""<!DOCTYPE html><html lang="pt-BR">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f0f2f5;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 0;">
<tr><td align="center">
<table width="700" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:10px;border:1px solid #dde1e7;">
  <tr><td style="background:#1a4f8a;padding:28px 32px;">
    <p style="margin:0;color:#a8c8f0;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
      Monitoramento Automático · AMUPE</p>
    <h1 style="margin:8px 0 4px;color:#fff;font-size:22px;font-weight:700;">Avisos de Licitação</h1>
    <p style="margin:0;color:#cce0f5;font-size:14px;">
      Município de {MUNICIPIO} &nbsp;·&nbsp; {data_fmt}</p>
  </td></tr>
  <tr><td style="padding:18px 32px;border-bottom:1px solid #eaecf0;background:#f8fafc;">
    <span style="background:{cor_badge};color:#fff;font-size:14px;font-weight:700;
      padding:6px 18px;border-radius:20px;display:inline-block;">
      {total} Aviso(s) de Licitação encontrado(s) hoje</span>
    <span style="margin-left:12px;font-size:12px;color:#9ca3af;">
      Análise por Inteligência Artificial</span>
  </td></tr>
  <tr><td style="padding:0 32px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0"
      style="margin-top:20px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      <thead><tr style="background:#f0f4f9;">
        <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;
          font-weight:700;border-bottom:2px solid #dce6f0;width:20%;">NÚMERO / MODALIDADE</th>
        <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;
          font-weight:700;border-bottom:2px solid #dce6f0;width:25%;">OBJETO</th>
        <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;
          font-weight:700;border-bottom:2px solid #dce6f0;width:33%;">RESUMO</th>
        <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;
          font-weight:700;border-bottom:2px solid #dce6f0;width:10%;">ABERTURA</th>
        <th style="padding:11px 12px;text-align:left;font-size:11px;color:#6b7280;
          font-weight:700;border-bottom:2px solid #dce6f0;width:12%;">VALOR EST.</th>
      </tr></thead>
      <tbody>{corpo}</tbody>
    </table>
  </td></tr>
  <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #eaecf0;">
    <p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.7;">
      Gerado automaticamente todos os dias úteis às <strong>10h</strong> (Brasília).<br>
      Fonte: <a href="{URL_AMUPE}" style="color:#1a4f8a;">{URL_AMUPE}</a>
      · Análise: Claude AI (Anthropic)</p>
  </td></tr>
</table></td></tr></table>
</body></html>"""

# ════════════════════════════════════════════════════════════
#  ETAPA 5 — Enviar e-mail
# ════════════════════════════════════════════════════════════

def enviar_email(html, avisos, data_hoje):
    total   = len(avisos)
    assunto = f"[Licitações {MUNICIPIO}] {total} aviso(s) — {data_hoje.strftime('%d/%m/%Y')}"
    print(f"📧 Enviando para {len(DESTINATARIOS)} destinatário(s)...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        for nome, ende in DESTINATARIOS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = assunto
            msg["From"]    = f"Monitor Licitações AMUPE <{GMAIL_USER}>"
            msg["To"]      = ende
            msg.attach(MIMEText(html, "html", "utf-8"))
            smtp.sendmail(GMAIL_USER, ende, msg.as_string())
            print(f"   ✅ Enviado para {nome} <{ende}>")

# ════════════════════════════════════════════════════════════
#  EXECUÇÃO
# ════════════════════════════════════════════════════════════

def main():
    data_hoje = date.today()
    print("\n" + "═"*52)
    print(f"  Monitor AMUPE · {MUNICIPIO} · {data_hoje.strftime('%d/%m/%Y')}")
    print(f"  VERSÃO 5.0")
    print("═"*52 + "\n")
    caminho = baixar_pdf_do_dia()
    texto   = extrair_texto_pdf(caminho)
    avisos  = analisar_com_ia(texto)
    html    = montar_email_html(avisos, data_hoje)
    enviar_email(html, avisos, data_hoje)
    print("\n✅ Concluído!")

if __name__ == "__main__":
    main()
