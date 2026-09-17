#!/usr/bin/env python3
"""
Teste decisivo sobre as ~639 respostas que param na ULTIMA pagina.

Duas explicacoes possiveis, e o carimbo de tempo do REDCap separa as duas:

  A) A pessoa submeteu e o questionario esta completo, mas o campo de status
     nao ficou em "2". Nesse caso {instrumento}_timestamp tem data e hora real
     -> nos estamos SUBCONTANDO respostas validas.

  B) A pessoa respondeu tudo mas o envio final nunca completou. Nesse caso o
     REDCap grava "[not completed]" no timestamp
     -> tem falha no submit final, e da para recuperar essa gente.

Tambem conta quantos dos 51 itens de barreira essas pessoas responderam, para
mostrar se elas estavam mesmo no fim ou so pularam para o final.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 verifica_ultima_pagina.py
"""

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

SAIDA = os.path.join(HERE, "ultima_pagina_resumo.txt")

PREFIXO = {
    "delphi_round1_en": "en", "delphi_round1_ptbr": "ptbr",
    "delphi_round1_spanish": "es", "delphi_round1_fr": "fr",
    "delphi_round1_ar": "ar", "delphi_round1_it": "it",
    "delphi_round1_zh": "zh", "delphi_round1_zh_cn": "zhcn",
    "delphi_round1_de": "de", "delphi_round1_ja": "ja",
    "delphi_round1_ko": "ko",
}


def main():
    meta = ag.api({"content": "metadata"})

    fechamento = {}    # form -> campo _closing_comments
    itens_imp = defaultdict(list)
    for f in meta:
        fn, form = f["field_name"], f["form_name"]
        if fn.endswith("_closing_comments"):
            fechamento[form] = fn
        if re.search(r"_b\d+[a-z]?_(imp|importance)$", fn):
            itens_imp[form].append(fn)

    # Os campos {form}_timestamp NAO podem ir no parametro "fields": o REDCap
    # recusa com erro 400. Eles vem sozinhos por causa de exportSurveyFields.
    pedidos = {"record_id"}
    for form, campo in fechamento.items():
        pedidos |= {campo, f"{form}_complete"}
        pedidos |= set(itens_imp.get(form, []))

    print(f"consultando {len(pedidos)} campos...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros")

    tem_ts = any(k.endswith("_timestamp") for r in registros for k in r)
    if not tem_ts:
        print("timestamps nao vieram junto; buscando por instrumento...")
        por_id = {str(r.get("record_id")): r for r in registros}
        for form in fechamento:
            try:
                extra = ag.api({
                    "content": "record", "type": "flat", "rawOrLabel": "raw",
                    "exportSurveyFields": "true", "forms": form,
                    "fields": "record_id",
                })
            except SystemExit:
                continue
            for r in extra:
                alvo = por_id.get(str(r.get("record_id")))
                if alvo is not None:
                    for k, v in r.items():
                        if k.endswith("_timestamp"):
                            alvo[k] = v
        tem_ts = any(k.endswith("_timestamp") for r in registros for k in r)
    print(f"carimbos de tempo disponiveis: {'sim' if tem_ts else 'NAO'}\n")

    # quem escreveu no campo de comentario final
    status = Counter()
    carimbo = Counter()
    combinado = Counter()
    itens_respondidos = []
    por_idioma = Counter()
    completos_totais = Counter()

    for rec in registros:
        for form, campo in fechamento.items():
            pref = PREFIXO.get(form, form)
            st = str(rec.get(f"{form}_complete", "")).strip()
            if st == "2":
                completos_totais[pref] += 1
            if not str(rec.get(campo, "")).strip():
                continue
            if st == "2":
                continue   # esses ja estao contados como completos, tudo bem

            ts = str(rec.get(f"{form}_timestamp", "")).strip()
            tipo_ts = "com data e hora" if re.match(r"\d{4}-\d{2}-\d{2}", ts) else (ts or "(vazio)")
            status[f"_complete = {st or '(vazio)'}"] += 1
            carimbo[tipo_ts] += 1
            combinado[(st or "vazio", tipo_ts)] += 1
            por_idioma[pref] += 1
            n = sum(1 for c in itens_imp.get(form, []) if str(rec.get(c, "")).strip())
            itens_respondidos.append((n, len(itens_imp.get(form, []))))

    total = sum(status.values())
    L = []
    L.append("AS RESPOSTAS QUE CHEGARAM NA ULTIMA PAGINA MAS NAO CONSTAM COMO COMPLETAS")
    L.append("")
    L.append(f"  pessoas que escreveram no comentario final e nao estao como completas: {total}")
    L.append(f"  (para comparar, completas hoje: {sum(completos_totais.values())})")
    L.append("")
    L.append("STATUS DO FORMULARIO")
    for k, v in status.most_common():
        L.append(f"  {k:<28} {v:>6}")
    L.append("")
    L.append("CARIMBO DE TEMPO DA SURVEY  <-- este e o teste decisivo")
    for k, v in carimbo.most_common():
        L.append(f"  {k:<28} {v:>6}")
    L.append("")
    L.append("  Leitura: 'com data e hora' = a pessoa submeteu e nos estamos")
    L.append("           subcontando. '[not completed]' = o envio final falhou.")
    L.append("")
    L.append("CRUZAMENTO status x carimbo")
    for (st, ts), v in combinado.most_common():
        L.append(f"  complete={st:<8} timestamp={ts:<20} {v:>6}")
    L.append("")
    if itens_respondidos:
        faixas = Counter()
        for n, tot in itens_respondidos:
            if tot == 0:
                faixas["instrumento sem itens"] += 1
            elif n == tot:
                faixas[f"responderam TODOS os {tot} itens"] += 1
            elif n >= 0.9 * tot:
                faixas["responderam 90% ou mais"] += 1
            elif n >= 0.5 * tot:
                faixas["responderam entre 50% e 90%"] += 1
            else:
                faixas["responderam menos de 50%"] += 1
        L.append("QUANTO DO QUESTIONARIO ESSAS PESSOAS TINHAM RESPONDIDO")
        for k, v in faixas.most_common():
            L.append(f"  {k:<36} {v:>6}")
        L.append("")
    L.append("POR IDIOMA")
    for k, v in por_idioma.most_common():
        L.append(f"  {k:<6} {v:>6}")

    with open(SAIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nsalvo em {os.path.basename(SAIDA)}")


if __name__ == "__main__":
    main()
