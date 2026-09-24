#!/usr/bin/env python3
"""
Delphi ADHD Barriers — REDCap aggregator.

Pulls records from REDCap via the API and writes an AGGREGATE-ONLY data.json
(counts by country x stakeholder category). No row-level or personal data ever
leaves this script.

The project has six parallel instruments (one per language) with DIFFERENT
option codes, so every source is read with its own code map — see config.json.

Usage
-----
  ./run.sh --discover    lista os campos
  ./run.sh --dump        salva o dicionario completo em metadata.json
  ./run.sh               gera o data.json
"""

import argparse
import http.client
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
OUTPUT_PATH = os.path.join(HERE, "data.json")
UNMAPPED_PATH = os.path.join(HERE, "paises_nao_reconhecidos.txt")
IGNORADOS_PATH = os.path.join(HERE, "paises_ignorados.json")
NOVOS_PATH = os.path.join(HERE, "paises_nao_triados.txt")

REGIONAL_MARKER = "— resposta regional, sem país —"

COUNTRY_HINTS = ("country", "pais", "país", "pays", "nation", "countries")
CATEGORY_HINTS = ("stakeholder", "category", "categoria", "role", "expertise",
                  "profession", "respondent", "perfil")

CERT_HELP = """
ERRO de certificado SSL.

Isto e um problema conhecido do Python instalado pelo python.org no macOS:
ele usa um conjunto proprio de certificados que vem vazio ate voce roda-lo uma vez.
Nao tem relacao com o token nem com o REDCap.

Correcao (uma vez so), no Terminal:

    open "/Applications/Python {ver}/Install Certificates.command"

Alternativa: pip3 install --upgrade certifi
"""


# --------------------------------------------------------------------------- API

