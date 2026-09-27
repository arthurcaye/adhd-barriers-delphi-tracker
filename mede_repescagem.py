#!/usr/bin/env python3
"""Mede o que a repescagem de 19/09 trouxe de volta.

POR QUE NAO BASTA O cruza_lista_convite.py

As listas repescagem_G*.csv foram regeradas em 22/09, TRES DIAS depois do
disparo. Quem voltou e terminou entre 19 e 22/09 ja tinha saido delas — e e
justamente nos primeiros dias que um lembrete rende mais. Cruzar essas
listas mede so a cauda.

A linha de base verdadeira e o que foi IMPORTADO no REDCap em 19/09:
repescagem_para_importar.csv (record_id + grupo), mais a correcao do grupo
espanhol de 22/09 (repescagem_importar_esfix.csv).

O QUE ESTE SCRIPT RESPONDE, por grupo:
  1. o campo grupo_repescagem ainda esta preenchido no REDCap?
     Se estiver vazio, a importacao nao pegou — e sem importacao o alerta
     nao disparou para aquela pessoa. E o primeiro suspeito quando a
     conversao e baixa demais.
  2. quantas PESSOAS (por e-mail, em qualquer registro/idioma) completaram
  3. quantos registros andaram desde 22/09 sem terminar
     (sinal de que a pessoa abriu o link, mesmo sem concluir)

Nao grava nada no REDCap. So le.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 mede_repescagem.py
"""

import csv
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cruza_lista_convite as cz  # noqa: E402  (carrega .env e o redcap_aggregate)

ag, FONTES, RE_IMP, EMAIL_RE = cz.ag, cz.FONTES, cz.RE_IMP, cz.EMAIL_RE

BASE = "repescagem_para_importar.csv"         # disparo de 19/09
ESFIX = "repescagem_importar_esfix.csv"       # correcao espanhol, 22/09
LISTAS_22 = ["repescagem_G1_nao_comecou.csv", "repescagem_G2_de_1_a_25.csv",
             "repescagem_G3_de_26_em_diante.csv"]


def le(nome):
    caminho = os.path.join(HERE, nome)
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def familia(mails):
    """Tipo de provedor, sem gravar o e-mail. Importa porque o Gmail tem a
    aba Promocoes e filtra remetente que nao passa no DMARC; servidor
    institucional costuma entregar direto. Se a conversao cai com o Gmail
    e nao com o idioma, o problema e entrega, nao texto."""
    if not mails:
        return "sem e-mail"
    d = sorted(mails)[0].split("@")[-1]
    if d in ("gmail.com", "googlemail.com"):
        return "gmail"
    if d.startswith(("hotmail", "outlook", "live.", "msn.")):
        return "microsoft"
    if d.startswith(("yahoo", "ymail")):
        return "yahoo"
    if d in ("qq.com", "163.com", "126.com", "sina.com"):
        return "china"
    if d in ("uol.com.br", "bol.com.br", "terra.com.br", "ig.com.br"):
        return "provedor BR"
    return "institucional/outro"


