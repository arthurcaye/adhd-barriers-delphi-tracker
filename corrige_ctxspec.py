#!/usr/bin/env python3
"""Tira o "obrigatorio" das caixas de justificativa de contexto (*_ctxspec).

O PROBLEMA

A secao 5 ("Global refinement") pergunta quais barreiras pesam mais em
contextos de poucos recursos, e abre UMA caixa de texto para cada barreira
marcada — todas na mesma pagina e todas OBRIGATORIAS. Quem marca 30
barreiras precisa escrever 30 justificativas antes de conseguir enviar. O
REDCap recusa o envio, a pessoa tenta de novo, e desiste. No log: registro
1100 clicou em enviar 4 vezes no mesmo minuto; 1096 voltou 4 vezes entre
agosto e setembro; 713, 1264 e 2045 pararam exatamente nessa pagina depois
de responder as 51 barreiras.

O QUE ESTE SCRIPT FAZ

  1. baixa o dicionario de dados ATUAL pela API
  2. grava uma copia de seguranca intacta (para desfazer, se preciso)
  3. grava uma versao em que so muda a coluna "Required Field?" dos campos
     *_ctxspec — nada mais
  4. confere que a unica diferenca entre as duas e essa

NAO envia nada ao REDCap. O upload e feito por voce em
  Designer -> Data Dictionary -> Upload
porque ali o REDCap mostra a lista de mudancas antes de aplicar, e voce
confirma. Nenhum dado coletado e alterado: required so vale para o proximo
envio de pagina.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 corrige_ctxspec.py
"""

import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ordem e nomes exatos das colunas do dicionario de dados do REDCap
COLUNAS = [
    ("field_name", "Variable / Field Name"),
    ("form_name", "Form Name"),
    ("section_header", "Section Header"),
    ("field_type", "Field Type"),
    ("field_label", "Field Label"),
    ("select_choices_or_calculations", "Choices, Calculations, OR Slider Labels"),
    ("field_note", "Field Note"),
    ("text_validation_type_or_show_slider_number",
     "Text Validation Type OR Show Slider Number"),
    ("text_validation_min", "Text Validation Min"),
    ("text_validation_max", "Text Validation Max"),
    ("identifier", "Identifier?"),
    ("branching_logic", "Branching Logic (Show field only if...)"),
    ("required_field", "Required Field?"),
    ("custom_alignment", "Custom Alignment"),
    ("question_number", "Question Number (surveys only)"),
    ("matrix_group_name", "Matrix Group Name"),
    ("matrix_ranking", "Matrix Ranking?"),
    ("field_annotation", "Field Annotation"),
]


def grava(caminho, meta):
    with open(caminho, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow([rotulo for _, rotulo in COLUNAS])
        for f in meta:
            wr.writerow([f.get(chave, "") for chave, _ in COLUNAS])


def corrige(meta):
    novo, mudou = [], []
    for f in meta:
        g = dict(f)
        if g["field_name"].endswith("_ctxspec") and g.get("required_field") == "y":
            g["required_field"] = ""
            mudou.append(g["field_name"])
        novo.append(g)
    return novo, mudou


def main(meta=None):
    if meta is None:
        import redcap_aggregate as ag
        from cruza_lista_convite import carrega_env  # noqa: F401  (carrega o .env)
        print("baixando o dicionario de dados atual (uns 15 MB, pode demorar)...")
        meta = ag.api({"content": "metadata"})
    print(f"{len(meta)} campos")

    faltam = [c for c, _ in COLUNAS if c not in meta[0]]
    if faltam:
        sys.exit(f"ERRO: a API nao devolveu as colunas {faltam}; nao gero o "
                 f"arquivo para nao subir um dicionario incompleto.")
    extras = [c for c in meta[0] if c not in dict(COLUNAS)]
    if extras:
        sys.exit(f"ERRO: a API devolveu colunas que este script nao conhece: "
                 f"{extras}. Pare e me mostre isto antes de subir qualquer coisa.")

    novo, mudou = corrige(meta)
    if not mudou:
        print("Nenhum *_ctxspec esta obrigatorio. Nada a fazer.")
        return

    # a unica diferenca permitida: required_field dos *_ctxspec
    for a, b in zip(meta, novo):
        for chave, _ in COLUNAS:
            if a.get(chave) != b.get(chave):
                assert chave == "required_field" and a["field_name"].endswith("_ctxspec")
    assert len(meta) == len(novo)

    pasta = os.path.join(HERE, "dicionario")
    os.makedirs(pasta, exist_ok=True)
    carimbo = dt.datetime.now().strftime("%Y%m%d_%H%M")
    backup = os.path.join(pasta, f"dicionario_ORIGINAL_{carimbo}.csv")
    corrigido = os.path.join(pasta, f"dicionario_SEM_OBRIGATORIO_CTXSPEC_{carimbo}.csv")
    grava(backup, meta)
    grava(corrigido, novo)

    por_form = {}
    for nome in mudou:
        form = next(f["form_name"] for f in meta if f["field_name"] == nome)
        por_form[form] = por_form.get(form, 0) + 1
    print(f"\n{len(mudou)} campos deixam de ser obrigatorios:")
    for form, n in sorted(por_form.items()):
        print(f"  {form:<28} {n}")
    print("\nNenhuma outra celula mudou (conferido campo a campo).")
    print(f"\ncopia de seguranca : dicionario/{os.path.basename(backup)}")
    print(f"para subir         : dicionario/{os.path.basename(corrigido)}")
    print("\nNo REDCap: Designer -> Data Dictionary -> 'Upload' -> escolha o arquivo")
    print("'para subir'. Na tela de conferencia, o REDCap deve listar apenas campos")
    print("*_ctxspec como alterados. Se aparecer qualquer outro campo, NAO confirme.")


if __name__ == "__main__":
    main()