def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def api(payload, tentativas=4):
    """Chamada ao REDCap, com repeticao em falha de transporte.

    O dicionario de dados ja passa de 16 MB e o servidor as vezes corta a
    resposta no meio (IncompleteRead). Nao e erro de token nem de parametro:
    e a conexao caindo com o corpo pela metade. Sem repeticao, o script morre
    e o trabalho inteiro se perde - foi o que aconteceu em 22/09/2026.

    Repetimos so o que faz sentido repetir. Erro de permissao ou de parametro
    (4xx) nao melhora tentando de novo, entao esses param na hora.
    """
    url = os.environ.get("REDCAP_API_URL", "").strip()
    token = os.environ.get("REDCAP_API_TOKEN", "").strip()
    if not url or not token:
        sys.exit("ERRO: defina REDCAP_API_URL e REDCAP_API_TOKEN no arquivo .env")

    body = dict(payload)
    body["token"] = token
    body.setdefault("format", "json")
    body.setdefault("returnFormat", "json")

    data = urllib.parse.urlencode(body).encode()

    espera = 3
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, context=ssl_context(), timeout=300) as resp:
                raw = resp.read().decode("utf-8")
            break
        except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                ConnectionError, TimeoutError) as err:
            if tentativa == tentativas:
                sys.exit(f"ERRO de transporte apos {tentativas} tentativas: "
                         f"{type(err).__name__}: {err}\n"
                         f"O dicionario ja passa de 16 MB; se isto virar rotina, "
                         f"vale pedir os campos em lotes.")
            print(f"  conexao caiu ({type(err).__name__}), "
                  f"tentando de novo em {espera}s "
                  f"[{tentativa}/{tentativas - 1}]")
            time.sleep(espera)
            espera *= 2
            continue
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:400]
            if err.code == 403:
                sys.exit(
                    "ERRO 403: o REDCap recusou o token.\n"
                    "  - confira se o token no .env esta completo e sem espacos\n"
                    "  - confira se o usuario tem permissao de API Export neste projeto\n"
                    "  - alguns REDCaps restringem a API por IP\n"
                    f"Resposta: {detail}"
                )
            sys.exit(f"ERRO HTTP {err.code} do REDCap:\n{detail}")
        except urllib.error.URLError as err:
            reason = getattr(err, "reason", err)
            if isinstance(reason, ssl.SSLCertVerificationError):
                sys.exit(CERT_HELP.format(ver="%d.%d" % sys.version_info[:2]))
            # URLError tambem embrulha queda de conexao; se ainda ha tentativa,
            # vale repetir em vez de desistir.
            if tentativa < tentativas and isinstance(reason, (OSError, TimeoutError)):
                print(f"  conexao caiu ({reason}), tentando de novo em {espera}s "
                      f"[{tentativa}/{tentativas - 1}]")
                time.sleep(espera)
                espera *= 2
                continue
            sys.exit(f"ERRO de conexao com {url}\n  {reason}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        sys.exit("ERRO: resposta inesperada do REDCap:\n" + raw[:1000])


# ------------------------------------------------------------------ exploracao

def discover():
    meta = api({"content": "metadata"})
    print(f"\n{len(meta)} campos no dicionario de dados.\n")

    def flag(name, label):
        text = (name + " " + label).lower()
        if any(h in text for h in COUNTRY_HINTS):
            return "  <-- possivel PAIS"
        if any(h in text for h in CATEGORY_HINTS):
            return "  <-- possivel CATEGORIA"
        return ""

    for f in meta:
        name = f.get("field_name", "")
        label = (f.get("field_label", "") or "").replace("\n", " ")[:70]
        print(f"  {name:<34} {f.get('field_type',''):<12} {label}{flag(name, label)}")


def dump():
    meta = api({"content": "metadata"})
    instruments = api({"content": "instrument"})
    path = os.path.join(HERE, "metadata.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"metadata": meta, "instruments": instruments}, fh,
                  ensure_ascii=False, indent=1)
    print(f"OK  {len(meta)} campos e {len(instruments)} instrumentos -> {path}")
    print("    (so o dicionario de dados; nenhuma resposta de participante)")


def list_records():
    """Grava uma lista local dos registros para voce marcar quais sao teste."""
    cfg = load_config()
    sources = cfg["sources"]
    fields = ["record_id"]
    for src in sources:
        fields += [src["country_field"], src["category_field"]]
        if src.get("email_field"):
            fields.append(src["email_field"])
        if src.get("complete_field"):
            fields.append(src["complete_field"])

    records = api({"content": "record", "type": "flat", "rawOrLabel": "raw",
                   "exportSurveyFields": "true",
                   "fields": ",".join(sorted(set(fields)))})

    path = os.path.join(HERE, "registros.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Lista local para identificar registros de teste.\n")
        fh.write("Copie os record_id dos testes para exclude_record_ids no config.json.\n")
        fh.write("Este arquivo NAO e publicado - fica so na sua maquina.\n\n")
        fh.write(f"{'record':<10} {'idioma':<7} {'compl':<6} {'quando':<18} "
                 f"{'e-mail':<36} pais\n")
        fh.write("-" * 120 + "\n")
        for rec in records:
            rid = rec.get("record_id", "?")
            for src in sources:
                country = (rec.get(src["country_field"]) or "").strip()
                email = (rec.get(src.get("email_field", "")) or "").strip()
                comp = str(rec.get(src.get("complete_field", ""), ""))
                when = str(rec.get(src["form"] + "_timestamp", "") or "")[:16]
                if not country and not email:
                    continue
                fh.write(f"{rid:<10} {src['lang']:<7} {comp:<6} {when:<18} "
                         f"{email[:34]:<36} {country[:40]}\n")
    print(f"OK  {len(records)} registros -> {path}")
    print("    marque os testes e liste os record_id em exclude_record_ids no config.json")


# ------------------------------------------------------------------- normaliza

SPLIT_RE = re.compile(
    r"\s*(?:[,;/|&+]|\band\b|\be\b|\by\b|\bet\b|\bو\b|、|，|und)\s*"
    # quebra de linha: gente digita um pais por linha na caixa de texto
    r"|\s*[\r\n]+\s*"
    # espaco ideografico (U+3000): separa "日本　Japan"
    r"|\s*　\s*"
    # espaco comum APENAS entre dois ideogramas: separa "台灣 美國" sem
    # quebrar "United States" nem "South Africa"
    r"|(?<=[一-鿿])\s+(?=[一-鿿])",
    re.IGNORECASE,
)


def strip_accents(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def country_key(raw):
    """Chave de comparacao: minusculas, sem acento, sem pontuacao.

    Precisa preservar arabe e chines — filtrar por [a-z] colapsaria todos os
    nomes em escrita nao-latina numa chave vazia, misturando paises diferentes.
    """
    key = strip_accents(raw or "").lower()
    key = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in key)
    return " ".join(key.split())


# Numeracao de lista no inicio do texto: "1. Republica Dominicana", "2) Peru",
# "3 - Chile". Aparece quando a pessoa lista varios paises um por linha e
# numera. O split por quebra de linha separa as linhas, mas o numero fica
# colado no nome e o alias nunca casa. Nenhum pais comeca com digito, entao
# retirar a numeracao e seguro.
ENUM_RE = re.compile(r"^\s*\d{1,2}\s*[.)\]\-–—:]\s*")

# Paises cujo nome CONTEM uma das conjuncoes que usamos como separador.
# Sem isto, "Bosnia and Herzegovina" vira dois paises inexistentes, e o
# mesmo vale para "Trinidad and Tobago", "Antigua y Barbuda" etc. Sao
# poucos e conhecidos, entao a lista e fechada. Os pares estao sem acento
# e em minusculas porque a busca e feita sobre o texto dobrado.
PARES_PROTEGIDOS = [
    ("bosnia", "herzegovina"), ("bosnie", "herzegovine"),
    ("bosnien", "herzegowina"), ("bosnia", "hercegovina"),
    ("trinidad", "tobago"), ("trinite", "tobago"), ("trindade", "tobago"),
    ("antigua", "barbuda"), ("antiga", "barbuda"),
    ("saint kitts", "nevis"), ("st kitts", "nevis"),
    ("san cristobal", "nieves"),
    ("saint vincent", "the grenadines"), ("saint vincent", "grenadines"),
    ("san vicente", "las granadinas"), ("san vicente", "granadinas"),
    ("sao tome", "principe"), ("santo tome", "principe"),
    ("turks", "caicos"),
    ("papua", "new guinea"),
]
_CONJ = r"\s*(?:and|y|e|et|und|&|,|-|–|—)\s*"
PROTEGIDOS_RE = [re.compile(a + _CONJ + b, re.IGNORECASE)
                 for a, b in PARES_PROTEGIDOS]


def _dobra(texto):
    """Minusculas sem acento PRESERVANDO o comprimento.

    strip_accents usa NFKD e pode mudar o numero de caracteres, o que
    desalinharia os indices. Aqui cada caractere vira exatamente um.
    """
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in texto).lower()


