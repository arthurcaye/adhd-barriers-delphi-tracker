#!/usr/bin/env python3
"""
Onde exatamente as pessoas param o questionario?

Motivo: relato de que a survey "trava no meio do caminho" para gente na
Australia. Duas explicacoes possiveis, e elas se distinguem pelo formato da
curva de abandono:

  - CANSACO  -> queda suave e continua ao longo das paginas
  - FALHA    -> despenca numa pagina especifica, ou tem um pico perto do fim
                (gente que respondeu quase tudo e mesmo assim ficou incompleta)

O script reconstroi as paginas do jeito que o REDCap monta (uma pagina por
section header, porque question_by_section=1), descobre em qual pagina cada
resposta incompleta parou, e compara Australia/Nova Zelandia com o resto.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 diagnostico_travamento.py

Gera:
  travamento_resumo.txt    so contagens, sem dado pessoal
  travamento_australia.csv lista dos incompletos de AU/NZ (TEM e-mail: nao versionar)
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
        sys.exit("ERRO: arquivo .env nao encontrado em " + HERE)
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carrega_env()

import json  # noqa: E402
import redcap_aggregate as ag  # noqa: E402

RESUMO = os.path.join(HERE, "travamento_resumo.txt")
AU_CSV = os.path.join(HERE, "travamento_australia.csv")

# prefixo -> (campo de e-mail, campo de nome, campo de pais)
FONTES = {
    "delphi_round1_en":      ("en",   "id_email",   "en_name",   "en_bg_countries"),
    "delphi_round1_ptbr":    ("ptbr", "ptbt_email", "ptbt_nome", "ptbr_bg_countries"),
    "delphi_round1_spanish": ("es",   "es_email",   "es_name",   "es_q6_countries"),
    "delphi_round1_fr":      ("fr",   "fr_email",   "fr_name",   "fr_bg_countries"),
    "delphi_round1_ar":      ("ar",   "ar_email",   "ar_name",   "ar_bg_countries"),
    "delphi_round1_it":      ("it",   "it_email",   "it_name",   "it_bg_countries"),
    "delphi_round1_zh":      ("zh",   "zh_email",   "zh_name",   "zh_bg_countries"),
    "delphi_round1_zh_cn":   ("zhcn", "zhcn_email", "zhcn_name", "zhcn_bg_countries"),
    "delphi_round1_de":      ("de",   "de_email",   "de_name",   "de_bg_countries"),
    "delphi_round1_ja":      ("ja",   "ja_email",   "ja_name",   "ja_bg_countries"),
}

OCEANIA = {"australia", "new zealand", "aotearoa", "nz", "aus", "oz"}


def monta_paginas(meta):
    """Uma pagina por section header, que e como o REDCap pagina a survey."""
    paginas = defaultdict(list)   # form -> [(titulo, [campos preenchiveis])]
    for form in {f["form_name"] for f in meta}:
        campos = [f for f in meta if f["form_name"] == form]
        titulo, atual = "(inicio)", []
        for f in campos:
            if f.get("section_header", "").strip():
                paginas[form].append((titulo, atual))
                titulo = re.sub(r"<[^>]+>", " ", f["section_header"])
                titulo = re.sub(r"\s+", " ", titulo).strip()[:52]
                atual = []
            if f["field_type"] != "descriptive":
                atual.append(f["field_name"])
        paginas[form].append((titulo, atual))
    return paginas


def pagina_de_cada_campo(paginas_do_form):
    """campo -> (indice da pagina, titulo da pagina)"""
    mapa = {}
    for i, (titulo, campos) in enumerate(paginas_do_form):
        for c in campos:
            mapa[c] = (i, titulo)
    return mapa


def preenchido(rec, campo):
    """Checkbox vem como campo___codigo; os demais, direto."""
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def main():
    print("lendo estrutura do questionario...")
    meta = ag.api({"content": "metadata"})
    paginas = monta_paginas(meta)

    campos_por_form = defaultdict(list)
    for f in meta:
        if f["field_type"] != "descriptive":
            campos_por_form[f["form_name"]].append(f["field_name"])

    pedidos = {"record_id"}
    for form, (_, email, nome, pais) in FONTES.items():
        pedidos |= {email, nome, pais, f"{form}_complete"}
        pedidos |= set(campos_por_form.get(form, []))

    print(f"consultando {len(pedidos)} campos no REDCap...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros recebidos\n")

    aliases = {}
    cfg = os.path.join(HERE, "config.json")
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as fh:
            aliases = json.load(fh).get("country_aliases", {})

    def eh_oceania(txt):
        t = str(txt or "").strip().lower()
        if not t:
            return False
        if any(p in t for p in OCEANIA):
            return True
        return str(aliases.get(str(txt).strip(), "")).lower() in {"australia", "new zealand"}

    parada_geral = Counter()        # (indice, titulo) -> n
    parada_oceania = Counter()
    por_form = Counter()
    completos = Counter()
    au_lista = []
    total_incompletos = 0

    for rec in registros:
        usado = None
        for form, (pref, email, nome, pais) in FONTES.items():
            marcas = [rec.get(email), rec.get(nome), rec.get(f"{pref}_consent_agree")]
            if any(str(x).strip() for x in marcas if x is not None):
                usado = form
                break
            if any(preenchido(rec, c) for c in campos_por_form.get(form, [])[:40]):
                usado = form
                break
        if not usado:
            continue

        pref, f_email, f_nome, f_pais = FONTES[usado]
        por_form[pref] += 1

        if str(rec.get(f"{usado}_complete", "")).strip() == "2":
            completos[pref] += 1
            continue

        total_incompletos += 1

        mapa = pagina_de_cada_campo(paginas.get(usado, []))
        ultima = None
        for campo in campos_por_form.get(usado, []):
            if preenchido(rec, campo) and campo in mapa:
                ultima = mapa[campo]
        if ultima is None:
            ultima = (-1, "(nao respondeu nada)")

        parada_geral[ultima] += 1
        if eh_oceania(rec.get(f_pais)):
            parada_oceania[ultima] += 1
            au_lista.append({
                "record_id": rec.get("record_id", ""),
                "idioma": pref,
                "pais_digitado": str(rec.get(f_pais, "")).strip(),
                "parou_na_pagina": ultima[0] + 1,
                "titulo_da_pagina": ultima[1],
                "email": str(rec.get(f_email, "")).strip(),
            })

    L = []
    L.append("ONDE O QUESTIONARIO PARA — diagnostico de travamento")
    L.append("")
    L.append(f"  registros que abriram algum instrumento : {sum(por_form.values())}")
    L.append(f"  completos                               : {sum(completos.values())}")
    L.append(f"  incompletos                             : {total_incompletos}")
    L.append("")
    L.append("CURVA DE ABANDONO — todos os idiomas, por pagina do questionario")
    L.append("(queda suave = cansaco | despencada numa pagina so = falha tecnica)")
    L.append("")
    maior = max(parada_geral.values()) if parada_geral else 1
    for (idx, titulo), n in sorted(parada_geral.items()):
        barra = "#" * max(1, round(40 * n / maior))
        L.append(f"  pag {idx+1:>3} | {n:>5} {barra}  {titulo}")
    L.append("")
    L.append("SO AUSTRALIA / NOVA ZELANDIA")
    L.append("")
    if parada_oceania:
        for (idx, titulo), n in sorted(parada_oceania.items()):
            L.append(f"  pag {idx+1:>3} | {n:>5}  {titulo}")
        L.append("")
        L.append(f"  total de incompletos em AU/NZ: {sum(parada_oceania.values())}")
    else:
        L.append("  nenhum incompleto identificado com pais AU/NZ")
    L.append("")
    L.append("POR IDIOMA (abriram / completos / % completude)")
    L.append("")
    for pref, n in sorted(por_form.items(), key=lambda x: -x[1]):
        c = completos.get(pref, 0)
        L.append(f"  {pref:<6} {n:>6} {c:>8}   {100*c/n if n else 0:5.1f}%")

    with open(RESUMO, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    if au_lista:
        with open(AU_CSV, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(au_lista[0].keys()))
            wr.writeheader()
            wr.writerows(sorted(au_lista, key=lambda x: -x["parou_na_pagina"]))

    print("\n".join(L))
    print(f"\nresumo   -> {os.path.basename(RESUMO)}")
    if au_lista:
        print(f"AU/NZ    -> {os.path.basename(AU_CSV)}  ({len(au_lista)} pessoas, tem e-mail: nao versione)")


if __name__ == "__main__":
    main()
