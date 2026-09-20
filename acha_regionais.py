#!/usr/bin/env python3
"""
Localiza os registros cujo texto de pais caiu no bucket
"— resposta regional, sem pais —" (ex.: "Europe", "Latin America", "Africa",
"Pays d'Europe"...) e tenta deduzir o pais real:
  1. pelo dominio do e-mail (ccTLD, mesma funcao country_from_email do agregador)
  2. mostrando o texto exato que a pessoa escreveu, para checagem manual

Nao grava nada no REDCap. So le e imprime/gera um txt local (nao versionado).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = HERE
sys.path.insert(0, DASH)


def carrega_env():
    caminho = os.path.join(DASH, ".env")
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carrega_env()
import redcap_aggregate as ag  # noqa: E402

cfg = json.load(open(os.path.join(DASH, "config.json"), encoding="utf-8"))
sources = cfg["sources"]
aliases = cfg["country_aliases"]

MARCADOR = "— resposta regional, sem país —"
regionais_raw = {k for k, v in aliases.items() if v == MARCADOR}
regionais_norm = {ag.country_key(k) for k in regionais_raw}

print(f"aliases marcados como regionais no config.json: {len(regionais_raw)}")
for r in sorted(regionais_raw):
    print(f"   {r!r}")
print()

fields = ["record_id"]
for src in sources:
    fields.append(src["country_field"])
    if src.get("email_field"):
        fields.append(src["email_field"])
    if src.get("complete_field"):
        fields.append(src["complete_field"])

registros = ag.api({
    "content": "record", "type": "flat", "rawOrLabel": "raw",
    "exportSurveyFields": "true",
    "fields": ",".join(sorted(set(fields))),
})

achados = []
for rec in registros:
    for src in sources:
        raw = (rec.get(src["country_field"]) or "").strip()
        if not raw:
            continue
        for pedaco in ag.split_countries(raw):
            if ag.country_key(pedaco) in regionais_norm:
                email = (rec.get(src.get("email_field", "")) or "").strip()
                comp = str(rec.get(src.get("complete_field", ""), ""))
                palpite = ag.country_from_email(email)
                achados.append({
                    "record_id": rec.get("record_id"),
                    "lang": src["lang"],
                    "completo": comp == "2",
                    "texto_digitado": pedaco,
                    "texto_completo_do_campo": raw,
                    "email": email,
                    "dominio": email.rsplit("@", 1)[-1] if "@" in email else "",
                    "palpite_por_email": palpite,
                })

print(f"registros com resposta regional: {len(achados)}\n")
linhas = []
for a in achados:
    linha = (f"registro {a['record_id']:<6} ({a['lang']}, "
              f"{'completo' if a['completo'] else 'incompleto'})  "
              f"digitou: {a['texto_digitado']!r}")
    if a["texto_completo_do_campo"] != a["texto_digitado"]:
        linha += f"   [campo inteiro: {a['texto_completo_do_campo']!r}]"
    linha += f"\n    e-mail: {a['email'] or '(vazio)'}"
    if a["palpite_por_email"]:
        linha += f"   ->  palpite pelo dominio: {a['palpite_por_email']}"
    else:
        linha += "   ->  dominio nao indica pais (genérico: gmail/hotmail/outlook/etc, ou vazio)"
    linhas.append(linha)
    print(linha)
    print()

out = os.path.join(HERE, "regionais_encontrados.txt")
with open(out, "w", encoding="utf-8") as fh:
    fh.write("\n\n".join(linhas) + "\n")
print(f"salvo em {out} (tem e-mail: nao versionar)")
