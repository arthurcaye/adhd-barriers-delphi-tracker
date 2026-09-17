#!/usr/bin/env python3
"""
Check geral do estudo: procura os problemas que ja nos morderam e os vizinhos.

Cada verificacao aqui existe porque algo parecido deu errado de verdade:

  1. INSTRUMENTO FORA DO PAINEL   (foi assim que perdemos alemao, japones e
     coreano: o instrumento existia no REDCap e nao estava no config.json,
     entao o painel contava zero)
  2. CODIGOS DE CATEGORIA         (o ingles usa codigos diferentes dos demais;
     um mapa trocado classifica clinico como pesquisador silenciosamente)
  3. PAIS NAO RECONHECIDO         (texto fora da lista de aliases some do
     painel sem aviso)
  4. RESPONDEU TUDO E NAO CONSTA  (os 57; aqui conferido pelo TRIO completo
     importancia + viabilidade + recomendacao, nao so importancia)
  5. E-MAIL REPETIDO              (mesma pessoa em varios registros: quem
     desistiu e recomecou do zero vira dois registros)
  6. RECONCILIACAO                (o total do data.json publicado bate com o
     numero de completos no REDCap?)

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 check_geral.py
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

SAIDA = os.path.join(HERE, "check_geral.txt")
CSV_REC = os.path.join(HERE, "check_recuperaveis.csv")
CSV_DUP = os.path.join(HERE, "check_duplicados.csv")

ADMIN = {"par_code"}
TRIO = (r"_(imp|importance)$", r"_(feas|feasibility)$", r"_(rec|recommendation)$")


def preenchido(rec, campo):
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def barreira_de(fn):
    m = re.search(r"_(b\d+[a-z]?)_", fn)
    return m.group(1) if m else None


def main():
    L = []
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    fontes = {s["form"]: s for s in cfg["sources"]}
    aliases = cfg.get("country_aliases", {})
    alias_norm = {ag.country_key(k) for k in aliases}

    meta = ag.api({"content": "metadata"})
    instrumentos = sorted({f["form_name"] for f in meta
                           if f["form_name"].startswith("delphi_round1")})

    ordem = defaultdict(list)
    escolhas, tipo = {}, {}
    trio = defaultdict(lambda: defaultdict(dict))   # form -> barreira -> papel -> campo
    for f in meta:
        form, fn = f["form_name"], f["field_name"]
        if not form.startswith("delphi_round1"):
            continue
        tipo[fn] = f["field_type"]
        escolhas[fn] = f.get("select_choices_or_calculations", "") or ""
        if f["field_type"] != "descriptive" and fn not in ADMIN:
            ordem[form].append(fn)
        b = barreira_de(fn)
        if b:
            for papel, padrao in zip(("imp", "feas", "rec"), TRIO):
                if re.search(padrao, fn):
                    trio[form][b][papel] = fn

    # ---------- 1. instrumento fora do painel -------------------------------
    L += ["=" * 70, "1. INSTRUMENTOS DO REDCAP x CONFIGURACAO DO PAINEL", "=" * 70, ""]
    faltando = [i for i in instrumentos if i not in fontes]
    sobrando = [f for f in fontes if f not in instrumentos]
    if faltando:
        L.append("  PROBLEMA: existem no REDCap e NAO estao no config.json")
        for i in faltando:
            L.append(f"     {i}   <-- respostas invisiveis no painel")
    if sobrando:
        L.append("  PROBLEMA: estao no config.json e nao existem no REDCap")
        for i in sobrando:
            L.append(f"     {i}")
    if not faltando and not sobrando:
        L.append(f"  ok: {len(instrumentos)} instrumentos, todos cadastrados")
    L.append("")

    # ---------- 2. codigos de categoria ------------------------------------
    L += ["=" * 70, "2. MAPA DE CATEGORIAS x OPCOES REAIS DO INSTRUMENTO", "=" * 70, ""]
    problemas = 0
    for form, src in sorted(fontes.items()):
        campo = src.get("category_field")
        if not campo or campo not in escolhas:
            L.append(f"  {form}: campo de categoria '{campo}' nao encontrado no metadata")
            problemas += 1
            continue
        reais = {}
        for op in escolhas[campo].split("|"):
            if "," in op:
                cod, rot = op.split(",", 1)
                reais[cod.strip()] = rot.strip()
        mapa = src.get("category_map", {})
        sem_mapa = [c for c in reais if c not in mapa]
        sem_opcao = [c for c in mapa if c not in reais]
        if sem_mapa or sem_opcao:
            problemas += 1
            L.append(f"  {form}:")
            for c in sem_mapa:
                L.append(f"     codigo {c} existe no instrumento e NAO esta no mapa"
                         f"  ({reais[c][:45]})")
            for c in sem_opcao:
                L.append(f"     codigo {c} esta no mapa e NAO existe no instrumento")
    if not problemas:
        L.append("  ok: todos os codigos de todos os idiomas estao mapeados")
    L.append("")

    # ---------- dados -------------------------------------------------------
    pedidos = {"record_id"}
    for form in instrumentos:
        pedidos |= set(ordem[form]) | {f"{form}_complete"}
    print(f"consultando {len(pedidos)} campos...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros\n")

    # ---------- 3. paises nao reconhecidos ---------------------------------
    L += ["=" * 70, "3. PAIS NAO RECONHECIDO (resposta completa que some do painel)",
          "=" * 70, ""]
    desconhecidos = Counter()
    completos_por_form = Counter()
    for rec in registros:
        for form in instrumentos:
            if str(rec.get(f"{form}_complete", "")).strip() != "2":
                continue
            completos_por_form[form] += 1
            src = fontes.get(form)
            if not src:
                continue
            txt = str(rec.get(src.get("country_field", ""), "") or "").strip()
            if not txt:
                desconhecidos["(campo vazio)"] += 1
                continue
            # Usar EXATAMENTE a normalizacao do agregador. Comparar texto cru
            # contra o dicionario cru da 118 falsos positivos so de caixa alta
            # ("UK" x "Uk", "italia" x "Italia"), que o agregador resolve.
            for p in ag.split_countries(txt):
                if ag.country_key(p) not in alias_norm:
                    desconhecidos[p[:40]] += 1
    if desconhecidos:
        L.append(f"  {sum(desconhecidos.values())} ocorrencias nao reconhecidas"
                 f" em respostas COMPLETAS:")
        for txt, n in desconhecidos.most_common(25):
            L.append(f"     {n:>4}x  {txt}")
        L.append("")
        L.append("  (cada uma some da tabela por pais; adicionar em country_aliases resolve)")
    else:
        L.append("  ok: todo pais informado em resposta completa e reconhecido")
    L.append("")

    # ---------- 4. respondeu tudo e nao consta ------------------------------
    L += ["=" * 70, "4. RESPONDEU AS BARREIRAS E NAO CONSTA COMO COMPLETA", "=" * 70, ""]
    L.append("  criterio: respondeu os TRES campos (importancia, viabilidade,")
    L.append("  recomendacao) de pelo menos 90% das barreiras, e complete != 2")
    L.append("")
    recuperaveis = []
    for rec in registros:
        for form in instrumentos:
            barreiras = trio.get(form, {})
            if not barreiras:
                continue
            if str(rec.get(f"{form}_complete", "")).strip() == "2":
                continue
            completas = sum(
                1 for b, papeis in barreiras.items()
                if len(papeis) == 3 and all(preenchido(rec, c) for c in papeis.values())
            )
            if completas == 0:
                continue
            so_imp = sum(1 for b, p in barreiras.items()
                         if "imp" in p and preenchido(rec, p["imp"]))
            if completas >= 0.9 * len(barreiras):
                src = fontes.get(form, {})
                recuperaveis.append({
                    "record_id": rec.get("record_id", ""),
                    "instrumento": form,
                    "barreiras_trio_completo": completas,
                    "barreiras_so_importancia": so_imp,
                    "de": len(barreiras),
                    "complete": str(rec.get(f"{form}_complete", "")).strip(),
                    "pais": str(rec.get(src.get("country_field", ""), "") or "").strip(),
                    "email": str(rec.get(src.get("email_field", ""), "") or "").strip(),
                })
            break
    if recuperaveis:
        por_form = Counter(r["instrumento"] for r in recuperaveis)
        L.append(f"  {len(recuperaveis)} registros com o trio completo em >=90% das barreiras:")
        for form, n in por_form.most_common():
            L.append(f"     {form:<26} {n:>4}")
        L.append("")
        tot_now = sum(completos_por_form.values())
        L.append(f"  completos hoje: {tot_now} | recuperaveis: {len(recuperaveis)}"
                 f" | ganho potencial: {100*len(recuperaveis)/max(tot_now,1):.1f}%")
    else:
        L.append("  nenhum: quem responde as barreiras ate o fim fica marcado como completo")
    L.append("")

    # ---------- 5. e-mail repetido -----------------------------------------
    L += ["=" * 70, "5. MESMO E-MAIL EM MAIS DE UM REGISTRO", "=" * 70, ""]
    por_email = defaultdict(list)
    for rec in registros:
        for form in instrumentos:
            src = fontes.get(form)
            if not src:
                continue
            em = str(rec.get(src.get("email_field", ""), "") or "").strip().lower()
            if em and "@" in em:
                st = str(rec.get(f"{form}_complete", "")).strip()
                por_email[em].append((rec.get("record_id", ""), form, st))
                break
    dups = {e: v for e, v in por_email.items() if len(v) > 1}
    if dups:
        dois_completos = {e: v for e, v in dups.items()
                          if sum(1 for x in v if x[2] == "2") > 1}
        L.append(f"  {len(dups)} e-mails aparecem em mais de um registro"
                 f" ({sum(len(v) for v in dups.values())} registros no total)")
        L.append(f"  destes, {len(dois_completos)} tem MAIS DE UMA resposta COMPLETA"
                 f"  <-- duplicata real na analise")
        if dois_completos:
            L.append("")
            for e, v in list(dois_completos.items())[:10]:
                ids = ", ".join(f"{r}({f.replace('delphi_round1_','')},c={s})"
                                for r, f, s in v)
                L.append(f"     {ids}")
    else:
        L.append("  ok: nenhum e-mail repetido")
    L.append("")

    # ---------- 6. reconciliacao -------------------------------------------
    L += ["=" * 70, "6. RECONCILIACAO COM O data.json PUBLICADO", "=" * 70, ""]
    caminho = os.path.join(HERE, "data.json")
    tot_redcap = sum(completos_por_form.values())
    if os.path.exists(caminho):
        d = json.load(open(caminho, encoding="utf-8"))
        pub = d.get("totals", {}).get("responses", 0)
        L.append(f"  completos no REDCap agora        : {tot_redcap}")
        L.append(f"  no data.json local ({d.get('generated_at','?')[:16]}) : {pub}")
        dif = tot_redcap - pub
        L.append(f"  diferenca                        : {dif}")
        if dif:
            L.append("")
            L.append("  parte da diferenca e tempo (o arquivo local pode estar velho);")
            L.append("  parte e pais nao reconhecido, do item 3 acima.")
        L.append("")
        L.append("  completos por instrumento no REDCap:")
        for form, n in completos_por_form.most_common():
            marca = "  <-- fora do painel" if form not in fontes else ""
            L.append(f"     {form:<26} {n:>4}{marca}")
    else:
        L.append("  data.json local nao encontrado")

    with open(SAIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    if recuperaveis:
        with open(CSV_REC, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(recuperaveis[0].keys()))
            wr.writeheader()
            wr.writerows(recuperaveis)
    if dups:
        with open(CSV_DUP, "w", encoding="utf-8", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["email", "record_id", "instrumento", "complete"])
            for e, v in dups.items():
                for r, f, s in v:
                    wr.writerow([e, r, f, s])

    print("\n".join(L))
    print(f"\nsalvo em {os.path.basename(SAIDA)}")
    if recuperaveis:
        print(f"recuperaveis -> {os.path.basename(CSV_REC)} (tem e-mail: nao versione)")
    if dups:
        print(f"duplicados   -> {os.path.basename(CSV_DUP)} (tem e-mail: nao versione)")


if __name__ == "__main__":
    main()
