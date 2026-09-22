#!/usr/bin/env python3
"""
Compara os 12 instrumentos de idioma entre si, procurando defeito estrutural.

Por que existe: o campo es_std_rating, que mostrava o documento de
especificacao no lugar do questionario, ficou meses no ar e so apareceu
porque uma painelista no Paraguai teve a gentileza de mandar uma captura de
tela. Nenhuma metrica o mostrava: quem trava abandona sem avisar, e um
abandono por defeito e indistinguivel de um abandono por cansaco.

A logica da auditoria: os doze instrumentos deveriam ser o MESMO
questionario em doze linguas. Entao qualquer coisa que exista em um e nao
nos outros e suspeita, por construcao. Nao preciso saber espanhol para
desconfiar de um campo que so o espanhol tem.

O ingles e a referencia porque foi o original; os demais sao traducoes dele.

O que verifica:
  1. campos que faltam num idioma e existem no ingles
  2. campos que existem num idioma e em nenhum outro   <- pegaria o es_std_rating
  3. tipo de campo divergente (um radio que virou texto em uma lingua)
  4. escala com numero de opcoes diferente (faltou o N/A, sobrou um ponto)
  5. texto de especificacao vazado para dentro do conteudo
  6. campo aparentemente nao traduzido (rotulo identico ao ingles)
  7. numero de quebras de pagina
  8. o trio imp/feas/rec completo nas 51 barreiras

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 audita_instrumentos.py
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
        sys.exit("ERRO: .env nao encontrado em " + HERE)
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


carrega_env()
import redcap_aggregate as ag  # noqa: E402

RELATORIO = os.path.join(HERE, "auditoria_instrumentos.txt")
PLANILHA = os.path.join(HERE, "auditoria_instrumentos.csv")

MARCAS_SPEC = [
    (r"\[\s*Cuadro de texto", "espec. de campo (es)"),
    (r"\[\s*Men[uú] desplegable", "espec. de menu (es)"),
    (r"\[\s*Open[- ]ended text", "espec. de campo (en)"),
    (r"\[\s*Required dropdown", "espec. de menu (en)"),
    (r"\[\s*Caixa de texto", "espec. de campo (pt)"),
    (r"\[\s*Men[uú] suspenso", "espec. de menu (pt)"),
    (r"\(\s*\)\s*\d+\s*=", "escala escrita como texto"),
    (r"obligatori[ao]\s*\]", "marcador de obrigatoriedade"),
    (r"\[\s*Text box\b", "espec. de campo (en)"),
]


def limpa(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


def prefixo_do(form, campos):
    """Descobre o prefixo do instrumento pela maioria dos nomes de campo.

    Nao da para deduzir do nome do formulario: delphi_round1_spanish usa
    prefixo 'es', delphi_round1_zh_cn usa 'zhcn'. E o ingles tem campos sem
    prefixo nenhum (id_email), residuo de quando era o unico idioma.
    """
    cont = Counter()
    for c in campos:
        if "_" in c:
            cont[c.split("_", 1)[0]] += 1
    return cont.most_common(1)[0][0] if cont else ""


def chave(campo, pref):
    """Nome do campo sem o prefixo de idioma: a identidade logica dele."""
    if pref and campo.startswith(pref + "_"):
        return campo[len(pref) + 1:]
    return campo


def main():
    print("lendo o dicionario de dados...")
    meta = ag.api({"content": "metadata"})
    print(f"{len(meta)} campos\n")

    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    forms_conhecidos = [s["form"] for s in cfg["sources"]]

    por_form = defaultdict(list)
    for f in meta:
        por_form[f["form_name"]].append(f)
    forms = [f for f in forms_conhecidos if f in por_form]
    extras = [f for f in por_form if f not in forms_conhecidos]

    prefixos, indice = {}, {}
    for form in forms:
        campos = [f["field_name"] for f in por_form[form]]
        pref = prefixo_do(form, campos)
        prefixos[form] = pref
        indice[form] = {chave(f["field_name"], pref): f for f in por_form[form]}

    REF = "delphi_round1_en"
    if REF not in indice:
        sys.exit("ERRO: instrumento em ingles nao encontrado.")
    ref = indice[REF]

    achados = []   # (gravidade, instrumento, campo, tipo, detalhe)

    def anota(grav, form, campo, tipo, detalhe):
        achados.append((grav, form, campo, tipo, detalhe))

    # ---------------------------------------------- 1, 2, 3 e 4: comparacao
    todas_chaves = defaultdict(set)
    for form in forms:
        for k in indice[form]:
            todas_chaves[k].add(form)

    # Um campo so "falta" se a maioria dos instrumentos o tem. Sem esse
    # filtro, campos de projeto que vivem apenas no formulario ingles
    # (id_email, survey_language, par_code, par_joindate) apareceriam como
    # ausentes nos outros onze, afogando os achados de verdade em ruido.
    LIMIAR = 0.6
    universais = {k for k, onde in todas_chaves.items()
                  if len(onde) >= LIMIAR * len(forms)}

    for form in forms:
        if form == REF:
            continue
        atual = indice[form]
        for k, fref in ref.items():
            if k not in atual:
                if k in universais:
                    anota("ALTO", form, k, "campo faltando",
                          f"existe em {len(todas_chaves[k])} dos {len(forms)} "
                          f"instrumentos ({fref['field_type']}), e nao aqui")
                continue
            f = atual[k]
            if f["field_type"] != fref["field_type"]:
                anota("ALTO", form, f["field_name"], "tipo divergente",
                      f"aqui e {f['field_type']}, no ingles e {fref['field_type']}")
            # Divergencia de numero de opcoes e grave por um motivo que nao
            # e obvio: o painel traduz o codigo da opcao em categoria de
            # stakeholder pelo category_map do config.json, e o mapa e por
            # idioma. Se um instrumento ganhou ou perdeu uma opcao, o codigo
            # deixa de significar a mesma coisa e a contagem do painel sai
            # errada sem nenhum aviso.
            codigos_a = re.findall(r"(?:^|\|)\s*([^,|]+?)\s*,",
                                   f.get("select_choices_or_calculations") or "")
            codigos_r = re.findall(r"(?:^|\|)\s*([^,|]+?)\s*,",
                                   fref.get("select_choices_or_calculations") or "")
            if codigos_r and codigos_a != codigos_r:
                if len(codigos_a) != len(codigos_r):
                    anota("ALTO", form, f["field_name"], "numero de opcoes",
                          f"aqui {len(codigos_a)} opcoes ({','.join(codigos_a)}), "
                          f"no ingles {len(codigos_r)} ({','.join(codigos_r)})")
                else:
                    anota("MEDIO", form, f["field_name"], "codigos das opcoes",
                          f"aqui {','.join(codigos_a)}, no ingles {','.join(codigos_r)}")
            if fref.get("required_field") != f.get("required_field"):
                anota("MEDIO", form, f["field_name"], "obrigatoriedade",
                      f"aqui '{f.get('required_field') or 'nao'}', "
                      f"no ingles '{fref.get('required_field') or 'nao'}'")

        for k, f in atual.items():
            if k in ref:
                continue
            onde = todas_chaves[k]
            if len(onde) == 1:
                anota("ALTO", form, f["field_name"], "campo so existe aqui",
                      f"nenhum outro dos {len(forms)} instrumentos tem equivalente")
            else:
                anota("BAIXO", form, f["field_name"], "campo fora do ingles",
                      f"existe tambem em: {', '.join(sorted(o.split('_')[-1] for o in onde if o != form))}")

    # ---------------------------------------------- 5: especificacao vazada
    for form in forms:
        for f in por_form[form]:
            for chave_txt in ("field_label", "field_note", "section_header",
                              "select_choices_or_calculations"):
                txt = limpa(f.get(chave_txt, ""))
                for padrao, rotulo in MARCAS_SPEC:
                    if re.search(padrao, txt, re.IGNORECASE):
                        anota("ALTO", form, f["field_name"], "texto de especificacao",
                              f"{rotulo} em {chave_txt}: {txt[:90]}")
                        break

    # ---------------------------------------------- 6: nao traduzido
    for form in forms:
        if form == REF:
            continue
        pref = prefixos[form]
        iguais = []
        for k, f in indice[form].items():
            if k not in ref:
                continue
            a, b = limpa(f.get("field_label")), limpa(ref[k].get("field_label"))
            # so conta se for texto de verdade, nao rotulo vazio ou numero
            if a and a == b and len(a) > 25:
                iguais.append(f["field_name"])
        if iguais:
            anota("MEDIO", form, f"({len(iguais)} campos)", "possivelmente nao traduzido",
                  "rotulo identico ao ingles: " + ", ".join(iguais[:6])
                  + (" ..." if len(iguais) > 6 else ""))

    # ---------------------------------------------- 7 e 8: paginacao e trio
    print(f"{'instrumento':<26}{'campos':>7}{'paginas':>9}{'barreiras completas':>21}")
    linhas_resumo = []
    for form in forms:
        campos = por_form[form]
        paginas = sum(1 for f in campos if (f.get("section_header") or "").strip())
        pref = prefixos[form]
        ids = set()
        for f in campos:
            m = re.search(r"_b(\d+[a-z]?)_imp$", f["field_name"])
            if m:
                ids.add(m.group(1))
        completas = sum(
            1 for b in ids
            if f"{pref}_b{b}_feas" in {x['field_name'] for x in campos}
            and f"{pref}_b{b}_rec" in {x['field_name'] for x in campos})
        linha = f"{form:<26}{len(campos):>7}{paginas:>9}{completas:>15} de {len(ids)}"
        print(linha)
        linhas_resumo.append(linha)
        if completas != len(ids):
            anota("ALTO", form, "-", "barreira incompleta",
                  f"{len(ids) - completas} barreira(s) sem o trio imp/feas/rec")

    # ---------------------------------------------- relatorio
    ordem = {"ALTO": 0, "MEDIO": 1, "BAIXO": 2}
    achados.sort(key=lambda a: (ordem[a[0]], a[1], a[2]))
    graves = [a for a in achados if a[0] == "ALTO"]

    with open(PLANILHA, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["gravidade", "instrumento", "campo", "tipo", "detalhe"])
        wr.writerows(achados)

    saida = ["AUDITORIA DOS INSTRUMENTOS", "",
             f"{len(forms)} instrumentos comparados contra o ingles.", ""]
    if extras:
        saida.append(f"ATENCAO: {len(extras)} instrumento(s) no REDCap fora do "
                     f"config.json: {', '.join(extras)}")
        saida.append("")
    saida += linhas_resumo + [""]
    conta = Counter(a[0] for a in achados)
    saida.append(f"achados: {conta.get('ALTO',0)} altos, "
                 f"{conta.get('MEDIO',0)} medios, {conta.get('BAIXO',0)} baixos")
    saida.append("")
    if graves:
        saida.append("=" * 68)
        saida.append("GRAVIDADE ALTA — verificar um por um")
        saida.append("=" * 68)
        for _, form, campo, tipo, det in graves:
            saida.append(f"  [{form.replace('delphi_round1_','')}] {campo}")
            saida.append(f"      {tipo}: {det}")
    else:
        saida.append("Nenhum achado de gravidade alta.")

    with open(RELATORIO, "w", encoding="utf-8") as fh:
        fh.write("\n".join(saida) + "\n")

    print()
    print("\n".join(saida[len(linhas_resumo) + 4:]))
    print()
    print(f"relatorio -> {os.path.basename(RELATORIO)}")
    print(f"planilha  -> {os.path.basename(PLANILHA)}  (todos os achados)")


if __name__ == "__main__":
    main()
