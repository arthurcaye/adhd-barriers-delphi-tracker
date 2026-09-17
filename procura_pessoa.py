#!/usr/bin/env python3
"""
Procura uma pessoa em todos os instrumentos, por nome ou por e-mail.

Serve para dois usos:
  - conferir o status de quem escreve dizendo "eu respondi" (e a promessa que
    fizemos ao painel coreano: confirmar participante a participante)
  - achar o SEGUNDO registro de alguem que recomecou o questionario em outra
    sessao, que nao aparece na busca por e-mail quando o endereco foi outro

Busca em todos os campos de nome e de e-mail dos onze instrumentos, sem
diferenciar maiusculas, aceitando pedaco do texto.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 procura_pessoa.py "오윤혜"
  python3 procura_pessoa.py "yunhye"
  python3 procura_pessoa.py "@snu.ac.kr"
"""

import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def carrega_env():
    caminho = os.path.join(HERE, ".env")
    if not os.path.exists(caminho):
        sys.exit("ERRO: arquivo .env nao encontrado em " + HERE)
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carrega_env()

import redcap_aggregate as ag  # noqa: E402

ADMIN = {"par_code"}


def preenchido(rec, campo):
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def main():
    if len(sys.argv) < 2:
        sys.exit('uso: python3 procura_pessoa.py "nome ou pedaco do e-mail"')
    alvo = sys.argv[1].strip().lower()

    meta = ag.api({"content": "metadata"})

    ordem = defaultdict(list)
    ident = defaultdict(list)      # form -> campos de nome/e-mail
    trio = defaultdict(lambda: defaultdict(dict))
    pais_de = {}
    for f in meta:
        form, fn = f["form_name"], f["field_name"]
        if not form.startswith("delphi_round1"):
            continue
        if f["field_type"] != "descriptive" and fn not in ADMIN:
            ordem[form].append(fn)
        if re.search(r"(_name|_nome|_email)$", fn):
            ident[form].append(fn)
        if fn.endswith("_countries"):
            pais_de[form] = fn
        m = re.search(r"_(b\d+[a-z]?)_", fn)
        if m:
            for papel, padrao in zip(("imp", "feas", "rec"),
                                     (r"_(imp|importance)$", r"_(feas|feasibility)$",
                                      r"_(rec|recommendation)$")):
                if re.search(padrao, fn):
                    trio[form][m.group(1)][papel] = fn

    forms = list(ordem)
    pedidos = {"record_id"}
    for form in forms:
        pedidos |= set(ordem[form]) | {f"{form}_complete"}

    print(f"procurando por {alvo!r} em {len(forms)} instrumentos...\n")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })

    achados = 0
    for rec in registros:
        casou = []
        for form in forms:
            for c in ident[form]:
                v = str(rec.get(c, "") or "").strip()
                if v and alvo in v.lower():
                    casou.append((form, c, v))
        if not casou:
            continue
        achados += 1
        form = casou[0][0]
        st = str(rec.get(f"{form}_complete", "")).strip()
        ts = str(rec.get(f"{form}_timestamp", "")).strip()
        barreiras = trio.get(form, {})
        cheias = sum(1 for b, p in barreiras.items()
                     if len(p) == 3 and all(preenchido(rec, c) for c in p.values()))
        so_imp = sum(1 for b, p in barreiras.items()
                     if "imp" in p and preenchido(rec, p["imp"]))
        cheios = [c for c in ordem[form] if preenchido(rec, c)]

        estado = {"2": "COMPLETA", "1": "nao verificada", "0": "incompleta"}.get(st, st or "?")
        print(f"--- registro {rec.get('record_id')} | {form} | {estado} ---")
        for _, campo, valor in casou:
            print(f"    casou em {campo}: {valor}")
        print(f"    pais            : {str(rec.get(pais_de.get(form,''),'') or '(vazio)').strip()}")
        print(f"    barreiras       : {cheias}/{len(barreiras)} com o trio completo"
              f"   ({so_imp} com importancia)")
        print(f"    timestamp       : {ts or '(vazio)'}")
        print(f"    ultimo campo    : {cheios[-1] if cheios else '(nenhum)'}")
        if st != "2" and barreiras and cheias >= 0.9 * len(barreiras):
            print("    >>> respondeu tudo e nao foi finalizada: RECUPERAVEL")
        print()

    if not achados:
        print("nenhum registro encontrado com esse texto.")
        print("tente so o sobrenome, o nome em coreano, ou o dominio do e-mail.")
    else:
        print(f"total: {achados} registro(s)")
        if achados > 1:
            print("mais de um registro: provavel que a pessoa tenha recomecado"
                  " o questionario numa segunda sessao.")


if __name__ == "__main__":
    main()