def split_countries(raw):
    """O campo e texto livre e pede 'o pais ou paises'. Devolve a lista."""
    texto = raw or ""
    # protege os nomes compostos trocando-os por um marcador sem separadores
    guardados = []
    dobrado = _dobra(texto)
    for rx in PROTEGIDOS_RE:
        for m in reversed(list(rx.finditer(dobrado))):
            i, f = m.span()
            guardados.append(texto[i:f])
            marca = "\x00%d\x00" % (len(guardados) - 1)
            texto = texto[:i] + marca + texto[f:]
            dobrado = dobrado[:i] + marca + dobrado[f:]

    partes = [ENUM_RE.sub("", p).strip(" .\t") for p in SPLIT_RE.split(texto)]

    def devolve(p):
        return re.sub(r"\x00(\d+)\x00",
                      lambda m: guardados[int(m.group(1))], p)

    return [devolve(p) for p in partes if len(p) > 1]


# ccTLDs mais provaveis neste estudo. Fica de fora .com/.org/.net/.edu porque
# nao dizem nada sobre o pais de quem responde.
CCTLD = {
    "br": "Brazil", "pt": "Portugal", "es": "Spain", "fr": "France", "it": "Italy",
    "de": "Germany", "nl": "Netherlands", "be": "Belgium", "ch": "Switzerland",
    "at": "Austria", "se": "Sweden", "no": "Norway", "dk": "Denmark", "fi": "Finland",
    "uk": "United Kingdom", "ie": "Ireland", "pl": "Poland", "cz": "Czech Republic",
    "sk": "Slovakia", "si": "Slovenia", "hr": "Croatia", "rs": "Serbia", "ba": "Bosnia and Herzegovina",
    "mk": "North Macedonia", "ro": "Romania", "bg": "Bulgaria", "hu": "Hungary",
    "gr": "Greece", "tr": "Turkey", "ru": "Russia", "ua": "Ukraine", "ee": "Estonia",
    "lt": "Lithuania", "lv": "Latvia", "ge": "Georgia", "is": "Iceland",
    "ca": "Canada", "mx": "Mexico", "ar": "Argentina", "cl": "Chile", "co": "Colombia",
    "pe": "Peru", "uy": "Uruguay", "py": "Paraguay", "bo": "Bolivia", "ve": "Venezuela",
    "ec": "Ecuador", "cr": "Costa Rica", "gt": "Guatemala", "hn": "Honduras",
    "sv": "El Salvador", "pa": "Panama", "do": "Dominican Republic", "cu": "Cuba",
    "au": "Australia", "nz": "New Zealand", "jp": "Japan", "kr": "South Korea",
    "cn": "China", "tw": "Taiwan", "hk": "Hong Kong", "sg": "Singapore", "my": "Malaysia",
    "th": "Thailand", "vn": "Vietnam", "id": "Indonesia", "ph": "Philippines",
    "in": "India", "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka", "np": "Nepal",
    "af": "Afghanistan", "ir": "Iran", "iq": "Iraq", "il": "Israel", "sa": "Saudi Arabia",
    "ae": "United Arab Emirates", "qa": "Qatar", "kw": "Kuwait", "om": "Oman",
    "jo": "Jordan", "lb": "Lebanon", "eg": "Egypt", "ma": "Morocco", "dz": "Algeria",
    "tn": "Tunisia", "sd": "Sudan", "ng": "Nigeria", "gh": "Ghana", "ke": "Kenya",
    "tz": "Tanzania", "ug": "Uganda", "za": "South Africa", "zw": "Zimbabwe",
    "mw": "Malawi", "zm": "Zambia", "mz": "Mozambique", "ao": "Angola", "sn": "Senegal",
    "et": "Ethiopia", "rw": "Rwanda", "cm": "Cameroon", "kh": "Cambodia", "dj": "Djibouti",
}


