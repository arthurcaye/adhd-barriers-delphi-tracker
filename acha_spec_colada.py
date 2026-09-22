#!/usr/bin/env python3
"""
Procura, no dicionario de dados, texto de ESPECIFICACAO que virou conteudo.

Motivo: uma painelista no Paraguai mandou captura da versao em espanhol
mostrando "[Cuadro de texto abierto obligatorio]" e "[Menu desplegable
obligatorio: todos los codigos y titulos de barreras...]" na tela, alem da
escala escrita como "( ) 2 = Factibilidad muy baja". Isso e o documento de
desenho do questionario, nao o questionario: em algum ponto a especificacao
foi colada onde deveria haver campos de verdade.

O script varre rotulo, nota, cabecalho de secao e opcoes de TODOS os campos
atras dessas marcas, e informa em que instrumento e em que ordem estao.

Tambem conta quantas pessoas responderam o campo ANTERIOR e o SEGUINTE ao
trecho suspeito. Se muita gente respondeu o anterior e quase ninguem o
seguinte, esta confirmado que o defeito interrompe o preenchimento ali.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 acha_spec_colada.py
"""

import os
import re
import sys
from collections import Counter

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

# Marcas de especificacao. Deliberadamente amplas e em varios idiomas: o
# mesmo documento de desenho foi usado para montar todas as traducoes, entao
# se vazou no espanhol pode ter vazado em outra.
MARCAS = [
    (r"\[\s*Cuadro de texto", "espec. de campo de texto (es)"),
    (r"\[\s*Men[uú] desplegable", "espec. de menu suspenso (es)"),
    (r"\[\s*Open[- ]ended text", "espec. de campo de texto (en)"),
    (r"\[\s*Dropdown\b", "espec. de menu suspenso (en)"),
    (r"\[\s*Required dropdown", "espec. de menu suspenso (en)"),
    (r"\[\s*Caixa de texto", "espec. de campo de texto (pt)"),
    (r"\[\s*Men[uú] suspenso", "espec. de menu suspenso (pt)"),
    (r"\(\s*\)\s*\d+\s*=", "escala escrita como texto, com ( ) no lugar do radio"),
    (r"\(\s*\)\s*N/?A\b", "opcao N/A escrita como texto"),
    (r"obligatori[ao]\s*\]", "marcador de obrigatoriedade da especificacao"),
]
CAMPOS_TEXTO = ["field_label", "field_note", "section_header",
                "select_choices_or_calculations"]


def limpa(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def main():
    print("lendo o dicionario de dados...")
    meta = ag.api({"content": "metadata"})
    print(f"{len(meta)} campos\n")

    ordem = {f["field_name"]: i for i, f in enumerate(meta)}
    suspeitos = []
    for f in meta:
        achou = []
        for chave in CAMPOS_TEXTO:
            texto = limpa(f.get(chave, ""))
            for padrao, rotulo in MARCAS:
                if re.search(padrao, texto, re.IGNORECASE):
                    achou.append((rotulo, chave, texto))
        if achou:
            suspeitos.append((f, achou))

    if not suspeitos:
        print("Nenhum texto de especificacao encontrado no DICIONARIO.")
        print()
        print("Isso muda o diagnostico e e uma informacao util: se o campo")
        print("esta correto no dicionario mas aparece errado para quem responde")
        print("em espanhol, o texto veio do Multi-Language Management. A")
        print("traducao para espanhol daquele campo foi preenchida com o")
        print("documento de especificacao.")
        print()
        print("Onde conferir: menu Multi-Language Management, aba do idioma")
        print("Espanhol, secao de traducao dos campos do instrumento")
        print("delphi_round1_spanish. Procure por 'Cuadro de texto'.")
        return

    print(f"{len(suspeitos)} CAMPO(S) COM TEXTO DE ESPECIFICACAO\n")
    por_form = Counter()
    for f, achou in suspeitos:
        por_form[f["form_name"]] += 1
        print(f"  campo      : {f['field_name']}")
        print(f"  instrumento: {f['form_name']}")
        print(f"  tipo       : {f['field_type']}")
        print(f"  posicao    : {ordem[f['field_name']]} de {len(meta)}")
        for rotulo, chave, texto in achou[:3]:
            print(f"  -> {rotulo}")
            print(f"     em {chave}: {texto[:160]}")
        print()
    print("por instrumento:", dict(por_form))

    # ------------------------------------------------ impacto no preenchimento
    alvos = [f for f, _ in suspeitos
             if f["form_name"] == "delphi_round1_spanish"] or [f for f, _ in suspeitos]
    if not alvos:
        return
    primeiro = min(ordem[f["field_name"]] for f in alvos)
    form = alvos[0]["form_name"]
    do_form = [f for f in meta if f["form_name"] == form
               and f["field_type"] in ("radio", "dropdown", "text", "notes",
                                       "checkbox", "yesno")]
    antes = [f for f in do_form if ordem[f["field_name"]] < primeiro]
    depois = [f for f in do_form if ordem[f["field_name"]] > primeiro]
    if not (antes and depois):
        return

    campo_antes = antes[-1]["field_name"]
    campo_depois = depois[0]["field_name"]
    print(f"\nIMPACTO em {form}")
    print(f"  ultimo campo antes do trecho : {campo_antes}")
    print(f"  primeiro campo depois        : {campo_depois}")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "fields": f"record_id,{campo_antes},{campo_depois}",
    })
    n_antes = sum(1 for r in registros if str(r.get(campo_antes, "") or "").strip())
    n_depois = sum(1 for r in registros if str(r.get(campo_depois, "") or "").strip())
    print(f"  responderam o campo anterior : {n_antes}")
    print(f"  responderam o seguinte       : {n_depois}")
    if n_antes:
        perda = 100 * (1 - n_depois / n_antes)
        print(f"  queda                        : {perda:.0f}%")
        if perda > 40:
            print("\n  QUEDA ALTA: confirma que o defeito interrompe o")
            print("  preenchimento nesse ponto.")


if __name__ == "__main__":
    main()
