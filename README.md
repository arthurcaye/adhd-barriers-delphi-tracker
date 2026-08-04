# Painel público de acompanhamento — Delphi de barreiras ao cuidado em TDAH

Link público que mostra, em tempo quase real, **quantas respostas já entraram por país e por categoria de participante** (as 5 categorias da figura: clinical practitioners, academic researchers, policy & system leaders, advocacy & lived experience, equity specialists).

Serve tanto para você acompanhar quanto para mandar aos co-autores — cada um vê como o país dele está.

---

## Como funciona

```
REDCap (HCPA)  ──API──▶  redcap_aggregate.py  ──▶  data.json  ──▶  index.html
   dados brutos          roda no servidor         só contagens      página pública
                         (token fica aqui)        (sem dado pessoal)
```

O ponto central: **o token da API nunca vai para o navegador**. O script roda num servidor (ou numa GitHub Action), lê os dados, calcula só as contagens agregadas e grava um `data.json` pequeno. A página pública lê esse JSON. Nenhum registro individual, nome ou texto livre é publicado.

---

## Arquivos

| Arquivo | O que é |
|---|---|
| `run.sh` | **Atalho para rodar tudo.** Lê o `.env` e chama o Python. |
| `preview.sh` | Sobe um servidor local e abre o painel no navegador. |
| `.env` | Onde vai o token. Já criado, só falta preencher. Nunca é versionado. |
| `redcap_aggregate.py` | Puxa os dados do REDCap e gera o `data.json`. Só usa a biblioteca padrão do Python — nada de `pip install`. |
| `config.json` | Configuração ativa (nomes dos campos, mapeamento de categorias). Já vem com um esqueleto. |
| `config.example.json` | Cópia de referência do modelo, caso você queira recomeçar. |
| `index.html` | A página do painel. Arquivo único, sem dependências externas. |
| `data.json` | Saída do script. **Agora contém dados falsos de demonstração** (aparece um aviso laranja na página); some na primeira execução real. |
| `.github/workflows/update-dashboard.yml` | Atualiza tudo de 15 em 15 min se você usar GitHub Pages. |

Não precisa instalar nada: o script usa só a biblioteca padrão do Python 3, que já vem no macOS. Se der "python3 não encontrado", rode `xcode-select --install`.

---

## Ver o painel agora (com os dados de demonstração)

```bash
cd ~/Downloads/delphi_emails/delphi_dashboard
./preview.sh
```

Abre em `http://localhost:8765`. Ctrl+C para parar.

> Dar duplo clique no `index.html` **não** funciona: em `file://` o navegador bloqueia a leitura do `data.json` e a tabela fica vazia. Por isso o `preview.sh`.

---

## Passo a passo

### 1. Pedir o token da API

No REDCap: **API** no menu lateral do projeto → *Request API token*. Peça permissão de **API Export** (só leitura — não precisa de import).

### 2. Colar o token

Abra o arquivo `.env` e substitua `cole_o_token_aqui` pelo token. Só isso.

### 3. Descobrir os nomes dos campos

Os nomes de variável do seu projeto eu não tenho como saber daqui. Rode:

```bash
./run.sh --discover
```

Ele lista todos os campos, marca os candidatos a **país** e **categoria**, e imprime as opções (choices) de cada um.

### 4. Configurar

Abra o `config.json` e ajuste:

- `country_field` — variável do país
- `category_field` — variável da categoria de participante (funciona com dropdown, radio **ou** checkbox de múltipla escolha)
- `complete_field` — normalmente `<nome_do_instrumento>_complete`
- `category_map` — de cada opção do REDCap para uma das 5 categorias da figura. **Use exatamente os textos que o `--discover` imprimiu.** O que não for mapeado cai numa coluna "Other" e o script avisa no terminal.
- `country_map` — só para normalizar grafias (ex.: `"Brasil": "Brazil"`), já que o survey roda em 6 idiomas
- `suppress_cells_below` — se quiser esconder células com 1 ou 2 respostas (privacidade em países com pouca gente), coloque `3`. Padrão `0` = mostra tudo.

### 5. Rodar

```bash
./run.sh
```

Saída esperada:

```
OK  372 respostas | 10 paises -> data.json
```

Depois `./preview.sh` para conferir no navegador antes de publicar.

### 6. Publicar

Você ainda vai decidir onde. As três opções, do mais simples ao mais institucional:

**a) GitHub Pages + Actions** — grátis, sem servidor, e o workflow já está pronto.
1. Crie um repositório **público** (só entram contagens agregadas, nada sensível) e suba esta pasta.
2. *Settings → Secrets and variables → Actions → New repository secret*: `REDCAP_API_URL` e `REDCAP_API_TOKEN`.
3. *Settings → Pages → Source: Deploy from a branch → main / (root)*.
4. Link fica em `https://<usuario>.github.io/<repo>/`.

O cron do GitHub roda de 15 em 15 min (na prática o GitHub às vezes atrasa alguns minutos em horário de pico — para este uso não faz diferença).

**b) Servidor do HCPA/UFRGS** — os dados não saem da instituição. Basta um cron:
```
*/15 * * * * cd /caminho/delphi_dashboard && REDCAP_API_URL=... REDCAP_API_TOKEN=... /usr/bin/python3 redcap_aggregate.py
```
e servir a pasta por HTTP.

**c) Vercel / Cloudflare** — se quiser tempo real de verdade em vez de cron. Aí o script vira uma função serverless com cache curto. Me avise que eu adapto.

---

## Pontos de atenção

- **IP liberado.** Alguns REDCaps institucionais restringem a API por IP. Se for o caso do HCPA, a opção (a) não funciona (o GitHub roda de IPs variados) e você precisa ir de (b).
- **Só respostas completas.** Por padrão `only_complete: true`. Se quiser contar parciais, mude para `false`.
- **Metas.** A página mostra a meta de cada categoria (15/10/10/10/5) no cabeçalho da coluna e marca com um traço verde as células que já bateram. Os números vêm de `targets` no config — a figura fala em meta *por idioma*, então confirme se a meta que você quer cobrar dos co-autores é por país ou por idioma antes de divulgar.
- **Países com pouca gente.** Numa combinação país × categoria com n=1, alguém de dentro pode inferir quem respondeu. Se isso preocupar, use `suppress_cells_below: 3`.
- **Nunca coloque o token no `index.html`.** Se algum dia der vontade de "simplificar" chamando a API direto do navegador: o token dá acesso de leitura a **todos** os dados do projeto, e ficaria visível para qualquer visitante.

---

## Próximo passo

Rode o `--discover` e me manda a saída — eu preencho o `config.json` com o mapeamento certo das categorias e já deixo testado.
