#!/usr/bin/env python3
"""
Analise de abandono do painel Delphi.

Responde: de todos os registros, quantos sao pessoas realmente abordaveis —
isto e, consentiram, deixaram e-mail e nao terminaram — e em que ponto do
questionario elas pararam.

Gera dois arquivos:
  abandono_resumo.txt    so contagens, nenhum dado pessoal
  abandono_contatos.csv  a lista propriamente dita, para uso local

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  ./run.sh --abandono          (se preferir: python3 analise_abandono.py)
"""

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def carrega_env():
    """Le o .env, para o script funcionar sem depender do run.sh."""
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

import redcap_aggregate as ag  # reaproveita api(), ssl, tratamento de erro

RESUMO = os.path.join(HERE, "abandono_resumo.txt")
CONTATOS = os.path.join(HERE, "abandono_contatos.csv")

# instrumento -> (prefixo dos campos, campo de e-mail, campo de nome)
FONTES = {
    "delphi_round1_en":      ("en",   "id_email",    "en_name"),
    "delphi_round1_ptbr":    ("ptbr", "ptbt_email",  "ptbt_nome"),
    "delphi_round1_spanish": ("es",   "es_email",    "es_name"),
    "delphi_round1_fr":      ("fr",   "fr_email",    "fr_name"),
    "delphi_round1_ar":      ("ar",   "ar_email",    "ar_name"),
    "delphi_round1_it":      ("it",   "it_email",    "it_name"),
    "delphi_round1_zh":      ("zh",   "zh_email",    "zh_name"),
    "delphi_round1_zh_cn":   ("zhcn", "zhcn_email",  "zhcn_name"),
    "delphi_round1_de":      ("de",   "de_email",    "de_name"),
    "delphi_round1_ja":      ("ja",   "ja_email",    "ja_name"),
    "delphi_round1_ko":      ("ko",   "ko_email",    "ko_name"),
    "delphi_round1_ru":      ("ru",   "ru_email",    "ru_name"),
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def campos_de_importancia(meta):
    """Os 51 itens de 'quao importante e esta barreira' de cada instrumento."""
    out = defaultdict(list)
    for f in meta:
        m = re.search(r"_b(\d+)[a-z]?_(imp|importance)$", f["field_name"])
        if m:
            out[f["form_name"]].append(f["field_name"])
    for k in out:
        out[k].sort()
    return out


def main():
    meta = ag.api({"content": "metadata"})
    itens = campos_de_importancia(meta)

    pedidos = ["record_id", "survey_language"]
    for form, (pref, email, nome) in FONTES.items():
        pedidos += [email, nome, f"{pref}_consent_agree", f"{form}_complete"]
        pedidos += itens.get(form, [])

    print(f"consultando {len(set(pedidos))} campos no REDCap...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(set(pedidos))),
    })
    print(f"{len(registros)} registros recebidos\n")

    funil = Counter()
    por_idioma = defaultdict(Counter)
    parada = Counter()
    contataveis = []

    for rec in registros:
        funil["registros"] += 1

        # qual instrumento a pessoa usou: aquele em que ela deixou algum rastro
        usado = None
        for form, (pref, email, nome) in FONTES.items():
            marcas = [rec.get(email), rec.get(nome), rec.get(f"{pref}_consent_agree")]
            marcas += [rec.get(c) for c in itens.get(form, [])]
            if any(str(x).strip() for x in marcas if x is not None):
                usado = form
                break
        if not usado:
            funil["abriram_e_sairam"] += 1
            continue

        funil["comecaram_algum_questionario"] += 1
        pref, f_email, f_nome = FONTES[usado]
        lang = pref
        por_idioma[lang]["comecaram"] += 1

        consent = str(rec.get(f"{pref}_consent_agree", "")).strip()
        completo = str(rec.get(f"{usado}_complete", "")).strip() == "2"
        email = str(rec.get(f_email, "")).strip()
        respondidos = sum(1 for c in itens.get(usado, []) if str(rec.get(c, "")).strip())

        if completo:
            funil["completos"] += 1
            por_idioma[lang]["completos"] += 1
            continue

        funil["incompletos"] += 1
        por_idioma[lang]["incompletos"] += 1

        if consent == "0":
            funil["incompletos_recusaram_consentimento"] += 1
            continue
        if consent != "1":
            funil["incompletos_nao_chegaram_ao_consentimento"] += 1
            continue

        funil["incompletos_com_consentimento"] += 1

        if not EMAIL_RE.match(email):
            funil["incompletos_com_consentimento_sem_email"] += 1
            continue

        funil["CONTATAVEIS"] += 1
        por_idioma[lang]["contataveis"] += 1
        faixa = ("0 itens" if respondidos == 0 else
                 "1 a 10" if respondidos <= 10 else
                 "11 a 25" if respondidos <= 25 else
                 "26 a 40" if respondidos <= 40 else
                 "41 a 50")
        parada[faixa] += 1
        contataveis.append({
            "record_id": rec.get("record_id", ""),
            "idioma": lang,
            "email": email,
            "nome": str(rec.get(f_nome, "")).strip(),
            "itens_respondidos": respondidos,
            "de_51": 51,
        })

    ordem = ["registros", "abriram_e_sairam", "comecaram_algum_questionario",
             "completos", "incompletos", "incompletos_recusaram_consentimento",
             "incompletos_nao_chegaram_ao_consentimento",
             "incompletos_com_consentimento",
             "incompletos_com_consentimento_sem_email", "CONTATAVEIS"]

    linhas = ["FUNIL DE ABANDONO — painel Delphi de barreiras", ""]
    for k in ordem:
        linhas.append(f"  {k:<46} {funil.get(k,0):>6}")
    linhas += ["", "POR IDIOMA (comecaram / completos / incompletos / contataveis)", ""]
    for lang, c in sorted(por_idioma.items(), key=lambda x: -x[1]["comecaram"]):
        linhas.append(f"  {lang:<6} {c['comecaram']:>6} {c['completos']:>8} "
                      f"{c['incompletos']:>10} {c['contataveis']:>10}")
    linhas += ["", "ONDE OS CONTATAVEIS PARARAM (de 51 itens de importancia)", ""]
    for faixa in ["0 itens", "1 a 10", "11 a 25", "26 a 40", "41 a 50"]:
        linhas.append(f"  {faixa:<12} {parada.get(faixa,0):>6}")

    with open(RESUMO, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")

    with open(CONTATOS, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["record_id", "idioma", "email",
                                            "nome", "itens_respondidos", "de_51"])
        wr.writeheader()
        for r in sorted(contataveis, key=lambda x: (-x["itens_respondidos"], x["idioma"])):
            wr.writerow(r)

    print("\n".join(linhas))
    print(f"\nresumo  -> {os.path.basename(RESUMO)}")
    print(f"contatos-> {os.path.basename(CONTATOS)}  ({len(contataveis)} pessoas)")
    print("O CSV tem nome e e-mail: fica so na sua maquina, nao versione.")


if __name__ == "__main__":
    main()
