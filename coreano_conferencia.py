#!/usr/bin/env python3
"""
Conferencia do painel coreano + teste global de "respondeu tudo mas nao consta".

Motivado pelo relato da Dra. Yunhye Oh: pelo menos 6 membros do painel coreano
dizem ter completado a Rodada 1, o numero informado foi muito menor, e ela
propria nao recebeu o e-mail de confirmacao de conclusao.

Duas perguntas, nessa ordem:

 1) Quantas respostas coreanas existem e qual o status de cada uma?
 2) Existe gente, em qualquer idioma, que respondeu praticamente todas as 51
    barreiras e mesmo assim NAO esta marcada como completa? Esse e o teste que
    eu tinha feito estreito demais antes: olhei so quem escreveu no comentario
    final, que e um campo opcional, e por isso achei so 3 casos.

Tambem imprime os nomes de campo do instrumento coreano (pais, categoria,
e-mail) e os codigos das opcoes, que e o que falta para cadastrar o coreano
no painel.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 coreano_conferencia.py
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

import redcap_aggregate as ag  # noqa: E402

SAIDA = os.path.join(HERE, "coreano_conferencia.txt")
CSV_KO = os.path.join(HERE, "coreano_registros.csv")

KO = "delphi_round1_ko"
ADMIN = {"par_code"}


def preenchido(rec, campo):
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def main():
    meta = ag.api({"content": "metadata"})

    ordem = defaultdict(list)
    itens = defaultdict(list)
    escolhas = {}
    rotulo = {}
    for f in meta:
        form, fn = f["form_name"], f["field_name"]
        if not form.startswith("delphi_round1"):
            continue
        rotulo[fn] = re.sub(r"<[^>]+>", " ", f.get("field_label", ""))[:60]
        escolhas[fn] = f.get("select_choices_or_calculations", "")
        if f["field_type"] != "descriptive" and fn not in ADMIN:
            ordem[form].append(fn)
        if re.search(r"_b\d+[a-z]?_(imp|importance)$", fn):
            itens[form].append(fn)

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

    L = []

    # ---------- 1. o instrumento coreano ------------------------------------
    L.append("=" * 72)
    L.append("1. PAINEL COREANO, REGISTRO A REGISTRO")
    L.append("=" * 72)
    L.append("")

    ko_itens = itens.get(KO, [])
    linhas_csv = []
    st_cont = Counter()
    if not ordem.get(KO):
        L.append("  instrumento coreano nao encontrado no metadata")
    else:
        campo_pais = next((c for c in ordem[KO] if c.endswith("_countries")), None)
        campo_mail = next((c for c in ordem[KO] if c.endswith("_email")), None)
        campo_cat = next((c for c in ordem[KO] if "expertise" in c or "_role" in c), None)

        for rec in registros:
            cheios = [c for c in ordem[KO] if preenchido(rec, c)]
            if not cheios:
                continue
            st = str(rec.get(f"{KO}_complete", "")).strip()
            ts = str(rec.get(f"{KO}_timestamp", "")).strip()
            n = sum(1 for c in ko_itens if preenchido(rec, c))
            st_cont[st or "(vazio)"] += 1
            marca = ""
            if st != "2" and n >= 0.9 * len(ko_itens) and ko_itens:
                marca = "   <<<< RESPONDEU TUDO E NAO CONSTA COMO COMPLETA"
            L.append(f"  registro {rec.get('record_id'):>5} | complete={st or '-':<2} | "
                     f"barreiras {n:>2}/{len(ko_itens)} | timestamp={ts or '(vazio)'}{marca}")
            L.append(f"        pais: {str(rec.get(campo_pais,'') or '(vazio)').strip()[:40]}"
                     f"   ultimo campo: {cheios[-1]}")
            linhas_csv.append({
                "record_id": rec.get("record_id", ""),
                "complete": st,
                "timestamp": ts,
                "barreiras": n,
                "de": len(ko_itens),
                "pais": str(rec.get(campo_pais, "") or "").strip(),
                "email": str(rec.get(campo_mail, "") or "").strip(),
                "ultimo_campo": cheios[-1],
            })
        L.append("")
        L.append(f"  total de registros coreanos: {sum(st_cont.values())}")
        for k, v in st_cont.most_common():
            nome = {"2": "COMPLETAS", "0": "incompletas", "1": "nao verificadas"}.get(k, k)
            L.append(f"     complete={k:<8} {v:>4}  ({nome})")
        L.append("")
        L.append("  --- para cadastrar o coreano no painel ---")
        L.append(f"  country_field  : {campo_pais}")
        L.append(f"  category_field : {campo_cat}")
        L.append(f"  email_field    : {campo_mail}")
        L.append(f"  complete_field : {KO}_complete")
        if campo_cat and escolhas.get(campo_cat):
            L.append("  opcoes da categoria:")
            for op in escolhas[campo_cat].split("|"):
                L.append(f"     {op.strip()}")

    # ---------- 2. teste global -------------------------------------------
    L.append("")
    L.append("=" * 72)
    L.append("2. TESTE GLOBAL: RESPONDEU QUASE TUDO MAS NAO CONSTA COMO COMPLETA")
    L.append("=" * 72)
    L.append("")
    L.append("  (o teste anterior olhou so quem escreveu no comentario final, que e")
    L.append("   opcional; este olha quem respondeu as barreiras, que e o que importa)")
    L.append("")
    achados = defaultdict(list)
    for rec in registros:
        for form in forms:
            lista = itens.get(form, [])
            if not lista:
                continue
            n = sum(1 for c in lista if preenchido(rec, c))
            if n == 0:
                continue
            st = str(rec.get(f"{form}_complete", "")).strip()
            if st == "2":
                continue
            if n >= 0.9 * len(lista):
                ts = str(rec.get(f"{form}_timestamp", "")).strip()
                achados[form].append((rec.get("record_id"), n, len(lista), st, ts))
            break

    if not achados:
        L.append("  nenhum caso: quem responde as barreiras ate o fim fica marcado como completo")
    else:
        tot = sum(len(v) for v in achados.values())
        L.append(f"  {tot} casos encontrados:")
        L.append("")
        for form, v in sorted(achados.items(), key=lambda x: -len(x[1])):
            L.append(f"  {form}: {len(v)}")
            for rid, n, de, st, ts in sorted(v, key=lambda x: -x[1])[:15]:
                L.append(f"     registro {rid:>5} | {n:>2}/{de} barreiras | "
                         f"complete={st or '-'} | timestamp={ts or '(vazio)'}")
            L.append("")

    with open(SAIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    if linhas_csv:
        with open(CSV_KO, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(linhas_csv[0].keys()))
            wr.writeheader()
            wr.writerows(linhas_csv)

    print("\n".join(L))
    print(f"\nsalvo em {os.path.basename(SAIDA)}")
    if linhas_csv:
        print(f"registros coreanos -> {os.path.basename(CSV_KO)} (tem e-mail: nao versione)")


if __name__ == "__main__":
    main()
