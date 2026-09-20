#!/usr/bin/env python3
"""
Confere, um a um, o status de uma lista de painelistas convidados.

Nasceu do pedido da Dra. Yunhye Oh: ela mandou a lista de quem o grupo
coreano convidou para a Rodada 1 e perguntou quem ja respondeu. Serve para
qualquer lider nacional que mandar uma lista parecida.

DETALHE QUE IMPORTA: nao basta procurar no instrumento coreano. Um painelista
convidado pelo grupo da Coreia pode perfeitamente ter respondido em ingles -
varios fizeram isso antes de a versao coreana existir. Entao a busca varre os
campos de e-mail dos 12 idiomas MAIS o email_todos.

Tambem junta os varios registros da mesma pessoa: o link publico cria um
registro novo a cada abertura, entao quem conferiu a propria resposta aparece
duas ou tres vezes. O status reportado e o do MELHOR registro dela.

Uso:
  1. Abra a planilha do lider nacional no Google Sheets
  2. Arquivo > Fazer download > Valores separados por virgula (.csv)
  3. Mova o arquivo para esta pasta
  4. cd ~/Downloads/delphi_emails/delphi_dashboard
     python3 confere_painel.py "nome do arquivo.csv"

Gera:
  <arquivo>_conferido.csv   a lista original + colunas de status
  <arquivo>_resumo.txt      contagens, sem dado pessoal
"""

import csv
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

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

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

