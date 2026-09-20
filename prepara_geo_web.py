#!/usr/bin/env python3
"""
Enxuga a geometria dos paises para o mapa do painel online.

O arquivo do Natural Earth tem 819 KB, quase todo desperdicio para o nosso
uso: dezenas de propriedades por pais (codigo ISO, PIB, populacao, nome em
diversas linguas) e coordenadas com 15 casas decimais. Precisamos do nome e
do contorno, e nada mais.

Duas reducoes:
  1. joga fora toda propriedade menos o nome
  2. arredonda a coordenada para 2 casas decimais

Duas casas decimais em grau equivalem a cerca de 1 km. Num mapa onde o
planeta inteiro cabe em 1000 pixels, cada pixel vale uns 40 km - ou seja,
a precisao descartada e quarenta vezes menor que o menor detalhe visivel.

Roda uma vez. O resultado vai para o repositorio e e servido junto da pagina.

Uso:
  python3 prepara_geo_web.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(HERE, "world_countries.geojson")
SAIDA = os.path.join(HERE, "world.geojson")

CASAS = 2


def nome_do(props):
    for chave in ("ADMIN", "NAME_LONG", "NAME", "name", "admin", "SOVEREIGNT"):
        if props.get(chave):
            return props[chave]
    return ""


def arredonda(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], CASAS), round(coords[1], CASAS)]
    return [arredonda(c) for c in coords]


def sem_repetidos(anel):
    """Depois de arredondar, pontos vizinhos viram identicos. Remove-los
    encolhe o arquivo sem mudar o desenho."""
    saida = [anel[0]]
    for p in anel[1:]:
        if p != saida[-1]:
            saida.append(p)
    if len(saida) >= 3 and saida[0] != saida[-1]:
        saida.append(saida[0])
    return saida if len(saida) >= 4 else None


def limpa(geom):
    if geom["type"] == "Polygon":
        aneis = [sem_repetidos(a) for a in arredonda(geom["coordinates"])]
        aneis = [a for a in aneis if a]
        return {"type": "Polygon", "coordinates": aneis} if aneis else None
    if geom["type"] == "MultiPolygon":
        polis = []
        for poli in arredonda(geom["coordinates"]):
            aneis = [sem_repetidos(a) for a in poli]
            aneis = [a for a in aneis if a]
            if aneis:
                polis.append(aneis)
        return {"type": "MultiPolygon", "coordinates": polis} if polis else None
    return None


def main():
    if not os.path.exists(ENTRADA):
        raise SystemExit(
            f"ERRO: {os.path.basename(ENTRADA)} nao encontrado.\n"
            "Rode antes: python3 mapa_mundi.py  (ele baixa a geometria)")

    geo = json.load(open(ENTRADA, encoding="utf-8"))
    saida = {"type": "FeatureCollection", "features": []}
    descartados = []

    for f in geo["features"]:
        nome = nome_do(f["properties"])
        if not nome or nome == "Antarctica":
            descartados.append(nome or "(sem nome)")
            continue
        g = limpa(f.get("geometry") or {})
        if not g:
            descartados.append(nome)
            continue
        saida["features"].append(
            {"type": "Feature", "properties": {"n": nome}, "geometry": g})

    # separator sem espaco: economiza um byte por virgula, e sao milhares
    with open(SAIDA, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, separators=(",", ":"))

    antes = os.path.getsize(ENTRADA)
    depois = os.path.getsize(SAIDA)
    print(f"paises mantidos   : {len(saida['features'])}")
    if descartados:
        print(f"descartados       : {', '.join(descartados)}")
    print(f"antes             : {antes/1024:>7.0f} KB")
    print(f"depois            : {depois/1024:>7.0f} KB")
    print(f"reducao           : {100*(1-depois/antes):>7.1f}%")
    print(f"\ngerado: {os.path.basename(SAIDA)}  (versione este, "
          f"nao o world_countries.geojson)")


if __name__ == "__main__":
    main()
