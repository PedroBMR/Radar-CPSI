# Radar CPSI 🛰️

Robô que **monitora diariamente a internet atrás de editais de CPSI** (Contrato
Público para Solução Inovadora — Lei Complementar nº 182/2021, art. 14)
relacionados a **videomonitoramento urbano / segurança pública inteligente**,
guarda um histórico organizado em SQLite versionado e **avisa no Telegram**.

- ✅ Roda 1x por dia via **GitHub Actions** (e manualmente para testes).
- ✅ Fonte primária **PNCP** + fonte secundária **Querido Diário** (~5.570 municípios).
- ✅ Filtro de palavras-chave **configurável** (CPSI **E** videomonitoramento).
- ✅ **Deduplicação** — nunca notifica o mesmo edital duas vezes.
- ✅ Notificação **instantânea** + **resumo diário** no Telegram.
- ✅ Modo **carga histórica (backfill)** desde set/2021, retomável.
- ✅ Fonte que cai **não derruba** as outras; alerta de falha recorrente.

---

## Índice

1. [Como funciona](#como-funciona)
2. [Estrutura do projeto](#estrutura-do-projeto)
3. [Rodando localmente](#rodando-localmente)
4. [Configurando o Telegram (token e chat_id)](#configurando-o-telegram)
5. [Configurando os Secrets no GitHub](#configurando-os-secrets-no-github)
6. [A carga histórica (backfill)](#a-carga-histórica-backfill)
7. [Personalizando palavras-chave](#personalizando-palavras-chave)
8. [Adicionando novas fontes](#adicionando-novas-fontes)
9. [Como o horário do cron é definido](#como-o-horário-do-cron-é-definido)
10. [Testes](#testes)
11. [Notas de validação das APIs](#notas-de-validação-das-apis)

---

## Como funciona

```
┌────────────┐   ┌────────────────┐   ┌─────────────────┐   ┌──────────────┐
│  Fontes    │──▶│ KeywordMatcher │──▶│  SQLite + dedup │──▶│  Telegram    │
│ PNCP / QD  │   │ CPSI  E  vídeo │   │ data/*.db (git) │   │ instant+resumo│
└────────────┘   └────────────────┘   └─────────────────┘   └──────────────┘
```

Um edital só é considerado **match** se contiver **ao mesmo tempo**:

1. um **sinal de CPSI** (`CPSI`, `solução inovadora`, `Lei Complementar 182`, …), **e**
2. um **termo de videomonitoramento** (`videomonitoramento`, `CFTV`, `câmeras`,
   `reconhecimento facial`, `segurança pública inteligente`, …).

A comparação ignora acentos e maiúsculas/minúsculas. Tudo é configurável em
[`config/keywords.yaml`](config/keywords.yaml).

---

## Estrutura do projeto

```
Radar CPSI/
├── config/
│   └── keywords.yaml          # palavras-chave e termos de busca (editável)
├── data/
│   └── radar_cpsi.db          # banco SQLite versionado (criado na 1ª execução)
├── src/radar_cpsi/
│   ├── config.py              # settings (.env) + carregamento de keywords
│   ├── keywords.py            # motor de match CPSI + vídeo
│   ├── models.py              # modelo Edital + chave de dedup
│   ├── database.py            # SQLite, dedup, saúde das fontes
│   ├── http_client.py         # HTTP com retry/backoff + rate limit
│   ├── notifier.py            # Telegram (instantâneo / resumo / alerta)
│   ├── pipeline.py            # orquestração comum (isola falhas por fonte)
│   ├── run_daily.py           # entrypoint da coleta diária
│   ├── backfill.py            # entrypoint da carga histórica (retomável)
│   └── sources/
│       ├── base.py            # interface Source (contrato comum)
│       ├── pncp.py            # fonte primária: PNCP
│       └── querido_diario.py  # fonte secundária: Querido Diário
├── tests/
│   ├── test_keywords.py       # testes do parser de keywords
│   └── test_dedup.py          # testes de deduplicação e storage
├── .github/workflows/
│   ├── daily.yml              # cron diário + commit do banco
│   └── tests.yml              # roda os testes em push/PR
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## Rodando localmente

Pré-requisitos: **Python 3.10+**.

```bash
# 1. Instalar dependências
python -m pip install -r requirements.txt

# 2. Configurar segredos locais
cp .env.example .env
#   edite o .env com seu TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
#   (ou deixe RADAR_DRY_RUN=1 para só imprimir no log, sem enviar nada)

# 3. Rodar a coleta diária
PYTHONPATH=src python -m radar_cpsi.run_daily --days 3
```

No Windows (PowerShell):

```powershell
$env:PYTHONPATH="src"; python -m radar_cpsi.run_daily --days 3
```

> 💡 **Testar sem enviar Telegram:** defina `RADAR_DRY_RUN=1` no `.env`. O robô
> roda de verdade contra as APIs, salva no banco, mas apenas **loga** as mensagens
> em vez de enviá-las.

---

## Configurando o Telegram

Você já tem o **bot** (token vindo do [@BotFather](https://t.me/BotFather)).
Falta descobrir o **`chat_id`** (o destino das mensagens):

1. Envie **qualquer mensagem** para o seu bot no Telegram (procure pelo nome dele
   e mande um "oi").
2. Abra no navegador (troque `<SEU_TOKEN>` pelo token do bot):
   ```
   https://api.telegram.org/bot<SEU_TOKEN>/getUpdates
   ```
3. Na resposta JSON, procure o campo `"chat":{"id": ...}` — **esse número é o
   seu `chat_id`**.
4. **Alternativa mais simples:** fale com o bot [@userinfobot](https://t.me/userinfobot)
   no Telegram; ele devolve o seu `chat_id` diretamente.

Coloque os dois valores no `.env` (local) e nos **Secrets** (GitHub).

---

## Configurando os Secrets no GitHub

Nunca coloque token/chat_id no código. No repositório do GitHub:

1. Vá em **Settings → Secrets and variables → Actions → New repository secret**.
2. Crie os dois secrets:

   | Nome                  | Valor                                  |
   |-----------------------|----------------------------------------|
   | `TELEGRAM_BOT_TOKEN`  | o token do seu bot (do @BotFather)     |
   | `TELEGRAM_CHAT_ID`    | o número do seu chat_id                |

3. Pronto. O workflow [`daily.yml`](.github/workflows/daily.yml) injeta esses
   secrets como variáveis de ambiente automaticamente.

> O workflow precisa de permissão de escrita para commitar o banco. Isso já está
> declarado (`permissions: contents: write`). Se o push falhar por permissão, vá
> em **Settings → Actions → General → Workflow permissions** e marque
> **"Read and write permissions"**.

---

## A carga histórica (backfill)

Roda **uma vez, sob demanda** (não entra no cron). Busca todos os editais de CPSI
de videomonitoramento desde **set/2021** (vigência da LC 182/2021) até hoje.

```bash
PYTHONPATH=src python -m radar_cpsi.backfill
```

Opções:

```bash
# recomeçar do zero, ignorando o checkpoint
PYTHONPATH=src python -m radar_cpsi.backfill --reset

# a partir de uma data específica
PYTHONPATH=src python -m radar_cpsi.backfill --start 2023-01-01
```

Características importantes:

- Os registros entram marcados como **`origem = 'backfill'`** (para você distinguir
  o retroativo do que é coletado no dia a dia).
- **Não** dispara notificação instantânea (evita spam); ao final envia **um único
  resumo** ao Telegram.
- Processa **mês a mês** e grava um **checkpoint** em `data/checkpoints/`. Se cair
  no meio, basta rodar de novo — ele **retoma** de onde parou.
- Respeita rate limit e faz **retry com backoff**.

Depois de rodar o backfill uma vez, deixe o cron diário seguir normalmente — ele
só coleta o que é novo dali pra frente (a dedup garante que nada se repete).

---

## Personalizando palavras-chave

Tudo em [`config/keywords.yaml`](config/keywords.yaml), sem tocar no código:

- **`cpsi_signals`** — termos que indicam que é um CPSI.
- **`video_group`** — termos do tema videomonitoramento.
- **`query_terms`** — o que é enviado às APIs como busca (reduz volume antes do
  filtro fino local).

Regra: um edital só casa se tiver **≥1 termo de `cpsi_signals` E ≥1 de `video_group`**.
Para incluir um novo termo, é só adicionar uma linha na lista. Termos com espaços
são tratados como expressão (tolerante a quebras de linha e espaços múltiplos).

---

## Adicionando novas fontes

A arquitetura já está pronta para novas fontes (ex.: scraper de uma prefeitura):

1. Crie `src/radar_cpsi/sources/minha_fonte.py`.
2. Implemente a interface [`Source`](src/radar_cpsi/sources/base.py):
   ```python
   from .base import Source
   from ..models import Edital

   class MinhaFonteSource(Source):
       name = "minha_fonte"

       def fetch(self, *, since=None, until=None):
           # consulte seu site/API, trate paginação, e emita Editais:
           yield Edital(source=self.name, title=..., link=..., uf=..., ...)
   ```
3. Registre-a em [`sources/__init__.py`](src/radar_cpsi/sources/__init__.py),
   dentro de `build_sources()`.

O pipeline aplica o filtro de keywords, a dedup e a notificação automaticamente.
Se a sua fonte lançar exceção, o robô **isola a falha** e segue com as demais.

---

## Como o horário do cron é definido

No topo de [`daily.yml`](.github/workflows/daily.yml):

```yaml
on:
  schedule:
    - cron: "0 9 * * *"   # 09:00 UTC = 06:00 no horário de Brasília (UTC-3)
```

O GitHub Actions usa **UTC**. Para rodar às 06:00 de Brasília, use `0 9 * * *`.
Para outro horário, ajuste `hora_UTC = hora_Brasília + 3`. Ex.: 08:00 BRT → `0 11 * * *`.

Para rodar **agora** (teste manual): aba **Actions → Radar CPSI — coleta diária →
Run workflow**.

---

## Testes

```bash
pip install -r requirements.txt
pytest -q
```

Cobrem o **parser de keywords** (regra CPSI+vídeo, acentos, limites de palavra) e
a **deduplicação / storage** (chave de dedup, origem backfill vs. diário, saúde
das fontes). Rodam também automaticamente em cada push/PR via
[`tests.yml`](.github/workflows/tests.yml).

---

## Notas de validação das APIs

Validado com chamadas reais antes da implementação:

- **PNCP** — `https://pncp.gov.br/api/search/` (o mesmo endpoint da busca do
  portal). Parâmetros: `q` (full-text), `tipos_documento=edital`, `pagina`,
  `tam_pagina`, `ordenacao=-data`. Retorna `items[]` com `title`, `description`,
  `orgao_nome`, `uf`, `municipio_nome`, `data_publicacao_pncp`,
  `numero_controle_pncp` (usado como ID de dedup) e `item_url`. A busca textual é
  a abordagem correta porque **nenhum código fixo de modalidade** da API
  `consulta/v1` corresponde a CPSI.
- **Querido Diário** — `https://api.queridodiario.ok.org.br/gazettes`.
  Parâmetros: `querystring`, `published_since`, `published_until`, `size`,
  `offset`. Cobre ~**5.570 municípios**. Retorna `gazettes[]` com `territory_name`,
  `state_code`, `date`, `url` (PDF, usado como ID) e `excerpts` (trechos que o
  matcher confirma).

> As APIs são públicas e podem mudar sem aviso. Se uma delas mudar de formato, o
> robô isola a falha, segue com a outra fonte e te alerta no Telegram após falhas
> recorrentes — aí é só ajustar o módulo da fonte afetada.
