"""
Script de diagnóstico — NÃO envia e-mail.
Baixa o PDF do dia, extrai o texto e mostra:
  1. Todas as linhas que mencionam "Abreu e Lima"
  2. Todas as linhas que mencionam "licitação" (qualquer variação)
  3. As 5 linhas ao redor de cada ocorrência (contexto)
Use este script para entender o que o PDF contém de verdade.
"""

import re
import requests
from bs4 import BeautifulSoup
import pdfplumber

URL_AMUPE = "https://www.diariomunicipal.com.br/amupe/"
MUNICIPIO = "ABREU E LIMA"

def baixar_pdf():
    print("📥 Baixando PDF...")
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(URL_AMUPE, headers=headers, timeout=30)
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

    print(f"   URL: {pdf_url}")
    r = requests.get(pdf_url, headers=headers, timeout=60)
    with open("/tmp/diario_diag.pdf", "wb") as f:
        f.write(r.content)
    print(f"   Tamanho: {len(r.content)//1024} KB")
    return "/tmp/diario_diag.pdf"

def extrair_texto(caminho):
    print("\n📖 Extraindo texto...")
    linhas = []
    with pdfplumber.open(caminho) as pdf:
        print(f"   Páginas: {len(pdf.pages)}")
        for i, p in enumerate(pdf.pages, 1):
            t = p.extract_text()
            if t:
                for ln in t.splitlines():
                    linhas.append((i, ln))
    print(f"   Total de linhas extraídas: {len(linhas)}")
    return linhas

def analisar(linhas):
    RE_AVISO    = re.compile(r"AVISO\s+DE\s+LICITA", re.IGNORECASE)
    RE_LICIT    = re.compile(r"licita", re.IGNORECASE)
    RE_MUNICIPIO = re.compile(re.escape(MUNICIPIO), re.IGNORECASE)

    print("\n" + "="*60)
    print("1. LINHAS COM 'AVISO DE LICITA...' (cabeçalho que a regex busca)")
    print("="*60)
    encontrou_aviso = False
    for i, (pag, ln) in enumerate(linhas):
        if RE_AVISO.search(ln):
            encontrou_aviso = True
            print(f"\n  [pág {pag}] >>> {ln.strip()}")
            # Mostra 5 linhas de contexto abaixo
            for j in range(1, 6):
                if i+j < len(linhas):
                    print(f"            +{j}: {linhas[i+j][1].strip()}")
    if not encontrou_aviso:
        print("  ⚠️  NENHUMA linha com 'AVISO DE LICITA' encontrada!")
        print("  Isso explica por que o script não encontra avisos.")

    print("\n" + "="*60)
    print("2. LINHAS QUE MENCIONAM O MUNICÍPIO (Abreu e Lima)")
    print("="*60)
    count = 0
    for pag, ln in linhas:
        if RE_MUNICIPIO.search(ln):
            count += 1
            if count <= 20:  # mostra só os primeiros 20
                print(f"  [pág {pag}] {ln.strip()}")
    print(f"  Total: {count} linha(s) mencionam '{MUNICIPIO}'")

    print("\n" + "="*60)
    print("3. PRIMEIRAS 30 LINHAS DO PDF (estrutura inicial)")
    print("="*60)
    for pag, ln in linhas[:30]:
        if ln.strip():
            print(f"  [pág {pag}] {ln.strip()}")

    print("\n" + "="*60)
    print("4. AMOSTRA DE LINHAS COM 'LICITAÇ' (qualquer contexto)")
    print("="*60)
    count2 = 0
    for i, (pag, ln) in enumerate(linhas):
        if RE_LICIT.search(ln):
            count2 += 1
            if count2 <= 15:
                print(f"  [pág {pag}] {ln.strip()}")
    print(f"  Total: {count2} linha(s) com 'licita...'")

if __name__ == "__main__":
    caminho = baixar_pdf()
    linhas  = extrair_texto(caminho)
    analisar(linhas)
    print("\n✅ Diagnóstico concluído.")