def country_from_email(email):
    """Palpite a partir do dominio do e-mail. So ccTLD — nunca busca externa."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1]
    parts = domain.split(".")
    if len(parts) < 2:
        return None
    return CCTLD.get(parts[-1])


# -------------------------------------------------------------------- agregacao

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit("ERRO: config.json nao encontrado.")
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--records", action="store_true",
                        help="lista os registros num arquivo local para achar os testes")
    args = parser.parse_args()

    if args.discover:
        return discover()
    if args.dump:
        return dump()
    if args.records:
        return list_records()

    cfg = load_config()
    sources = cfg["sources"]
    categories = list(cfg["categories"])
    targets = cfg.get("targets", {})
    only_complete = cfg.get("only_complete", True)
    min_cell = int(cfg.get("suppress_cells_below", 0))
    infer_from_email = bool(cfg.get("infer_country_from_email", False))
    inferred_log = []
    drop_ids = {str(x) for x in cfg.get("exclude_record_ids", [])}
    require_known = bool(cfg.get("require_known_country", True))
    cutoff = str(cfg.get("exclude_before", "") or "")
    drop_mails = {str(x).strip().lower() for x in cfg.get("exclude_emails", [])}
    # e-mails de teste vem por variavel de ambiente para nao ficarem num repo publico
    drop_mails |= {e.strip().lower()
                   for e in os.environ.get("EXCLUDE_EMAILS", "").split(",") if e.strip()}
    excluded = [0]

    alias = {country_key(k): v for k, v in cfg.get("country_aliases", {}).items()}

    fields = ["record_id"]
    for src in sources:
        fields += [src["country_field"], src["category_field"]]
        if src.get("email_field"):
            fields.append(src["email_field"])
        if src.get("complete_field"):
            fields.append(src["complete_field"])

    records = api({
        "content": "record",
        "type": "flat",
        "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(set(fields))),
    })

    matrix = defaultdict(Counter)
    per_country_total = Counter()
    per_category_total = Counter()
    per_language = Counter()
    unknown_countries = Counter()
    total = 0
    inferred_count = [0]
    skipped_incomplete = 0
    skipped_no_country = 0

    for rec in records:
        if str(rec.get("record_id", "")) in drop_ids:
            excluded[0] += 1
            continue
        if drop_mails:
            mails = {str(rec.get(s2.get("email_field"), "")).strip().lower()
                     for s2 in sources if s2.get("email_field")}
            if mails & drop_mails:
                excluded[0] += 1
                continue

        if cutoff:
            stamps = [str(rec.get(s2["form"] + "_timestamp", "") or "")
                      for s2 in sources]
            stamps = [t for t in stamps if t and t[0].isdigit()]
            if stamps and max(stamps) < cutoff:
                excluded[0] += 1
                continue

        for src in sources:
            cfield = src["country_field"]
            raw_country = (rec.get(cfield) or "").strip()
            cat_prefix = src["category_field"] + "___"
            ticked = [k[len(cat_prefix):] for k, v in rec.items()
                      if k.startswith(cat_prefix) and str(v) == "1"]

            if not raw_country and not ticked:
                continue  # este respondente nao usou este instrumento

            comp = src.get("complete_field")
            if only_complete and comp and str(rec.get(comp, "")) != "2":
                skipped_incomplete += 1
                continue

            inferred_here = False
            if not raw_country and infer_from_email and src.get("email_field"):
                guess = country_from_email(rec.get(src["email_field"]))
                if guess:
                    raw_country = guess
                    inferred_here = True
                    inferred_log.append((rec.get("record_id", "?"), src["lang"], guess))

            if not raw_country:
                skipped_no_country += 1
                continue

            cmap = src["category_map"]
            cats = set()
            for code in ticked:
                cats.add(cmap.get(str(code), "Other"))
            if not cats:
                cats.add("Not reported")

            countries = []
            for piece in split_countries(raw_country):
                name = alias.get(country_key(piece))
                if name is None:
                    unknown_countries[piece] += 1
                    if require_known:
                        continue          # texto nao reconhecido nao vira pais
                    name = piece.title()
                if name == REGIONAL_MARKER:
                    # "Europe", "Latin America" etc: a pessoa respondeu uma
                    # regiao, nao um pais. Nao vira linha na tabela - se ela
                    # tambem citou um pais de verdade no mesmo campo, ele ja
                    # foi capturado separadamente; se so citou a regiao, o
                    # registro fica sem pais (nao aparece no painel).
                    continue
                countries.append(name)
            countries = list(dict.fromkeys(countries))
            if not countries:
                skipped_no_country += 1
                continue

            for country in countries:
                for cat in cats:
                    matrix[country][cat] += 1
                    per_category_total[cat] += 1
                per_country_total[country] += 1

            per_language[src["lang"]] += 1
            total += 1
            if inferred_here:
                inferred_count[0] += 1

    columns = [c for c in categories]
    for extra in ("Education", "Other", "Not reported"):
        if per_category_total.get(extra) and extra not in columns:
            columns.append(extra)

    rows = []
    for country, counts in matrix.items():
        cells = {}
        for col in columns:
            n = counts.get(col, 0)
            cells[col] = 0 if (0 < n < min_cell) else n
        rows.append({"country": country, "cells": cells,
                     "total": per_country_total[country]})
    rows.sort(key=lambda r: (-r["total"], r["country"]))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "columns": columns,
        "targets": {c: targets.get(c) for c in columns},
        "rows": rows,
        "totals": {
            "responses": total,
            "countries": len(rows),
            "by_category": {c: per_category_total.get(c, 0) for c in columns},
            "by_language": dict(per_language),
        },
        "notes": {
            "only_complete": bool(only_complete),
            "skipped_incomplete": skipped_incomplete,
            "skipped_no_country": skipped_no_country,
            "suppress_cells_below": min_cell,
            "inferred_from_email": inferred_count[0],
            "excluded_records": excluded[0],
        },
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print(f"OK  {total} respostas | {len(rows)} paises -> {OUTPUT_PATH}")
    print(f"    por idioma: {dict(per_language)}")
    if skipped_incomplete:
        print(f"    {skipped_incomplete} respostas incompletas ignoradas")
    if skipped_no_country:
        print(f"    {skipped_no_country} respostas sem pais informado")
    if excluded[0]:
        print(f"    {excluded[0]} registros excluidos (testes/config)")

    if inferred_log:
        path = os.path.join(HERE, "paises_inferidos.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Paises deduzidos do dominio do e-mail porque o campo de pais\n")
            fh.write("veio vazio. Sao palpites - revise antes de usar no artigo.\n\n")
            for rid, lang, guess in inferred_log:
                fh.write(f"  record {rid:<8} ({lang})  ->  {guess}\n")
        print(f"    {len(inferred_log)} paises inferidos pelo e-mail -> "
              f"{os.path.basename(path)}")

    if unknown_countries:
        with open(UNMAPPED_PATH, "w", encoding="utf-8") as fh:
            fh.write("Textos de pais que nao estao no country_aliases do config.json.\n")
            fh.write("Foram usados como vieram (com a primeira letra maiuscula).\n")
            fh.write("Adicione os que precisarem de correcao ao config.json.\n\n")
            for name, n in unknown_countries.most_common():
                fh.write(f"{n:>5}  {name}\n")
        print(f"    {len(unknown_countries)} grafias de pais nao reconhecidas -> "
              f"{os.path.basename(UNMAPPED_PATH)}")

    # ---------------------------------------------------------------- alarme
    # Este arquivo ja existia e ja listava "Hong Kong SAR" havia dias. Ninguem
    # abriu, porque nada pedia que abrisse, e 26 respostas completas ficaram
    # fora da contagem ate um painelista reclamar. Registrar em silencio nao e
    # o mesmo que avisar.
    ignorados = set()
    if os.path.exists(IGNORADOS_PATH):
        try:
            with open(IGNORADOS_PATH, encoding="utf-8") as fh:
                ignorados = {country_key(k)
                             for k in json.load(fh).get("ignorados", {})}
        except (json.JSONDecodeError, OSError):
            pass

    novos = {nome: n for nome, n in unknown_countries.items()
             if country_key(nome) not in ignorados}

    if novos:
        with open(NOVOS_PATH, "w", encoding="utf-8") as fh:
            fh.write("TEXTO DE PAIS NAO RECONHECIDO E AINDA NAO TRIADO\n\n")
            fh.write("Cada linha abaixo e uma ou mais respostas COMPLETAS que\n")
            fh.write("nao estao entrando na contagem por pais do painel.\n\n")
            for nome, n in sorted(novos.items(), key=lambda x: -x[1]):
                fh.write(f"{n:>5}  {nome}\n")
            fh.write("\nO que fazer com cada uma:\n")
            fh.write("  e pais escrito de outro jeito -> country_aliases "
                     "no config.json\n")
            fh.write("  nao e pais                    -> paises_ignorados.json\n")
        perdidas = sum(novos.values())
        print()
        print("  " + "!" * 62)
        print(f"  {len(novos)} TEXTO(S) DE PAIS NAO RECONHECIDO, "
              f"{perdidas} resposta(s) fora da contagem")
        for nome, n in sorted(novos.items(), key=lambda x: -x[1])[:8]:
            print(f"     {n:>3}x  {nome[:52]}")
        print(f"  detalhe em {os.path.basename(NOVOS_PATH)}")
        print("  " + "!" * 62)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=Pais nao reconhecido::{len(novos)} grafia(s) "
                  f"nova(s), {perdidas} resposta(s) fora da contagem")
    elif os.path.exists(NOVOS_PATH):
        os.remove(NOVOS_PATH)


if __name__ == "__main__":
    main()
