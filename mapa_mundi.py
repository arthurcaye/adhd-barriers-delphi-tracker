#!/usr/bin/env python3
"""
Mapa-mundi das respostas do painel Delphi, em padrao de publicacao.

Gera PDF vetorial (o que o Lancet pede), SVG editavel e PNG 600 dpi.

Decisoes de desenho, e por que:

  PROJECAO ROBINSON. E a convencao para mapa tematico mundial em periodico
  medico. Mercator exagera grosseiramente a area em latitudes altas - num
  mapa de participacao, faria Noruega e Canada parecerem dominar o estudo.
  Robinson e um compromisso: nao preserva area nem angulo perfeitamente, mas
  nao distorce nenhum dos dois a ponto de enganar a leitura.

  CLASSES, NAO GRADIENTE CONTINUO. A distribuicao e muito assimetrica (Brasil
  com 75, e uma cauda longa de paises com 1). Num gradiente continuo, tudo
  abaixo de 20 vira a mesma cor e o leitor perde 40 paises. As faixas tornam
  visivel a diferenca entre 1 e 10 respostas, que e justamente onde esta a
  questao de representatividade.

  CINZA PARA AUSENCIA DE DADO. Branco confunde com zero e com o fundo. Cinza
  claro diz "nao participou" sem competir com a escala de cor.

Uso:
  cd ~/Downloads/delphi_emails/delphi_dashboard
  python3 redcap_aggregate.py     # primeiro, para o data.json estar atual
  python3 mapa_mundi.py

  --online   usa o data.json publicado no GitHub Pages em vez do local
"""

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_GEO = os.path.join(HERE, "world_countries.geojson")
PUBLICADO = "https://arthurcaye.github.io/adhd-barriers-delphi-tracker/data.json"

# Fontes da geometria, em ordem de preferencia. Natural Earth 110m e o padrao
# de facto para mapa mundial em publicacao: generalizado o suficiente para
# nao pesar, detalhado o suficiente para os paises serem reconheciveis.
FONTES_GEO = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson",
    "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/"
    "ne_110m_admin_0_countries.geojson",
]

# Nome no nosso config.json -> nome no Natural Earth.
# So entram os que divergem; o resto casa direto.
EQUIV = {
    "United States": "United States of America",
    "South Korea": "South Korea",
    "Russia": "Russia",
    "Czech Republic": "Czechia",
    "Serbia": "Republic of Serbia",
    "Tanzania": "United Republic of Tanzania",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Dominican Republic": "Dominican Republic",
    "North Macedonia": "North Macedonia",
    "Ivory Coast": "Ivory Coast",
    "Guinea-Bissau": "Guinea-Bissau",
}

# Territorios que nao existem como unidade separada no Natural Earth 110m.
# Nao e erro: na escala mundial eles sao pequenos demais para virar poligono
# proprio. Precisam ser declarados na legenda do artigo.
SEM_POLIGONO_NO_110M = {"Hong Kong", "Singapore", "Macau"}

NAO_E_PAIS = "— resposta regional, sem país —"


def baixa_geometria():
    if os.path.exists(CACHE_GEO) and os.path.getsize(CACHE_GEO) > 100_000:
        print(f"geometria em cache: {os.path.basename(CACHE_GEO)}")
        return
    ultimo = None
    for url in FONTES_GEO:
        try:
            print(f"baixando geometria de {url.split('/')[2]}...")
            with urllib.request.urlopen(url, timeout=120) as r:
                dados = r.read()
            if len(dados) < 100_000:
                raise ValueError("arquivo pequeno demais, provavelmente erro")
            with open(CACHE_GEO, "wb") as fh:
                fh.write(dados)
            print(f"  ok, {len(dados)//1024} KB guardados em "
                  f"{os.path.basename(CACHE_GEO)}")
            return
        except Exception as e:
            ultimo = e
            print(f"  falhou: {type(e).__name__}: {e}")
    sys.exit(
        "\nNao consegui baixar a geometria dos paises.\n"
        "Baixe manualmente este arquivo e salve nesta pasta como "
        "world_countries.geojson:\n  " + FONTES_GEO[0] + f"\n\n(ultimo erro: {ultimo})"
    )


def carrega_contagens(online):
    if online:
        print("lendo o data.json publicado...")
        with urllib.request.urlopen(PUBLICADO, timeout=60) as r:
            d = json.load(r)
    else:
        caminho = os.path.join(HERE, "data.json")
        if not os.path.exists(caminho):
            sys.exit("ERRO: data.json nao encontrado. Rode antes: "
                     "python3 redcap_aggregate.py")
        d = json.load(open(caminho, encoding="utf-8"))
    contagens = {}
    for linha in d["rows"]:
        pais = linha["country"]
        if pais == NAO_E_PAIS:
            continue          # nao e pais, nao pode virar poligono
        contagens[pais] = linha["total"]
    return contagens, d