RE_IMP = re.compile(r"_b(\d+[a-z]?)_(?:imp|importance)$")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    entrada = sys.argv[1]
    if not os.path.exists(entrada):
        entrada2 = os.path.join(HERE, entrada)
        if os.path.exists(entrada2):
            entrada = entrada2
        else:
            sys.exit(f"ERRO: nao encontrei o arquivo {sys.argv[1]}")

    # ---------------------------------------------- le a lista do lider
    with open(entrada, encoding="utf-8-sig") as fh:
        linhas = list(csv.reader(fh))
    if not linhas:
        sys.exit("ERRO: planilha vazia.")

    # acha a coluna de e-mail sozinho: a que tem mais enderecos validos
    n_col = max(len(l) for l in linhas)
    pontos = [0] * n_col
    for l in linhas:
        for i, c in enumerate(l):
            if EMAIL_RE.search(c or ""):
                pontos[i] += 1
    col_email = pontos.index(max(pontos))
    if max(pontos) == 0:
        sys.exit("ERRO: nenhuma coluna da planilha tem e-mail reconhecivel.")

    # A planilha pode vir sem cabecalho, e o download do Google as vezes traz
    # a primeira linha em branco. Tratamos os dois casos: se a primeira linha
    # nao tem e-mail, ela e cabecalho (ou lixo) e sai do corpo; se estiver
    # vazia, inventamos nomes de coluna para o arquivo de saida ficar legivel.
    primeira = linhas[0]
    tem_cabecalho = not EMAIL_RE.search(
        primeira[col_email] if col_email < len(primeira) else "")
    if tem_cabecalho and not any((c or "").strip() for c in primeira):
        cabecalho = [f"coluna {i+1}" for i in range(n_col)]
    elif tem_cabecalho:
        cabecalho = list(primeira) + [""] * (n_col - len(primeira))
    else:
        cabecalho = [f"coluna {i+1}" for i in range(n_col)]
    corpo = linhas[1:] if tem_cabecalho else linhas

    convidados = []
    for l in corpo:
        bruto = l[col_email] if col_email < len(l) else ""
        m = EMAIL_RE.search(bruto or "")
        convidados.append({"linha": l, "email": m.group(0).lower() if m else ""})

    com_email = [c for c in convidados if c["email"]]
    print(f"planilha: {os.path.basename(entrada)}")
    print(f"  coluna de e-mail detectada: {col_email + 1}"
          + (f" ({cabecalho[col_email]})" if tem_cabecalho and col_email < len(cabecalho) else ""))
    print(f"  {len(convidados)} linhas, {len(com_email)} com e-mail valido\n")

    # ---------------------------------------------- le o REDCap
    print("consultando o REDCap...")
    meta = ag.api({"content": "metadata"})
    nomes = {f["field_name"] for f in meta}
    imp_por_form = defaultdict(set)
    for f in meta:
        m = RE_IMP.search(f["field_name"])
        if m:
            imp_por_form[f["form_name"]].add(m.group(1))

    pedidos = {"record_id"}
    if "email_todos" in nomes:
        pedidos.add("email_todos")
    for form, (pref, email, nome) in FONTES.items():
        for c in (email, nome):
            if c in nomes:
                pedidos.add(c)
        pedidos.add(f"{form}_complete")
        for b in imp_por_form.get(form, set()):
            campo = f"{pref}_b{b}_imp"
            if campo in nomes:
                pedidos.add(campo)

    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros recebidos\n")

    # ---------------------------------------------- indexa por e-mail
    por_email = defaultdict(list)
    for rec in registros:
        enderecos = set()
        v = str(rec.get("email_todos", "") or "").strip().lower()
        if v:
            enderecos.add(v)
        for form, (pref, f_email, f_nome) in FONTES.items():
            v = str(rec.get(f_email, "") or "").strip().lower()
            if v:
                enderecos.add(v)
        if not enderecos:
            continue

        # qual instrumento essa pessoa usou, e quao longe foi
        melhor = None
        for form, (pref, f_email, f_nome) in FONTES.items():
            ids = imp_por_form.get(form, set())
            n = sum(1 for b in ids if str(rec.get(f"{pref}_b{b}_imp", "") or "").strip())
            completo = str(rec.get(f"{form}_complete", "") or "").strip() == "2"
            tocou = completo or n or str(rec.get(f_email, "") or "").strip()
            if not tocou:
                continue
            cand = {"form": form, "lang": pref, "n": n, "total": len(ids) or 51,
                    "completo": completo, "nome": str(rec.get(f_nome, "") or "").strip()}
            if melhor is None or (cand["completo"], cand["n"]) > (melhor["completo"], melhor["n"]):
                melhor = cand
        if melhor is None:
            melhor = {"form": "-", "lang": "-", "n": 0, "total": 51, "completo": False, "nome": ""}
        melhor["record_id"] = rec.get("record_id")
        for e in enderecos:
            por_email[e].append(melhor)

    # ---------------------------------------------- confere um a um
    contagem = {"completo": 0, "parcial": 0, "so_abriu": 0, "sem_registro": 0, "sem_email": 0}
    saida = []
    for c in convidados:
        if not c["email"]:
            contagem["sem_email"] += 1
            saida.append(c["linha"] + ["(sem e-mail na planilha)", "", "", ""])
            continue
        achados = por_email.get(c["email"], [])
        if not achados:
            contagem["sem_registro"] += 1
            saida.append(c["linha"] + ["nao consta", "", "", ""])
            continue
        melhor = max(achados, key=lambda x: (x["completo"], x["n"]))
        if melhor["completo"]:
            status = "COMPLETO"; contagem["completo"] += 1
        elif melhor["n"] > 0:
            status = "parcial"; contagem["parcial"] += 1
        else:
            status = "abriu mas nao respondeu"; contagem["so_abriu"] += 1
        saida.append(c["linha"] + [
            status,
            f"{melhor['n']}/{melhor['total']}",
            melhor["lang"],
            str(len(achados)) if len(achados) > 1 else "",
        ])

    base = os.path.splitext(os.path.basename(entrada))[0]
    destino = os.path.join(HERE, f"{base}_conferido.csv")
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        extras = ["status", "barreiras respondidas", "idioma usado", "registros duplicados"]
        wr.writerow((cabecalho if tem_cabecalho else [f"col{i+1}" for i in range(n_col)]) + extras)
        for l in saida:
            wr.writerow(l)

    linhas_resumo = [
        f"CONFERENCIA DO PAINEL — {os.path.basename(entrada)}", "",
        f"  convidados na lista           {len(convidados):>5}",
        f"  COMPLETARAM                   {contagem['completo']:>5}",
        f"  responderam em parte          {contagem['parcial']:>5}",
        f"  abriram e nao responderam     {contagem['so_abriu']:>5}",
        f"  nao constam no banco          {contagem['sem_registro']:>5}",
        f"  sem e-mail na planilha        {contagem['sem_email']:>5}",
        "",
        "Busca feita nos campos de e-mail dos 12 idiomas e no email_todos,",
        "porque convidados de um pais podem ter respondido em outra lingua.",
    ]
    resumo = os.path.join(HERE, f"{base}_resumo.txt")
    with open(resumo, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas_resumo) + "\n")

    print("\n".join(linhas_resumo))
    print()
    print(f"detalhe por pessoa -> {os.path.basename(destino)}  (tem e-mail: nao versione)")
    print(f"resumo             -> {os.path.basename(resumo)}")


if __name__ == "__main__":
    main()
