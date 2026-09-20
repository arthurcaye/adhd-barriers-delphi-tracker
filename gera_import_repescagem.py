#!/usr/bin/env python3
"""
Monta o CSV que leva a segmentacao da repescagem para DENTRO do REDCap.

Por que isso existe: o REDCap nao consegue, sozinho, separar quem respondeu
26 barreiras de quem respondeu zero, nem juntar os varios registros de uma
mesma pessoa. Quem sabe disso e o repescagem.py. Entao gravamos o resultado
dele em dois campos novos, e a partir dai o proprio REDCap consegue trabalhar:
um alerta com a logica [grupo_repescagem] = "3" acha exatamente o grupo 3.

O truque que faz tudo funcionar: o alerta do REDCap pode ser disparado
"when conditional logic is TRUE during a data import". Como so o registro
ESCOLHIDO de cada pessoa recebe marcacao, a importacao dispara um e-mail por
pessoa - e nao um por registro, que era o problema da Participant List.

Campos que precisam existir antes (Online Designer, tipo Text Box):
  grupo_repescagem   recebe 1, 2 ou 3
  link_repescagem    recebe o link que retoma o questionario daquela pessoa

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 gera_import_repescagem.py
"""

import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

ENTRADAS = {
    "1": "repescagem_G1_nao_comecou.csv",
    "2": "repescagem_G2_de_1_a_25.csv",
    "3": "repescagem_G3_de_26_em_diante.csv",
}
SAIDA = os.path.join(HERE, "repescagem_para_importar.csv")

# Idiomas que ganham e-mail traduzido. Todo o resto cai no balde do ingles:
# sao linguas com pouquissima gente, e montar um alerta para 1 pessoa nao
# compensa. O QUESTIONARIO continua abrindo no idioma original de qualquer
# forma - isso aqui decide so a lingua da mensagem.
TRADUZIDOS = {"ptbr", "es", "zh"}


def bucket(idioma):
    return idioma if idioma in TRADUZIDOS else "en"


def main():
    linhas = []
    por_grupo = Counter()
    sem_link = []

    for grupo, nome in ENTRADAS.items():
        caminho = os.path.join(HERE, nome)
        if not os.path.exists(caminho):
            sys.exit(f"ERRO: {nome} nao encontrado.\n"
                     f"Rode antes: python3 repescagem.py --sem-consent --links")
        with open(caminho, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                link = (r.get("link_repescagem") or r.get("link_retomada") or "").strip()
                if not link:
                    sem_link.append(r["record_id"])
                    continue
                chave = grupo + bucket((r.get("idioma") or "").strip())
                linhas.append({
                    "record_id": r["record_id"],
                    "grupo_repescagem": chave,
                    "link_repescagem": link,
                })
                por_grupo[chave] += 1

    if sem_link:
        print(f"ATENCAO: {len(sem_link)} pessoas ficaram sem link e foram deixadas")
        print("de fora. Rode 'python3 repescagem.py --sem-consent --links' de novo")
        print("para completar (o cache pula o que ja deu certo).")
        print()

    # o mesmo registro nao pode aparecer duas vezes: seria e-mail repetido
    vistos = Counter(l["record_id"] for l in linhas)
    repetidos = [k for k, v in vistos.items() if v > 1]
    if repetidos:
        sys.exit(f"ERRO: {len(repetidos)} record_id repetidos no arquivo. "
                 f"Nao importe: isso mandaria e-mail duplicado.")

    campos = ["record_id", "grupo_repescagem", "link_repescagem"]

    def grava(caminho, dados):
        with open(caminho, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=campos)
            wr.writeheader()
            for l in sorted(dados, key=lambda x: int(x["record_id"])):
                wr.writerow(l)

    grava(SAIDA, linhas)

    # Um arquivo por grupo: a importacao e o gatilho do alerta, entao importar
    # tudo de uma vez dispararia os tres e-mails no mesmo instante. Separado,
    # cada grupo sai no dia que voce quiser.
    for g in ("3", "2", "1"):
        so_dele = [l for l in linhas if l["grupo_repescagem"].startswith(g)]
        grava(os.path.join(HERE, f"repescagem_importar_grupo{g}.csv"), so_dele)

    print(f"{len(linhas)} registros para importar\n")
    print("ALERTAS A CRIAR — um por combinacao abaixo.")
    print("A logica de cada um e:   [grupo_repescagem] = \"<valor>\"\n")
    print(f"   {'valor':<10} {'pessoas':>8}   idioma do e-mail")
    nomes = {"en": "ingles (inclui italiano, japones, russo, arabe, alemao,"
                   " coreano, frances)",
             "ptbr": "portugues", "es": "espanhol", "zh": "chines tradicional"}
    total_alertas = 0
    for g in ("3", "2", "1"):
        for lng in ("en", "ptbr", "es", "zh"):
            chave = g + lng
            n = por_grupo.get(chave, 0)
            if n:
                total_alertas += 1
                print(f"   {chave:<10} {n:>8}   {nomes[lng]}")
        print()
    print(f"   total de alertas a montar: {total_alertas}\n")
    print("ARQUIVOS (importe UM DE CADA VEZ, na ordem que quiser disparar):")
    for g in ("3", "2", "1"):
        n = sum(v for k, v in por_grupo.items() if k.startswith(g))
        print(f"   repescagem_importar_grupo{g}.csv   {n:>5}")
    print(f"   {os.path.basename(SAIDA)}    {len(linhas):>5}  (os tres de uma vez)")
    print()
    print("ANTES DE IMPORTAR, confira nesta ordem:")
    print("  1. os campos grupo_repescagem e link_repescagem existem no projeto")
    print("  2. os tres alertas ja estao criados, salvos e ATIVOS")
    print("     (a importacao e o gatilho: se o alerta nao existir na hora,")
    print("      nada e enviado e nao da para repetir sem refazer o campo)")
    print("  3. voce testou com UM registro seu antes de subir os 1875")
    print()
    print("O arquivo tem link pessoal de participante: nao versione.")


if __name__ == "__main__":
    main()
