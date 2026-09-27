#!/usr/bin/env python3
"""Backup completo do projeto 913 antes de mexer no dicionario.

Grava numa pasta datada (backup/AAAAMMDD_HHMM/):
  dados_<instrumento>.csv   todos os registros, um arquivo por instrumento
                            (codigos crus, como o REDCap guarda) — inclui
                            os instrumentos auxiliares (repescagem etc.)
  dicionario.csv            o dicionario de dados, no formato de upload
  instrumentos.json         lista de instrumentos
  projeto.json              informacoes do projeto
  MANIFESTO.txt             quantas linhas e colunas em cada arquivo

Por instrumento, e em CSV, porque exportar os 7.749 campos de uma vez em
JSON passaria de meio giga e o servidor corta.

ATENCAO: tem nome e e-mail de participante. A pasta backup/ esta no
.gitignore; nao copie para lugar publico.

So LE o REDCap. Nao grava nada.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 backup_redcap.py
"""

import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cruza_lista_convite  # noqa: E402,F401  (carrega o .env)
import redcap_aggregate as ag  # noqa: E402
from corrige_ctxspec import COLUNAS  # noqa: E402


def bruto(payload, tentativas=4):
    """POST que devolve texto (CSV), com repeticao em queda de conexao."""
    url = os.environ["REDCAP_API_URL"].strip()
    corpo = dict(payload, token=os.environ["REDCAP_API_TOKEN"].strip())
    data = urllib.parse.urlencode(corpo).encode()
    espera = 3
    for t in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, context=ag.ssl_context(), timeout=600) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError):
                sys.exit(f"ERRO HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
            if t == tentativas:
                sys.exit(f"ERRO de conexao apos {tentativas} tentativas: {e}")
            print(f"    conexao caiu ({type(e).__name__}); de novo em {espera}s")
            time.sleep(espera)
            espera *= 2


def conta(texto):
    linhas = list(csv.reader(io.StringIO(texto)))
    return max(len(linhas) - 1, 0), (len(linhas[0]) if linhas else 0)


def main():
    pasta = os.path.join(HERE, "backup", dt.datetime.now().strftime("%Y%m%d_%H%M"))
    os.makedirs(pasta, exist_ok=True)
    manifesto = []

    def salva(nome, texto):
        with open(os.path.join(pasta, nome), "w", encoding="utf-8", newline="") as fh:
            fh.write(texto)
        n, c = conta(texto) if nome.endswith(".csv") else (0, 0)
        linha = f"{nome:<40} {n:>6} linhas  {c:>5} colunas" if nome.endswith(".csv") \
            else f"{nome:<40} {len(texto):>10} bytes"
        manifesto.append(linha)
        print("  " + linha)

    print("projeto e instrumentos...")
    salva("projeto.json", json.dumps(ag.api({"content": "project"}), ensure_ascii=False, indent=1))
    instrumentos = ag.api({"content": "instrument"})
    salva("instrumentos.json", json.dumps(instrumentos, ensure_ascii=False, indent=1))

    print("dicionario...")
    meta = ag.api({"content": "metadata"})
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow([r for _, r in COLUNAS])
    for f in meta:
        wr.writerow([f.get(c, "") for c, _ in COLUNAS])
    salva("dicionario.csv", buf.getvalue())

    total_campos = 0
    print("dados, um instrumento por vez...")
    for ins in instrumentos:
        nome = ins["instrument_name"]
        texto = bruto({"content": "record", "format": "csv", "type": "flat",
                       "rawOrLabel": "raw", "forms": nome,
                       # sem isto o REDCap so poe o record_id no instrumento
                       # onde ele mora (language_router), e os demais
                       # arquivos ficam sem como ligar linha a registro
                       "fields": "record_id",
                       "exportSurveyFields": "true",
                       "exportDataAccessGroups": "false"})
        salva(f"dados_{nome}.csv", texto)
        total_campos += conta(texto)[1]

    manifesto.append(f"\n{len(meta)} campos no dicionario; "
                     f"{len(instrumentos)} instrumentos exportados")
    with open(os.path.join(pasta, "MANIFESTO.txt"), "w", encoding="utf-8") as fh:
        fh.write("Backup do projeto 913 — " + dt.datetime.now().isoformat(" ", "minutes")
                 + "\n\n" + "\n".join(manifesto) + "\n")
    print(f"\nbackup em: backup/{os.path.basename(pasta)}/")
    print("Tem dados de participante: nao versione, nao compartilhe.")


if __name__ == "__main__":
    main()
