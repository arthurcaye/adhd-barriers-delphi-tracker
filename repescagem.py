#!/usr/bin/env python3
"""
Monta a lista de repescagem: quem comecou o questionario e nao terminou.

REGRA CENTRAL, e a razao de este script existir em vez de um filtro simples:
uma MESMA PESSOA pode ter varios registros. O link publico do questionario
esta com save_and_return_code_bypass=1, entao toda vez que alguem reabre o
link o REDCap cria um registro NOVO em branco - foi assim que a Dra. Yunhye Oh
apareceu com um registro completo (3433) e um vazio (4163). Se filtrassemos
so por "registro incompleto", mandariamos cobranca para gente que ja terminou.

Entao o corte e por PESSOA (e-mail), nao por registro:
  1. junta todos os registros de cada e-mail, em qualquer um dos 12 idiomas
  2. se QUALQUER registro daquele e-mail estiver completo -> a pessoa sai da
     lista inteira, mesmo que tenha outros tres registros pela metade
  3. quem recusou o consentimento (consent=0) sai sempre, em qualquer cenario
  4. do que sobra, fica o registro MAIS ADIANTADO da pessoa (o que tem mais
     barreiras respondidas) - e para esse registro que o link de retomada
     deve apontar

Os tres grupos, por quanto a pessoa avancou:
  A  trio completo (importancia+viabilidade+recomendacao) em >=90% das
     barreiras, mas complete != 2. Ela respondeu tudo e nao apertou enviar.
  B  respondeu pelo menos uma barreira, mas menos que isso.
  C  consentiu (ou nem chegou la) e nao respondeu nenhuma barreira.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 repescagem.py                  # so monta as listas
  python3 repescagem.py --teste-link     # testa UM link de retomada e para
  python3 repescagem.py --links          # busca o link de todo mundo (lento)
  python3 repescagem.py --sem-consent    # inclui quem nao chegou a consentir

Nao grava NADA no REDCap. So le.
"""

import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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

# Mesma validacao usada no preenche_email_todos.py: precisa ser pelo menos tao
# rigorosa quanto a do REDCap, senao entra lixo na lista de disparo.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# instrumento -> (prefixo, campo de e-mail, campo de nome)
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

# A letra PRECISA entrar na captura. A barreira 12 e subdividida em b12a, b12b,
# b12c e b12d; capturando so o numero, as quatro viram a mesma chave "12" e o
# total cai de 51 para 48, o que jogaria gente do grupo A (quase terminou) para
# o grupo B por engano.
RE_IMP = re.compile(r"_b(\d+[a-z]?)_(?:imp|importance)$")
RE_FEAS = re.compile(r"_b(\d+[a-z]?)_(?:feas|feasibility)$")
RE_REC = re.compile(r"_b(\d+[a-z]?)_(?:rec|recommendation)$")


def api_texto(payload):
    """Igual ao ag.api(), mas devolve TEXTO CRU.

    Precisa existir separado porque content=surveyLink nao responde JSON:
    devolve a URL pelada. O ag.api() faria json.loads e morreria.
    """
    url = os.environ.get("REDCAP_API_URL", "").strip()
    token = os.environ.get("REDCAP_API_TOKEN", "").strip()
    body = dict(payload)
    body["token"] = token
    body.setdefault("format", "json")
    body.setdefault("returnFormat", "json")
    data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, context=ag.ssl_context(), timeout=120) as resp:
            return resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as err:
        detalhe = err.read().decode("utf-8", "replace")[:300]
        return f"__ERRO__ HTTP {err.code}: {detalhe}"
    except urllib.error.URLError as err:
        return f"__ERRO__ conexao: {getattr(err, 'reason', err)}"
    except Exception as err:
        # RemoteDisconnected e parentes nao sao URLError: sem este ramo, o
        # script morria no meio e perdia tudo o que ja tinha buscado.
        return f"__ERRO__ {type(err).__name__}: {err}"


CACHE_LINKS = os.path.join(HERE, "repescagem_links_cache.json")


