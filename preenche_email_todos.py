#!/usr/bin/env python3
"""
Diagnostica e preenche o campo email_todos nos registros antigos.

Por que existe: a regra H do Data Quality so enxerga campos do tipo "calc".
O @CALCTEXT e uma action tag num campo de texto, entao a regra devolve zero
mesmo quando a tag esta funcionando, e nao preenche nada retroativamente.

O script faz duas coisas, nessa ordem:

  DIAGNOSTICO (sempre)  diz quantos registros ja tem email_todos preenchido.
                        Se der zero em TODOS, a action tag nao esta ativa e
                        nao adianta preencher o passado: o futuro tambem nao
                        vai preencher. Nesse caso, pare e resolva a tag antes.

  GRAVACAO (so com --gravar)  escreve email_todos nos registros que tem e-mail
                        em algum idioma e estao com o campo vazio.

Sem --gravar ele nao altera NADA: so mostra o que faria.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 preenche_email_todos.py            # so olha
  python3 preenche_email_todos.py --gravar   # grava de verdade
"""

import csv
import json
import os
import re
import sys

# Precisa ser pelo menos tao rigorosa quanto a validacao do REDCap, senao a
# importacao falha inteira por causa de uma linha. A versao anterior aceitava
# virgula no nome do usuario ("geno,tropa@gmail.com") e o REDCap recusou.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def sugere_correcao(valor):
    """Tenta consertar erros de digitacao obvios. NAO aplica nada: so sugere.

    Os casos vistos de verdade: espaco sobrando ("dramenel@ gmail.com"),
    virgula no lugar do ponto ("...@gmail,com"), cerquilha no lugar da arroba
    ("Hinshaw#berkeley.edu") e e-mail dentro de <> com nome na frente.
    """
    c = (valor or "").strip()
    m = re.search(r"<\s*([^>]+?)\s*>", c)     # "Nome" <email@x.org>
    if m:
        c = m.group(1)
    c = c.replace(" ", "")
    if "@" not in c and "#" in c:
        c = c.replace("#", "@", 1)
    if EMAIL_RE.match(c):
        return c
    c2 = c.replace(",", ".")
    if EMAIL_RE.match(c2):
        return c2
    return None

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

DESTINO = "email_todos"
LOTE = 200