# ------------------------------------------------------------- Robinson
# Tabela oficial de Robinson: fatores de comprimento do paralelo (X) e de
# distancia do equador (Y) a cada 5 graus de latitude. Entre os pontos,
# interpolacao linear - e assim que a projecao e definida na pratica, ela nao
# tem forma fechada.
_ROB_X = [1.0000, 0.9986, 0.9954, 0.9900, 0.9822, 0.9730, 0.9600, 0.9427,
          0.9216, 0.8962, 0.8679, 0.8350, 0.7986, 0.7597, 0.7186, 0.6732,
          0.6213, 0.5722, 0.5322]
_ROB_Y = [0.0000, 0.0620, 0.1240, 0.1860, 0.2480, 0.3100, 0.3720, 0.4340,
          0.4958, 0.5571, 0.6176, 0.6769, 0.7346, 0.7903, 0.8435, 0.8936,
          0.9394, 0.9761, 1.0000]


def robinson(lon, lat):
    import numpy as np
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    a = np.abs(lat) / 5.0
    i = np.clip(a.astype(int), 0, 17)
    t = a - i
    x = (np.take(_ROB_X, i) + t * (np.take(_ROB_X, i + 1) - np.take(_ROB_X, i)))
    y = (np.take(_ROB_Y, i) + t * (np.take(_ROB_Y, i + 1) - np.take(_ROB_Y, i)))
    return 0.8487 * x * np.radians(lon), 1.3523 * np.sign(lat) * y