def carrega_cache():
    if os.path.exists(CACHE_LINKS):
        try:
            with open(CACHE_LINKS, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def grava_cache(cache):
    with open(CACHE_LINKS, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


def link_de_retomada(record_id, instrumento, tentativas=4):
    """Link que RETOMA o registro existente, em vez de criar um novo.

    Com repeticao: o servidor derruba a conexao depois de algumas centenas de
    chamadas seguidas (RemoteDisconnected). Nao e erro de permissao nem de
    dado - e o REDCap se protegendo de rajada. Esperar e tentar de novo
    resolve; a espera dobra a cada tentativa.
    """
    espera = 2
    for tentativa in range(tentativas):
        resposta = api_texto({
            "content": "surveyLink",
            "record": str(record_id),
            "instrument": instrumento,
        })
        if not resposta.startswith("__ERRO__"):
            return resposta
        # 403 e permissao: repetir nao adianta, para na hora
        if "HTTP 403" in resposta:
            return resposta
        if tentativa < tentativas - 1:
            time.sleep(espera)
            espera *= 2
    return resposta


def campos_por_instrumento(meta):
    """Descobre, por instrumento, os campos de importancia/viabilidade/recomendacao.

    Guarda o NOME REAL de cada campo, nao so o numero da barreira. A versao
    anterior guardava o numero e remontava o nome como f"{prefixo}_b{n}_imp",
    o que funciona em onze instrumentos e falha no espanhol: la os campos se
    chamam es_b01_importance, es_b01_feasibility e es_b01_recommendation.
    O resultado foi contar zero barreira para todo respondente em espanhol e
    classificar os 195 como se nunca tivessem comecado.

    Ler o nome do dicionario em vez de deduzi-lo elimina a classe inteira de
    erro: se amanhã um instrumento novo usar outra convencao, isto continua
    funcionando.
    """
    imp = defaultdict(dict)
    feas = defaultdict(dict)
    rec = defaultdict(dict)
    for f in meta:
        nome, form = f["field_name"], f["form_name"]
        for regex, destino in ((RE_IMP, imp), (RE_FEAS, feas), (RE_REC, rec)):
            m = regex.search(nome)
            if m:
                destino[form][m.group(1)] = nome
                break
    return imp, feas, rec


def main():
    quer_links = "--links" in sys.argv
    teste_link = "--teste-link" in sys.argv
    incluir_sem_consent = "--sem-consent" in sys.argv

    print("lendo o dicionario de dados...")
    meta = ag.api({"content": "metadata"})
    imp_ids, feas_ids, rec_ids = campos_por_instrumento(meta)
    nomes_campos = {f["field_name"] for f in meta}

    # monta a lista de campos a pedir: e-mail, nome, consentimento, complete,
    # e os tres campos de cada barreira
    pedidos = {"record_id"}
    for form, (pref, email, nome) in FONTES.items():
        for c in (email, nome, f"{pref}_consent_agree", f"{form}_complete"):
            if c in nomes_campos or c.endswith("_complete"):
                pedidos.add(c)
        for mapa in (imp_ids, feas_ids, rec_ids):
            pedidos.update(mapa.get(form, {}).values())

    print(f"consultando {len(pedidos)} campos no REDCap (pode demorar)...")
    registros = ag.api({
        "content": "record", "type": "flat", "rawOrLabel": "raw",
        "exportSurveyFields": "true",
        "fields": ",".join(sorted(pedidos)),
    })
    print(f"{len(registros)} registros recebidos\n")

    # ---------------------------------------------------- passo 1: por registro
    por_registro = []
    for rec in registros:
        rid = str(rec.get("record_id", ""))
        for form, (pref, f_email, f_nome) in FONTES.items():
            email = str(rec.get(f_email, "") or "").strip()
            nome = str(rec.get(f_nome, "") or "").strip()
            consent = str(rec.get(f"{pref}_consent_agree", "") or "").strip()
            completo = str(rec.get(f"{form}_complete", "") or "").strip() == "2"

            d_imp = imp_ids.get(form, {})
            d_feas = feas_ids.get(form, {})
            d_rec = rec_ids.get(form, {})
            preenchido = lambda c: bool(str(rec.get(c, "") or "").strip())
            n_imp = sum(1 for c in d_imp.values() if preenchido(c))
            n_trio = sum(
                1 for b, c in d_imp.items()
                if preenchido(c)
                and b in d_feas and preenchido(d_feas[b])
                and b in d_rec and preenchido(d_rec[b])
            )
            total_b = len(d_imp) or 1

            # a pessoa tocou neste instrumento?
            if not (email or nome or consent or n_imp):
                continue

            por_registro.append({
                "record_id": rid,
                "form": form,
                "lang": pref,
                "email": email,
                "nome": nome,
                "consent": consent,
                "completo": completo,
                "n_imp": n_imp,
                "n_trio": n_trio,
                "total_b": total_b,
                "frac_trio": n_trio / total_b,
            })

    print(f"{len(por_registro)} pares registro/instrumento com algum rastro\n")

    # --------------------------------- passo 2: agrupa por PESSOA (e-mail)
    por_email = defaultdict(list)
    sem_email = 0
    for r in por_registro:
        chave = r["email"].lower()
        if not EMAIL_RE.match(r["email"]):
            sem_email += 1
            continue
        por_email[chave].append(r)

    completou_em_algum_lugar = set()
    recusou = set()
    for chave, lista in por_email.items():
        if any(r["completo"] for r in lista):
            completou_em_algum_lugar.add(chave)
        if any(r["consent"] == "0" for r in lista):
            recusou.add(chave)

    # --------------------------------- passo 3: escolhe o registro de cada um
    grupos = {"G1": [], "G2": [], "G3": []}
    descartes = Counter()

    for chave, lista in por_email.items():
        if chave in completou_em_algum_lugar:
            descartes["ja completou (em algum registro)"] += 1
            continue
        if chave in recusou:
            descartes["recusou o consentimento"] += 1
            continue

        consentiu = any(r["consent"] == "1" for r in lista)
        if not consentiu and not incluir_sem_consent:
            descartes["nunca chegou ao consentimento"] += 1
            continue

        # o registro mais adiantado: mais trios, depois mais importancias,
        # depois o mais recente (record_id maior)
        melhor = max(lista, key=lambda r: (r["n_trio"], r["n_imp"], int(r["record_id"] or 0)))

        # Corte do Rohde: G1 nao comecou, G2 fez de 1 a 25, G3 fez 26 ou mais.
        # Dentro do G3 ainda marcamos quem respondeu o trio em >=90% das
        # barreiras: essa gente literalmente so precisa apertar Enviar, e a
        # mensagem para ela pode dizer isso com todas as letras.
        if melhor["n_imp"] == 0:
            grupo = "G1"
        elif melhor["n_imp"] <= 25:
            grupo = "G2"
        else:
            grupo = "G3"

        grupos[grupo].append({
            "so_falta_enviar": "sim" if melhor["frac_trio"] >= 0.90 else "nao",
            "record_id": melhor["record_id"],
            "instrumento": melhor["form"],
            "idioma": melhor["lang"],
            "nome": melhor["nome"],
            "email": melhor["email"],
            "consentiu": "sim" if consentiu else "NAO",
            "barreiras_respondidas": melhor["n_imp"],
            "de": melhor["total_b"],
            "trio_completo": melhor["n_trio"],
            "outros_registros": len(lista) - 1,
            "link_retomada": "",
        })

    # --------------------------------- passo 4: link de retomada
    if teste_link:
        alvo = None
        for g in ("G3", "G2", "G1"):
            if grupos[g]:
                alvo = grupos[g][0]
                break
        if not alvo:
            sys.exit("nenhum registro na lista para testar.")
        print("TESTE DE LINK DE RETOMADA")
        print(f"  registro {alvo['record_id']} / {alvo['instrumento']}")
        resposta = link_de_retomada(alvo["record_id"], alvo["instrumento"])
        if resposta.startswith("__ERRO__"):
            print(f"  FALHOU: {resposta}")
            print("\n  Se for 403, o token nao tem direito de exportar survey link.")
            print("  Nesse caso o disparo tem de sair pelo proprio REDCap, que")
            print("  monta o link sozinho, ou alguem precisa liberar essa permissao.")
        else:
            print(f"  OK -> {resposta}")
            print("\n  Abra esse link no navegador e confirme que ele ABRE O")
            print("  QUESTIONARIO JA PREENCHIDO, em vez de comecar do zero.")
            print("  Se abrir preenchido, a repescagem pode usar links por pessoa.")
        return

    if quer_links:
        total = sum(len(v) for v in grupos.values())
        cache = carrega_cache()
        if cache:
            print(f"cache encontrado: {len(cache)} links ja buscados antes, "
                  f"serao reaproveitados")
        print(f"buscando {total} links de retomada...")
        print("(pode interromper com Ctrl+C: o progresso fica salvo e a proxima")
        print(" execucao continua de onde parou)")
        feitos = 0
        novos = 0
        falhas = []
        for g in ("G1", "G2", "G3"):
            for linha in grupos[g]:
                chave = f"{linha['record_id']}|{linha['instrumento']}"
                if chave in cache:
                    linha["link_retomada"] = cache[chave]
                else:
                    link = link_de_retomada(linha["record_id"], linha["instrumento"])
                    if link.startswith("__ERRO__"):
                        falhas.append((linha["record_id"], link[:60]))
                        linha["link_retomada"] = ""
                    else:
                        cache[chave] = link
                        linha["link_retomada"] = link
                    novos += 1
                    time.sleep(0.2)   # nao martelar o servidor
                    if novos % 25 == 0:
                        grava_cache(cache)
                feitos += 1
                if feitos % 50 == 0:
                    print(f"  {feitos}/{total}  (novos nesta rodada: {novos})")
        grava_cache(cache)
        print()
        if falhas:
            print(f"ATENCAO: {len(falhas)} links nao vieram, mesmo apos repetir.")
            print("Rode o comando de novo: o cache pula o que ja deu certo e")
            print("tenta so estes.")
            for rid, erro in falhas[:5]:
                print(f"   registro {rid}: {erro}")
            print()

    # --------------------------------- passo 5: grava
    rotulos = {
        "G1": "G1_nao_comecou",
        "G2": "G2_de_1_a_25",
        "G3": "G3_de_26_em_diante",
    }
    for g, rotulo in rotulos.items():
        caminho = os.path.join(HERE, f"repescagem_{rotulo}.csv")
        with open(caminho, "w", encoding="utf-8", newline="") as fh:
            campos = ["record_id", "instrumento", "idioma", "nome", "email",
                      "consentiu", "barreiras_respondidas", "de", "trio_completo",
                      "so_falta_enviar", "outros_registros", "link_retomada"]
            wr = csv.DictWriter(fh, fieldnames=campos)
            wr.writeheader()
            for linha in sorted(grupos[g], key=lambda x: (x["idioma"], -x["barreiras_respondidas"])):
                wr.writerow(linha)

    linhas = ["LISTA DE REPESCAGEM — painel Delphi de barreiras", ""]
    linhas.append("Corte por PESSOA (e-mail), nao por registro: quem tem qualquer")
    linhas.append("registro completo sai da lista inteira.")
    linhas.append("")
    linhas.append(f"  e-mails distintos encontrados      {len(por_email):>6}")
    for motivo, n in descartes.most_common():
        linhas.append(f"  fora: {motivo:<32} {n:>6}")
    linhas.append(f"  registros sem e-mail valido        {sem_email:>6}  (nao contactaveis)")
    linhas.append("")
    so_enviar = sum(1 for x in grupos["G3"] if x["so_falta_enviar"] == "sim")
    linhas.append("GRUPOS (numeracao do Rohde)")
    linhas.append(f"  G1  nao respondeu nenhuma barreira {len(grupos['G1']):>6}")
    linhas.append(f"  G2  respondeu de 1 a 25            {len(grupos['G2']):>6}")
    linhas.append(f"  G3  respondeu 26 ou mais           {len(grupos['G3']):>6}")
    linhas.append(f"      destes, so falta apertar Enviar{so_enviar:>6}")
    linhas.append(f"      TOTAL A CONTATAR               {sum(len(v) for v in grupos.values()):>6}")
    linhas.append("")
    linhas.append("POR IDIOMA (para saber quantas traducoes de cada e-mail)")
    linhas.append("")
    for g in ("G1", "G2", "G3"):
        c = Counter(x["idioma"] for x in grupos[g])
        if c:
            resumo = "  ".join(f"{k}:{v}" for k, v in c.most_common())
            linhas.append(f"  {g}  {resumo}")

    resumo_path = os.path.join(HERE, "repescagem_resumo.txt")
    with open(resumo_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")

    print("\n".join(linhas))
    print()
    print(f"resumo -> repescagem_resumo.txt  (so contagens, pode versionar)")
    for g, rotulo in rotulos.items():
        print(f"grupo {g} -> repescagem_{rotulo}.csv  ({len(grupos[g])} pessoas)")
    print("\nOs CSV tem nome e e-mail de participante: NAO versione.")
    if not quer_links:
        print("Rode --teste-link antes de qualquer disparo, para confirmar que o")
        print("link de retomada funciona. Sem isso a repescagem cria duplicatas.")


if __name__ == "__main__":
    main()
