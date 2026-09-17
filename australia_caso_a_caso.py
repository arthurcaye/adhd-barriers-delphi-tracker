#!/usr/bin/env python3
"""
Os registros da Australia / Nova Zelandia, um por um.

O relato foi "a survey trava no meio do caminho". A analise agregada nao
mostrou falha tecnica, mas ela dilui poucos casos em milhares. Aqui olhamos
caso a caso, porque sao poucos.

O sinal que interessa e a FORMA do preenchimento das 51 barreiras:

  ###########.................  prefixo limpo -> parou e nao voltou (desistencia)
  #####....####...#####.......  com buracos   -> perdeu pedaco no meio (falha)

Quem abandona por cansaco deixa um prefixo continuo. Quem perde uma pagina por
falha tecnica deixa buraco, porque o REDCap grava pagina a pagina.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 australia_caso_a_caso.py
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

SAIDA = os.path.join(HERE, "australia_caso_a_caso.txt")

TERMOS = ("australia", "austrália", "new zealand", "aotearoa", "nova zelandia",
          "nueva zelanda", "australie", "澳大利亚", "澳洲", "オーストラリア", "호주")
DOMINIOS = (".au", ".nz")

ADMIN = {"par_code"}


def preenchido(rec, campo):
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def main():
    meta = ag.api({"content": "metadata"})

    ordem = defaultdict(list)
    itens = defaultdict(list)      # form -> campos _imp, na ordem (1 por barreira)
    rotulo = {}
    campo_pais, campo_email = {}, {}
    for f in meta:
        form, fn = f["form_name"], f["field_name"]
        if not form.startswith("delphi_round1"):
            continue
        rotulo[fn] = re.sub(r"<[^>]+>", " ", f.get("field_label", ""))[:60]
        if f["field_type"] != "descriptive" and fn not in ADMIN:
            ordem[form].append(fn)
        if re.search(r"_b\d+[a-z]?_(imp|importance)$", fn):
            itens[form].append(fn)
        if fn.endswith("_countries") or fn.endswith("_bg_countries"):
            campo_pais[form] = fn
        if fn.endswith("_email") and form not in campo_email:
            campo_email[form] = fn

    forms = list(ordem)
    pedidos = {"record_id"}
    for form in forms:
        pedidos |= set(ordem[form]) | {f"{form}_complete"}

    print(f"consultando {len(pedidos)} campos...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros\n")

    L = ["REGISTROS DA AUSTRALIA / NOVA ZELANDIA, CASO A CASO", ""]
    achados = 0

    for rec in registros:
        melhor, cheios = None, []
        for form in forms:
            c = [x for x in ordem[form] if preenchido(rec, x)]
            if len(c) > len(cheios):
                melhor, cheios = form, c
        if melhor is None:
            continue

        pais = str(rec.get(campo_pais.get(melhor, ""), "") or "")
        email = str(rec.get(campo_email.get(melhor, ""), "") or "")
        por_pais = any(t in pais.lower() for t in TERMOS)
        por_email = any(email.strip().lower().endswith(d) for d in DOMINIOS)
        if not (por_pais or por_email):
            continue

        achados += 1
        st = str(rec.get(f"{melhor}_complete", "")).strip()
        ts = str(rec.get(f"{melhor}_timestamp", "")).strip()
        lista = itens.get(melhor, [])
        mapa = "".join("#" if preenchido(rec, c) else "." for c in lista)
        n = mapa.count("#")

        # buraco = algum "." antes do ultimo "#"
        ult = mapa.rfind("#")
        buracos = mapa[:ult].count(".") if ult >= 0 else 0

        L.append(f"--- registro {rec.get('record_id')} | {melhor} ---")
        L.append(f"    pais digitado : {pais.strip() or '(vazio)'}"
                 + ("   [identificado pelo dominio do e-mail]" if not por_pais else ""))
        L.append(f"    status        : complete={st or '(vazio)'}   timestamp={ts or '(vazio)'}")
        L.append(f"    barreiras     : {n} de {len(lista)} respondidas")
        L.append(f"    mapa          : {mapa}")
        if buracos:
            L.append(f"    >>> {buracos} BURACO(S) no meio do preenchimento — sinal de perda de pagina")
        else:
            L.append("    (preenchimento continuo, sem buraco)")
        L.append(f"    ultimo campo  : {cheios[-1]}")
        L.append(f"                    {rotulo.get(cheios[-1],'')}")
        L.append("")

    if not achados:
        L.append("  nenhum registro identificado como AU/NZ")
    else:
        L.append(f"total: {achados} registros")
        L.append("")
        L.append("Para comparar, a mesma leitura em quem NAO e AU/NZ e incompleto:")
        comp = {"continuo": 0, "com buraco": 0}
        for rec in registros:
            melhor, cheios = None, []
            for form in forms:
                c = [x for x in ordem[form] if preenchido(rec, x)]
                if len(c) > len(cheios):
                    melhor, cheios = form, c
            if melhor is None or str(rec.get(f"{melhor}_complete", "")).strip() == "2":
                continue
            lista = itens.get(melhor, [])
            mapa = "".join("#" if preenchido(rec, c) else "." for c in lista)
            if mapa.count("#") < 2:
                continue
            ult = mapa.rfind("#")
            comp["com buraco" if mapa[:ult].count(".") else "continuo"] += 1
        tot = sum(comp.values()) or 1
        for k, v in comp.items():
            L.append(f"  {k:<12} {v:>6}  ({100*v/tot:.1f}%)")

    with open(SAIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nsalvo em {os.path.basename(SAIDA)}  (tem pais e e-mail: nao versione)")


if __name__ == "__main__":
    main()