def main():
    online = "--online" in sys.argv
    baixa_geometria()
    contagens, bruto = carrega_contagens(online)

    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Patch
    from matplotlib.path import Path
    from matplotlib.collections import PatchCollection

    # Arial e a preferida em periodico medico, mas nao existe em todo
    # sistema. A lista degrada para Helvetica e depois para a fonte
    # padrao do matplotlib, sem quebrar a geracao.
    FAMILIA = ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]

    geo = json.load(open(CACHE_GEO, encoding="utf-8"))

    def nome_do(props):
        for chave in ("ADMIN", "NAME_LONG", "NAME", "name", "admin", "SOVEREIGNT"):
            if props.get(chave):
                return props[chave]
        return ""

    nomes_geo = {nome_do(f["properties"]) for f in geo["features"]}

    # ---- casamento de nomes. E aqui que mapas tematicos erram em silencio:
    # um pais que nao casa some do mapa sem aviso nenhum.
    mapeado, nao_casou = {}, []
    for pais, n in contagens.items():
        alvo = EQUIV.get(pais, pais)
        if alvo in nomes_geo:
            mapeado[alvo] = mapeado.get(alvo, 0) + n
        else:
            nao_casou.append((pais, n))

    FAIXAS = [(1, 4), (5, 9), (10, 24), (25, 49), (50, 10**9)]
    ROTULOS = ["1–4", "5–9", "10–24", "25–49", "≥50"]
    CORES = ["#D6E5EA", "#A6C8D3", "#6FA3B4", "#3B7A8E", "#1D4E5E"]
    SEM_DADO, BORDA = "#F2F2F2", "#FFFFFF"

    def cor(n):
        for (lo, hi), c in zip(FAIXAS, CORES):
            if lo <= n <= hi:
                return c
        return SEM_DADO

    fig, ax = plt.subplots(figsize=(11.7, 6.3))
    patches, cores = [], []

    for f in geo["features"]:
        nome = nome_do(f["properties"])
        if nome == "Antarctica":
            continue                      # convencao em mapa tematico global
        n = mapeado.get(nome, 0)
        c = cor(n) if n else SEM_DADO
        g = f["geometry"]
        if not g:
            continue
        # GeoJSON: Polygon e [anel_externo, buraco, buraco...]; MultiPolygon e
        # uma lista desses. Normalizamos para uma lista de poligonos, cada um
        # com seu externo na posicao 0.
        if g["type"] == "Polygon":
            poligonos = [g["coordinates"]]
        elif g["type"] == "MultiPolygon":
            poligonos = g["coordinates"]
        else:
            continue

        for poly in poligonos:
            if not poly:
                continue
            externo = np.asarray(poly[0], dtype=float)
            if externo.ndim != 2 or len(externo) < 3:
                continue

            def area_com_sinal(a):
                x, y = a[:, 0], a[:, 1]
                return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))

            verts, codes = [], []

            def acrescenta(anel):
                X, Y = robinson(anel[:, 0], anel[:, 1])
                pts = np.column_stack([X, Y])
                verts.extend(pts.tolist())
                codes.extend([Path.MOVETO] + [Path.LINETO] * (len(pts) - 1))

            acrescenta(externo)
            sinal_ext = area_com_sinal(externo)
            # Buracos: o preenchimento por regra nonzero so abre o buraco se o
            # anel interno girar no sentido oposto ao externo. Muito arquivo
            # nao respeita essa convencao, entao invertemos quando preciso.
            # Sem isso, o Lesoto sai pintado com a cor da Africa do Sul.
            for buraco in poly[1:]:
                arr = np.asarray(buraco, dtype=float)
                if arr.ndim != 2 or len(arr) < 3:
                    continue
                if area_com_sinal(arr) * sinal_ext > 0:
                    arr = arr[::-1]
                acrescenta(arr)

            patches.append(PathPatch(Path(np.asarray(verts), codes)))
            cores.append(c)

    col = PatchCollection(patches, facecolor=cores, edgecolor=BORDA,
                          linewidths=0.3)
    ax.add_collection(col)

    # moldura do globo, para o mapa nao "flutuar"
    lon_b = np.concatenate([np.full(180, -180), np.linspace(-180, 180, 360),
                            np.full(180, 180), np.linspace(180, -180, 360)])
    lat_b = np.concatenate([np.linspace(-90, 90, 180), np.full(360, 90),
                            np.linspace(90, -90, 180), np.full(360, -90)])
    bx, by = robinson(lon_b, lat_b)
    ax.plot(bx, by, color="#BFBFBF", linewidth=0.6, zorder=0)

    ax.set_aspect("equal")
    ax.set_xlim(bx.min() * 1.02, bx.max() * 1.02)
    ax.set_ylim(by.min() * 1.06, by.max() * 1.10)
    ax.axis("off")

    total = bruto["totals"]["responses"]
    n_paises = len([1 for v in contagens.values() if v])
    # Titulo e subtitulo no nivel da FIGURA, nao do eixo: com set_title mais
    # um text() no topo do eixo, os dois se sobrepoem.
    fig.text(0.015, 0.975, "Completed Delphi responses by country",
             fontsize=12.5, color="#22303A", fontfamily=FAMILIA,
             va="top", ha="left")
    fig.text(0.015, 0.930,
             f"{total} responses from {n_paises} countries",
             fontsize=9, color="#6B7C86", fontfamily=FAMILIA,
             va="top", ha="left")

    leg = [Patch(facecolor=c, edgecolor=BORDA, label=r)
           for c, r in zip(CORES, ROTULOS)]
    leg.append(Patch(facecolor=SEM_DADO, edgecolor=BORDA, label="No responses"))
    ax.legend(handles=leg, loc="lower left", ncol=6, frameon=False,
              fontsize=8.5, handlelength=1.5, handleheight=1.0,
              columnspacing=1.2, bbox_to_anchor=(0, -0.04),
              prop={"family": FAMILIA, "size": 8.5})

    fig.tight_layout()
    saidas = []
    for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 600})):
        caminho = os.path.join(HERE, f"mapa_respostas_delphi.{ext}")
        fig.savefig(caminho, bbox_inches="tight", facecolor="white", **kw)
        saidas.append(caminho)
    plt.close(fig)

    # ---------------------------------------------------------- conferencia
    soma_mapa = sum(mapeado.values())
    soma_linhas = sum(r["total"] for r in bruto["rows"])
    regional = next((r["total"] for r in bruto["rows"]
                     if r["country"] == NAO_E_PAIS), 0)
    print()
    print("CONFERENCIA")
    print(f"  respondentes (pessoas)             {total:>5}")
    print(f"  paises com ao menos uma resposta   {n_paises:>5}")
    print(f"  soma das contagens por pais        {soma_linhas:>5}")
    print(f"  desenhado no mapa                  {soma_mapa:>5}")
    print(f"  nao desenhado                      {soma_linhas - soma_mapa:>5}")
    if regional:
        print(f"     resposta regional, sem pais      {regional:>2}")
    print()
    print(f"  A soma por pais ({soma_linhas}) e maior que o numero de")
    print(f"  respondentes ({total}) porque a pergunta permite nomear mais de")
    print( "  um pais, e cada pessoa e contada em cada pais que indicou.")
    print( "  ISSO PRECISA CONSTAR NA LEGENDA DA FIGURA.")
    if nao_casou:
        print(f"\n  {len(nao_casou)} pais(es) sem poligono correspondente:")
        for p, n in sorted(nao_casou, key=lambda x: -x[1]):
            nota = ("  (territorio pequeno; nao existe como unidade separada "
                    "na escala 1:110m)" if p in SEM_POLIGONO_NO_110M else
                    "  <-- VERIFIQUE: nome pode precisar de equivalencia")
            print(f"     {p:<28} {n:>3}{nota}")
        print("\n  Declare na legenda da figura as respostas nao representadas.")
    print()
    for s in saidas:
        print(f"gerado: {os.path.basename(s)}")
    print("\nPara o Lancet, envie o PDF ou o SVG (vetorial). O PNG e so para")
    print("conferencia rapida e para colar em e-mail e apresentacao.")


if __name__ == "__main__":
    main()
