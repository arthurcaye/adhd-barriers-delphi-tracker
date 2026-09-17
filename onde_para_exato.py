#!/usr/bin/env python3
"""
Qual e, exatamente, o ULTIMO CAMPO que a pessoa respondeu antes de parar?

O diagnostico anterior mostrou 639 paradas na ultima pagina, mas o teste do
comentario final mostrou que so 3 pessoas escreveram ali. Logo, o "ultimo
campo" dessas 639 e outra coisa. Este script nomeia o campo, sem agrupar por
pagina, para nao esconder nada atras do mapeamento.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 onde_para_exato.py
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

SAIDA = os.path.join(HERE, "onde_para_exato.txt")


def preenchido(rec, campo):
    if campo in rec:
        return bool(str(rec[campo]).strip())
    pref = campo + "___"
    return any(k.startswith(pref) and str(v).strip() == "1" for k, v in rec.items())


def main():
    meta = ag.api({"content": "metadata"})

    ordem = defaultdict(list)     # form -> campos preenchiveis, na ordem
    tipo = {}
    rotulo = {}
    secao = {}
    obrig = {}
    for f in meta:
        if f["field_type"] == "descriptive":
            continue
        form = f["form_name"]
        ordem[form].append(f["field_name"])
        tipo[f["field_name"]] = f["field_type"]
        rotulo[f["field_name"]] = re.sub(r"<[^>]+>", " ", f.get("field_label", ""))[:70]
        secao[f["field_name"]] = re.sub(r"<[^>]+>", " ", f.get("section_header", "") or "")[:45]
        obrig[f["field_name"]] = (f.get("required_field", "") or "").strip().lower() == "y"

    # so os instrumentos do Delphi
    forms = [f for f in ordem if f.startswith("delphi_round1")]

    pedidos = {"record_id"}
    for form in forms:
        pedidos |= set(ordem[form])
        pedidos.add(f"{form}_complete")

    print(f"consultando {len(pedidos)} campos...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros\n")

    # --- descarta campos administrativos -------------------------------------
    # Um campo auto-preenchido (par_code e o caso aqui) aparece em registros
    # onde NADA mais foi respondido. Como ele fica no fim da ordem do
    # formulario, virava sempre o "ultimo campo preenchido" e escondia o campo
    # real: 100% dos incompletos em ingles apareciam parando nele.
    # Criterio: se um campo e o UNICO preenchido em mais de 5% dos registros
    # que tocaram o formulario, ele e administrativo, nao e resposta.
    sozinho = defaultdict(Counter)
    tocaram = Counter()
    for rec in registros:
        for form in forms:
            cheios = [c for c in ordem[form] if preenchido(rec, c)]
            if not cheios:
                continue
            tocaram[form] += 1
            if len(cheios) == 1:
                sozinho[form][cheios[0]] += 1

    administrativos = {}
    for form in forms:
        n = tocaram.get(form, 0)
        if n < 20:
            continue
        fora = [c for c, k in sozinho[form].items() if k > 0.05 * n]
        if fora:
            administrativos[form] = fora
            ordem[form] = [c for c in ordem[form] if c not in set(fora)]

    if administrativos:
        print("campos administrativos descartados (apareciam preenchidos sozinhos):")
        for form, campos in administrativos.items():
            for c in campos:
                print(f"  {form}: {c}  — unico campo preenchido em "
                      f"{sozinho[form][c]} de {tocaram[form]} registros")
        print()

    ultimo_campo = defaultdict(Counter)   # form -> Counter(campo)
    incompletos = Counter()

    so_administrativo = 0
    for rec in registros:
        # o instrumento usado e aquele em que a pessoa mais preencheu coisas
        melhor, cheios_melhor = None, []
        for form in forms:
            cheios = [c for c in ordem[form] if preenchido(rec, c)]
            if len(cheios) > len(cheios_melhor):
                melhor, cheios_melhor = form, cheios
        if melhor is None:
            # nenhum campo de conteudo: so tinha campo administrativo?
            if any(preenchido(rec, c)
                   for form in forms for c in administrativos.get(form, [])):
                so_administrativo += 1
            continue
        if str(rec.get(f"{melhor}_complete", "")).strip() == "2":
            continue
        ultimo_campo[melhor][cheios_melhor[-1]] += 1
        incompletos[melhor] += 1

    L = []
    L.append("ULTIMO CAMPO RESPONDIDO ANTES DE PARAR — por instrumento")
    L.append("")
    if so_administrativo:
        L.append(f"  {so_administrativo} registros so tinham campo administrativo "
                 f"(abriram o link e nao responderam nada) — fora da conta abaixo")
        L.append("")
    for form in sorted(forms, key=lambda f: -incompletos.get(f, 0)):
        n = incompletos.get(form, 0)
        if not n:
            continue
        L.append(f"=== {form}  ({n} incompletos) ===")
        for campo, c in ultimo_campo[form].most_common(12):
            pct = 100 * c / n
            flag = " [OBRIGATORIO]" if obrig.get(campo) else ""
            L.append(f"  {c:>5} ({pct:4.1f}%)  {campo}  <{tipo.get(campo,'?')}>{flag}")
            if secao.get(campo):
                L.append(f"            secao: {secao[campo]}")
            L.append(f"            texto: {rotulo.get(campo,'')}")
        L.append("")

    with open(SAIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"salvo em {os.path.basename(SAIDA)}")


if __name__ == "__main__":
    main()