def main():
    gravar = "--gravar" in sys.argv

    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    campos = [s["email_field"] for s in cfg["sources"]]

    meta = ag.api({"content": "metadata"})
    nomes = {f["field_name"] for f in meta}
    if DESTINO not in nomes:
        sys.exit(f"ERRO: o campo '{DESTINO}' nao existe no projeto.\n"
                 f"Crie-o no Online Designer antes de rodar isto.")
    faltando = [c for c in campos if c not in nomes]
    if faltando:
        sys.exit("ERRO: campos de e-mail nao encontrados: " + ", ".join(faltando))

    print(f"lendo {len(campos)} campos de e-mail + {DESTINO}...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "fields": ",".join(["record_id", DESTINO] + campos),
    })
    print(f"{len(registros)} registros\n")

    ja_tem = 0
    sem_email = 0
    a_gravar = []
    divergentes = []
    invalidos = []

    for rec in registros:
        atual = str(rec.get(DESTINO, "") or "").strip()
        esperado = ""
        for c in campos:
            v = str(rec.get(c, "") or "").strip()
            if v:
                esperado = v
                break
        if atual:
            ja_tem += 1
            if esperado and atual.lower() != esperado.lower():
                divergentes.append((rec.get("record_id"), atual, esperado))
            continue
        if not esperado:
            sem_email += 1
            continue
        # O campo email_todos tem validacao de e-mail no REDCap: mandar um
        # valor invalido faz a importacao inteira falhar. Entao so vai o que
        # e e-mail de verdade; o resto sai numa lista separada para revisao.
        if not EMAIL_RE.match(esperado):
            invalidos.append((rec.get("record_id"), esperado, sugere_correcao(esperado)))
            continue
        a_gravar.append({"record_id": rec.get("record_id"), DESTINO: esperado})

    print("DIAGNOSTICO")
    print(f"  ja preenchidos          : {ja_tem}")
    print(f"  vazios COM e-mail       : {len(a_gravar)}   <- estes seriam gravados")
    print(f"  vazios SEM e-mail nenhum: {sem_email}   (nada a fazer)")
    if invalidos:
        recuperaveis = [x for x in invalidos if x[2]]
        print(f"  texto que NAO e e-mail    : {len(invalidos)}   (fora da importacao)")
        print(f"     destes, com correcao obvia possivel: {len(recuperaveis)}")
    if divergentes:
        print(f"  divergentes             : {len(divergentes)}  (ja tem valor diferente do esperado)")
        for rid, a, e in divergentes[:5]:
            print(f"      registro {rid}: tem {a!r}, esperado {e!r}")
    print()

    if ja_tem == 0:
        print("ATENCAO: nenhum registro tem o campo preenchido.")
        print("Se voce ja respondeu um questionario de teste depois de criar o campo,")
        print("isso indica que o @CALCTEXT NAO esta ativo nesta versao do REDCap.")
        print("Preencher o passado nao resolveria: as respostas novas tambem viriam")
        print("vazias. Confirme com um teste antes de gravar.")
        print()

    if not a_gravar:
        print("nada a gravar.")
        return

    # --aplicar-sugestoes: dobra as correcoes obvias dentro do arquivo de
    # importacao, em vez de deixa-las so na lista de revisao. Cada correcao
    # aplicada e impressa, para ficar registrado o que foi alterado.
    if "--aplicar-sugestoes" in sys.argv and invalidos:
        aplicadas = []
        restantes = []
        for rid, val, sug in invalidos:
            if sug:
                a_gravar.append({"record_id": rid, DESTINO: sug})
                aplicadas.append((rid, val, sug))
            else:
                restantes.append((rid, val, sug))
        invalidos = restantes
        if aplicadas:
            print(f"CORRECOES APLICADAS ({len(aplicadas)}):")
            for rid, val, sug in sorted(aplicadas, key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
                alerta = ""
                if re.search(r"@[A-Za-z0-9.-]*(gmaikl|gmai\.|gmial|hotmial)", sug, re.I):
                    alerta = "   <<< dominio parece ter erro, vai voltar"
                if val.count(" ") >= 1 and " " in val.split("@")[0].strip():
                    alerta = alerta or "   <<< havia espaco no nome do usuario, confirme"
                print(f"   registro {rid:>5}: {val[:40]:42} -> {sug}{alerta}")
            print()

    if "--csv" in sys.argv:
        destino = os.path.join(HERE, "email_todos_para_importar.csv")
        with open(destino, "w", encoding="utf-8", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["record_id", DESTINO])
            for r in a_gravar:
                wr.writerow([r["record_id"], r[DESTINO]])
        print(f"CSV gerado: {os.path.basename(destino)}  ({len(a_gravar)} linhas)")
        if invalidos:
            rev = os.path.join(HERE, "email_invalidos_para_revisar.csv")
            with open(rev, "w", encoding="utf-8", newline="") as fh:
                wr = csv.writer(fh)
                wr.writerow(["record_id", "valor_digitado", "sugestao", "acao"])
                for rid, val, sug in sorted(invalidos, key=lambda x: (x[2] is None, x[0])):
                    wr.writerow([rid, val, sug or "",
                                 "revisar e corrigir no REDCap" if sug else "nao e e-mail"])
            print(f"CSV de revisao: {os.path.basename(rev)}  ({len(invalidos)} linhas)")
            print("   as linhas com sugestao sao e-mails reais com erro de digitacao;")
            print("   corrija no REDCap se concordar, e rode este script de novo.")
        print()
        print("Para subir no REDCap, sem precisar de permissao de API:")
        print("  1. menu Data Import Tool")
        print("  2. escolha o arquivo e deixe o formato como CSV")
        print("  3. o REDCap mostra uma previa; confira que so a coluna")
        print(f"     {DESTINO} aparece marcada para alteracao")
        print("  4. confirme a importacao")
        print()
        print("O arquivo tem e-mail de participante: nao versione, e apague depois.")
        return

    if not gravar:
        print(f"MODO SEGURO: nada foi alterado.")
        print(f"Opcoes:")
        print(f"  --csv      gera planilha para subir pelo Data Import Tool (nao"
              f" precisa de permissao de API)")
        print(f"  --gravar   grava direto pela API (precisa de API Import/Update)")
        return

    print(f"gravando {len(a_gravar)} registros em lotes de {LOTE}...")
    print("(so o campo email_todos e enviado; nenhum outro campo e tocado)")
    total = 0
    for i in range(0, len(a_gravar), LOTE):
        lote = a_gravar[i:i + LOTE]
        resp = ag.api({
            "content": "record", "action": "import", "type": "flat",
            "overwriteBehavior": "normal",      # nunca apaga valor existente
            "data": json.dumps(lote),
        })
        n = resp.get("count", 0) if isinstance(resp, dict) else 0
        total += n
        print(f"  lote {i//LOTE + 1}: {n} registros")
    print(f"\npronto: {total} registros atualizados")


if __name__ == "__main__":
    main()
