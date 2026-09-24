#!/usr/bin/env python3
"""
Cruza uma lista de convidados contra quem ja esta no REDCap.

Nasceu da lista do New Frontiers America Latina: 535 medicos que se
inscreveram no congresso e que o Rohde quer convidar. Antes de disparar,
precisamos saber quem dessa lista ja passou pelo estudo, porque mandar
convite para quem ja respondeu e o tipo de erro que custa credibilidade
com o proprio publico que estamos tentando recrutar.

Separa a lista em quatro:
  JA COMPLETOU        nao convidar. Ja deu o trabalho todo.
  COMECOU E PAROU     nao convidar com este texto: eles nao precisam de
                      convite, precisam de retomada. Ja estao na repescagem.
  RECUSOU CONSENTIMENTO  nunca convidar. Disseram nao uma vez.
  NOVO                convidar. E para estes que o e-mail foi escrito.

Busca nos campos de e-mail dos 12 idiomas e no email_todos, porque um
medico argentino pode perfeitamente ter respondido em ingles.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 cruza_lista_convite.py ../latam/lista_new_frontiers.csv
"""

import csv
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def carrega_env():
    caminho = os.path.join(HERE, ".env")
    if not os.path.exists(caminho):
        sys.exit("ERRO: .env nao encontrado em " + HERE)
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


carrega_env()
import redcap_aggregate as ag  # noqa: E402

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

FONTES = {
    "delphi_round1_en":      ("en",   "id_email"),
    "delphi_round1_ptbr":    ("ptbr", "ptbt_email"),
    "delphi_round1_spanish": ("es",   "es_email"),
    "delphi_round1_fr":      ("fr",   "fr_email"),
    "delphi_round1_ar":      ("ar",   "ar_email"),
    "delphi_round1_it":      ("it",   "it_email"),
    "delphi_round1_zh":      ("zh",   "zh_email"),
    "delphi_round1_zh_cn":   ("zhcn", "zhcn_email"),
    "delphi_round1_de":      ("de",   "de_email"),
    "delphi_round1_ja":      ("ja",   "ja_email"),
    "delphi_round1_ko":      ("ko",   "ko_email"),
    "delphi_round1_ru":      ("ru",   "ru_email"),
}

# Le o nome real do campo no dicionario em vez de deduzi-lo: o espanhol usa
# es_b01_importance onde os outros usam es_b01_imp, e remontar o nome por
# padrao ja classificou 43 pessoas errado uma vez.
RE_IMP = re.compile(r"_b(\d+[a-z]?)_(?:imp|importance)$")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    entrada = sys.argv[1]
    if not os.path.exists(entrada):
        sys.exit(f"ERRO: nao encontrei {entrada}")

    with open(entrada, encoding="utf-8-sig") as fh:
        convidados = list(csv.DictReader(fh))
    col_email = next((c for c in convidados[0] if "mail" in c.lower()), None)
    if not col_email:
        sys.exit("ERRO: a planilha nao tem coluna de e-mail.")
    print(f"lista: {os.path.basename(entrada)}  ({len(convidados)} linhas)")

    print("consultando o REDCap...")
    meta = ag.api({"content": "metadata"})
    nomes = {f["field_name"] for f in meta}
    imp_por_form = defaultdict(dict)
    for f in meta:
        m = RE_IMP.search(f["field_name"])
        if m:
            imp_por_form[f["form_name"]][m.group(1)] = f["field_name"]

    pedidos = {"record_id"}
    if "email_todos" in nomes:
        pedidos.add("email_todos")
    for form, (pref, campo_email) in FONTES.items():
        if campo_email in nomes:
            pedidos.add(campo_email)
        pedidos.add(f"{form}_complete")
        consent = f"{pref}_consent_agree"
        if consent in nomes:
            pedidos.add(consent)
        pedidos.update(imp_por_form.get(form, {}).values())

    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros\n")

    # e-mail -> pior/melhor situacao encontrada
    situacao = {}
    for rec in registros:
        enderecos = set()
        for campo in ["email_todos"] + [c for _, c in FONTES.values()]:
            v = str(rec.get(campo, "") or "").strip().lower()
            if EMAIL_RE.fullmatch(v):
                enderecos.add(v)
        if not enderecos:
            continue

        completo = any(str(rec.get(f"{form}_complete", "") or "").strip() == "2"
                       for form in FONTES)
        recusou = any(str(rec.get(f"{pref}_consent_agree", "") or "").strip() == "0"
                      for pref, _ in [(p, c) for p, c in FONTES.values()])
        barreiras = 0
        for form in FONTES:
            barreiras += sum(
                1 for campo in imp_por_form.get(form, {}).values()
                if str(rec.get(campo, "") or "").strip())

        if completo:
            estado = "JA COMPLETOU"
        elif recusou:
            estado = "RECUSOU CONSENTIMENTO"
        elif barreiras:
            estado = "COMECOU E PAROU"
        else:
            estado = "ABRIU SEM RESPONDER"

        prioridade = {"JA COMPLETOU": 4, "RECUSOU CONSENTIMENTO": 3,
                      "COMECOU E PAROU": 2, "ABRIU SEM RESPONDER": 1}
        for e in enderecos:
            if prioridade[estado] > prioridade.get(situacao.get(e, ""), 0):
                situacao[e] = estado

    saida = []
    contagem = Counter()
    for c in convidados:
        e = str(c.get(col_email, "") or "").strip().lower()
        estado = situacao.get(e, "NOVO")
        # quem so abriu e nao respondeu nada pode receber o convite normal
        if estado == "ABRIU SEM RESPONDER":
            estado = "NOVO"
        contagem[estado] += 1
        linha = dict(c)
        linha["situacao"] = estado
        linha["convidar"] = "sim" if estado == "NOVO" else "nao"
        saida.append(linha)

    base = os.path.splitext(entrada)[0]
    campos = list(convidados[0].keys()) + ["situacao", "convidar"]
    with open(base + "_cruzado.csv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=campos)
        wr.writeheader()
        wr.writerows(saida)
    convidar = [l for l in saida if l["convidar"] == "sim"]
    with open(base + "_convidar.csv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=campos)
        wr.writeheader()
        wr.writerows(convidar)

    print("SITUACAO DOS CONVIDADOS")
    for estado in ["NOVO", "COMECOU E PAROU", "JA COMPLETOU",
                   "RECUSOU CONSENTIMENTO"]:
        n = contagem.get(estado, 0)
        marca = "  <- convidar" if estado == "NOVO" else "  <- NAO convidar"
        print(f"  {estado:<24}{n:>5}{marca if n else ''}")
    print()
    col_pais = next((c for c in convidados[0] if "pa" in c.lower()[:3]), None)
    if col_pais:
        print("A CONVIDAR, por pais:")
        for p, n in Counter(str(l.get(col_pais, "-")).strip().title()
                            for l in convidar).most_common(10):
            print(f"   {p:<24}{n:>4}")
    print()
    print(f"detalhe   -> {os.path.basename(base)}_cruzado.csv")
    print(f"a convidar-> {os.path.basename(base)}_convidar.csv  "
          f"({len(convidar)} pessoas)")
    print("\nOs dois tem e-mail: nao versione.")


if __name__ == "__main__":
    main()