def main():
    base = {r["record_id"]: r["grupo_repescagem"] for r in le(BASE)}
    if not base:
        sys.exit(f"ERRO: {BASE} nao encontrado ou vazio.")
    esfix = {r["record_id"] for r in le(ESFIX)}

    # barreiras de cada registro em 22/09 (as listas regeradas trazem isso)
    em_22 = {}
    for nome in LISTAS_22:
        for r in le(nome):
            try:
                em_22[r["record_id"]] = int(r.get("barreiras_respondidas") or 0)
            except ValueError:
                pass

    print("consultando o REDCap...")
    meta = ag.api({"content": "metadata"})
    nomes = {f["field_name"] for f in meta}
    imp = defaultdict(list)
    for f in meta:
        if RE_IMP.search(f["field_name"]):
            imp[f["form_name"]].append(f["field_name"])

    pedidos = {"record_id"} | ({"email_todos"} & nomes)
    pedidos |= {c for c in ("grupo_repescagem", "link_repescagem") if c in nomes}
    for form, (_, campo_email) in FONTES.items():
        if campo_email in nomes:
            pedidos.add(campo_email)
        pedidos.add(f"{form}_complete")
        pedidos.update(imp.get(form, []))

    regs = ag.api({"content": "record", "type": "flat", "rawOrLabel": "raw",
                   "fields": ",".join(sorted(pedidos))})
    print(f"{len(regs)} registros\n")

    def emails(rec):
        out = set()
        for campo in ["email_todos"] + [c for _, c in FONTES.values()]:
            v = str(rec.get(campo, "") or "").strip().lower()
            if EMAIL_RE.fullmatch(v):
                out.add(v)
        return out

    def completo(rec):
        return any(str(rec.get(f"{f}_complete", "") or "") == "2" for f in FONTES)

    def barreiras(rec):
        return sum(1 for f in FONTES for c in imp.get(f, [])
                   if str(rec.get(c, "") or "").strip())

    por_id = {r["record_id"]: r for r in regs}
    completou_email = set()
    for r in regs:
        if completo(r):
            completou_email |= emails(r)

    linhas, tab = [], defaultdict(Counter)
    por_fam = defaultdict(Counter)
    for rid, grupo in base.items():
        rec = por_id.get(rid)
        t = tab[grupo]
        t["importados"] += 1
        if rec is None:
            t["registro_sumiu"] += 1
            continue
        if str(rec.get("grupo_repescagem", "") or "").strip():
            t["campo_ok"] += 1
        mails = emails(rec)
        voltou = completo(rec) or bool(mails & completou_email)
        andou = (not voltou and rid in em_22 and barreiras(rec) > em_22[rid])
        t["completou"] += voltou
        t["andou_sem_terminar"] += andou
        fam = familia(mails)
        por_fam[(grupo[1:], fam)]["n"] += 1
        por_fam[(grupo[1:], fam)]["c"] += voltou
        linhas.append({"record_id": rid, "grupo": grupo, "provedor": fam,
                       "esfix": "sim" if rid in esfix else "",
                       "grupo_no_redcap": rec.get("grupo_repescagem", ""),
                       "barreiras_22_09": em_22.get(rid, ""),
                       "barreiras_hoje": barreiras(rec),
                       "completou": "sim" if voltou else "",
                       "andou": "sim" if andou else ""})

    print("grupo    importados  campo no REDCap  completaram      andou s/ terminar")
    tot = Counter()
    for g in sorted(tab, key=lambda x: (x[0], x[1:])):
        t = tab[g]
        tot.update(t)
        n = t["importados"]
        print(f"{g:<8} {n:>10}  {t['campo_ok']:>8} ({100*t['campo_ok']/n:3.0f}%)"
              f"  {t['completou']:>5} ({100*t['completou']/n:4.1f}%)"
              f"  {t['andou_sem_terminar']:>8}")
    n = tot["importados"]
    print(f"{'TOTAL':<8} {n:>10}  {tot['campo_ok']:>8} ({100*tot['campo_ok']/n:3.0f}%)"
          f"  {tot['completou']:>5} ({100*tot['completou']/n:4.1f}%)"
          f"  {tot['andou_sem_terminar']:>8}")
    if tot["registro_sumiu"]:
        print(f"\nregistros importados que nao existem mais: {tot['registro_sumiu']}")

    print("\nPOR NIVEL")
    for nivel in "123":
        c = Counter()
        for g, t in tab.items():
            if g.startswith(nivel):
                c.update(t)
        if c["importados"]:
            print(f"  G{nivel}: {c['completou']}/{c['importados']} completaram "
                  f"({100*c['completou']/c['importados']:.1f}%)")

    print("\nIDIOMA x PROVEDOR  (completaram / importados)")
    print("  separa 'o texto em portugues falhou' de 'o Gmail escondeu a mensagem'")
    fams = sorted({f for _, f in por_fam})
    idiomas = sorted({i for i, _ in por_fam})
    print("  " + " " * 8 + "".join(f"{f[:14]:>16}" for f in fams))
    for i in idiomas:
        cel = []
        for f in fams:
            c = por_fam.get((i, f))
            cel.append(f"{c['c']}/{c['n']}" if c else "-")
        print(f"  {i:<8}" + "".join(f"{x:>16}" for x in cel))

    saida = os.path.join(HERE, "mede_repescagem_detalhe.csv")
    with open(saida, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(linhas[0]))
        wr.writeheader()
        wr.writerows(linhas)
    print(f"\ndetalhe -> {os.path.basename(saida)}  (sem e-mail; so record_id)")

    if tot["campo_ok"] < 0.9 * n:
        print("\nATENCAO: o campo grupo_repescagem esta vazio em mais de 10% dos "
              "registros importados. Se a importacao nao pegou, o alerta nao "
              "disparou para essas pessoas — confira o Notification Log antes "
              "de qualquer segundo envio.")


if __name__ == "__main__":
    main()
