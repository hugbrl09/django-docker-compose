# Documentação Técnica — Aplicação Django em Docker Compose

Atividade avaliativa de Computação em Nuvem — ULBRA, 2026/02.

Este documento é o roteiro do projeto: o que foi feito, por que cada decisão foi
tomada e como demonstrar que funciona.

---

## 1. Objetivo

Construir uma imagem Docker própria para uma aplicação Django, orquestrando três
containers com Docker Compose:

| Container | Papel |
|---|---|
| `nginx` | proxy reverso e única porta de entrada |
| `web` | aplicação Django executada pelo Gunicorn |
| `db` | banco de dados PostgreSQL |

A aplicação possui upload de arquivos, e os arquivos enviados são gravados em um
**volume Docker**, de modo que sobrevivem à destruição dos containers.

---

## 2. Arquitetura

```
                          HOST (Windows / WSL2)
                                  |
                         http://localhost:8090
                                  |
   +------------------------------v------------------------------+
   |                       rede: frontend                         |
   |                                                              |
   |   +---------------+                    +-----------------+   |
   |   |     nginx     | ---proxy_pass--->  |       web       |   |
   |   |  (porta 80)   |     web:8000       |    gunicorn     |   |
   |   |               |                    |     django      |   |
   |   +-------+-------+                    +--------+--------+   |
   |           |                                     |            |
   +-----------|-------------------------------------|------------+
               |                                     |
               |                     +---------------v------------+
               |                     |       rede: backend        |
               |                     |                            |
               |                     |      +--------------+      |
               |                     |      |      db      |      |
               |                     |      |  postgres:17 |      |
               |                     |      +------+-------+      |
               |                     +-------------|--------------+
               |                                   |
               |        VOLUMES DOCKER             |
               |   +---------------------+         |
               +-->|    media_volume     |<--------+--- (montado nos dois)
               |   +---------------------+         |
               |   +---------------------+         |
               +-->|    static_volume    |<--------+
                   +---------------------+
                   +---------------------+
                   |    postgres_data    |<--- (só o db)
                   +---------------------+
```

### 2.1 Fluxo de uma requisição normal (uma página HTML)

```
navegador  ->  nginx:80  ->  gunicorn (web:8000)  ->  Django  ->  PostgreSQL (db:5432)
                                                        |
                                                        v
navegador  <-  nginx      <-  gunicorn              <-  HTML renderizado
```

1. O navegador acessa `localhost:8090`, que o Docker mapeia para a porta 80 do
   container `nginx`.
2. O Nginx não encontra a URL nos blocos `/media/` nem `/static/`, então cai no
   bloco `location /` e repassa (`proxy_pass`) para `http://django`, que é o
   upstream apontando para `web:8000`.
3. O Gunicorn recebe a requisição HTTP e a converte para o formato **WSGI**,
   entregando a um dos seus 3 workers.
4. O worker executa o código Django, que consulta o PostgreSQL em `db:5432`.
5. A resposta volta pelo mesmo caminho.

### 2.2 Fluxo do UPLOAD (escrita)

```
navegador  ->  nginx  ->  gunicorn  ->  Django
                                          |--> bytes do arquivo -> /app/media/documentos/
                                          |                        (media_volume)
                                          +--> linha no banco    -> PostgreSQL
                                               (título + caminho)   (postgres_data)
```

O ponto mais importante da atividade: **o arquivo e o registro vão para lugares
diferentes**. O `FileField` do Django grava no banco apenas a *string* do caminho
(`"documentos/nota.pdf"`); os bytes vão para o sistema de arquivos, dentro de
`MEDIA_ROOT`.

É por isso que são necessários **dois** volumes:

- só `postgres_data` → sobrariam registros apontando para arquivos inexistentes;
- só `media_volume` → sobrariam arquivos órfãos, que a aplicação não lista.

### 2.3 Fluxo do DOWNLOAD (leitura) — o Django fica fora

```
navegador  ->  nginx  ->  lê direto do media_volume  ->  navegador
                          (nenhum processo Python é acionado)
```

O Nginx monta o mesmo `media_volume` e entrega o arquivo sozinho.

**Por que isso importa:** o Nginx é escrito em C e usa I/O assíncrono, atendendo
milhares de downloads simultâneos. Um worker do Gunicorn ficaria *bloqueado*
durante todo o download de um arquivo grande — com apenas 3 workers, 3 downloads
lentos derrubariam o site inteiro.

**Como demonstrar:** abrir `docker compose logs -f nginx` e
`docker compose logs -f web` em dois terminais e baixar um arquivo. A requisição
aparece apenas no log do Nginx.

---

## 3. Estrutura de pastas

```
django-docker-compose/
├── docker-compose.yml       orquestração dos 3 serviços, volumes e redes
├── .env                     segredos reais (NÃO versionado)
├── .env.example             modelo das variáveis (versionado)
├── .gitignore
├── README.md
├── DOCUMENTACAO.md          este arquivo
│
├── app/                     contexto de build da imagem da aplicação
│   ├── Dockerfile           receita da imagem Django + Gunicorn
│   ├── .dockerignore        o que não entra no contexto de build
│   ├── requirements.txt     dependências Python
│   ├── entrypoint.sh        espera o banco -> migrate -> collectstatic -> gunicorn
│   ├── manage.py
│   ├── core/                projeto Django
│   │   ├── settings.py      configuração (lida do ambiente)
│   │   ├── urls.py          rotas raiz
│   │   └── wsgi.py          ponto de entrada chamado pelo Gunicorn
│   └── uploads/             app do upload
│       ├── models.py        model Documento (FileField)
│       ├── forms.py         ModelForm
│       ├── views.py         view que lista e recebe upload
│       ├── urls.py
│       ├── admin.py
│       ├── migrations/
│       │   └── 0001_initial.py
│       └── templates/uploads/lista.html
│
└── nginx/
    └── default.conf         configuração do proxy reverso
```

Volumes (gerenciados pelo Docker, **não** são pastas do projeto):

| Volume | Montado em | Conteúdo |
|---|---|---|
| `postgres_data` | `db:/var/lib/postgresql/data` | dados do banco |
| `media_volume` | `web:/app/media` e `nginx:/app/media` (ro) | **arquivos enviados** |
| `static_volume` | `web:/app/staticfiles` e `nginx:/app/staticfiles` (ro) | CSS/JS coletados |

---

## 4. Arquivo por arquivo

### 4.1 `app/Dockerfile`

```dockerfile
FROM python:3.12-slim
```

Imagem base. `slim` é um Debian enxuto (~50 MB contra ~350 MB da completa):
imagem menor, pull mais rápido e menor superfície de ataque. A tag está fixada em
`3.12` e não em `latest` — com `latest`, um build futuro poderia pegar outra
versão de Python e quebrar sem nenhuma alteração no código.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
```

A primeira evita gerar arquivos `.pyc`, inúteis num container descartável. A
segunda desliga o buffer de `stdout`/`stderr` — sem ela, os logs do Django ficam
presos no buffer e o `docker compose logs -f` parece travado.

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**Esta ordem é a decisão mais importante do arquivo.** Cada instrução gera uma
**camada** imutável, e o Docker reaproveita a camada quando a entrada dela não
mudou. Copiando só o `requirements.txt` antes do `pip install`:

- alterei um arquivo `.py` → a camada do `pip` é reaproveitada, rebuild em ~2s;
- alterei o `requirements.txt` → só então o `pip` reinstala.

Se fosse `COPY . .` antes do `pip install`, **qualquer** alteração em qualquer
arquivo invalidaria a camada do `pip` e reinstalaria tudo.

`--no-cache-dir` evita gravar o cache de download do pip dentro da imagem (~50 MB
que nunca seriam reutilizados).

```dockerfile
EXPOSE 8000
```

Apenas **documenta** que o processo escuta na 8000. **Não publica nada** para o
host — quem publica porta é a chave `ports:` do Compose.

```dockerfile
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
```

O `ENTRYPOINT` roda sempre; o `CMD` é entregue a ele como argumento.

Ambos usam a **forma exec** (lista JSON) e não a forma string. Com a forma
string, o Docker executaria via `/bin/sh -c`, o shell viraria o PID 1 e o
Gunicorn **não** receberia o `SIGTERM` do `docker compose down` — o container
levaria 10 segundos para ser morto à força em vez de encerrar limpo.

`--bind 0.0.0.0:8000` é crítico: com `127.0.0.1` o Gunicorn só aceitaria conexões
de dentro do próprio container, e o Nginx (que está em outro container, com outra
pilha de rede) receberia *connection refused*. `0.0.0.0` significa "escute em
todas as interfaces deste container".

`--workers 3`: processos independentes atendendo em paralelo. A regra de bolso da
documentação do Gunicorn é `(2 × núcleos) + 1`.

### 4.2 `app/entrypoint.sh`

Executa, nesta ordem:

1. **Espera o PostgreSQL aceitar conexão.** O `depends_on` garante a ordem de
   *início* dos containers, mas o Postgres leva alguns segundos inicializando o
   cluster; nesse intervalo o container já está "up" e ainda recusa conexão. No
   Compose isso é resolvido pelo `healthcheck` + `condition: service_healthy`;
   este laço é a segunda linha de defesa, para o caso de a imagem ser executada
   fora do Compose.
2. **`migrate --noinput`** — cria/atualiza as tabelas. Roda aqui, e não no
   Dockerfile, porque migration precisa de um **banco vivo**, e no momento do
   build não existe container de banco algum.
3. **`collectstatic --noinput --clear`** — junta os CSS/JS (inclusive os do
   Django admin) em `STATIC_ROOT`, que está montado no `static_volume` que o
   Nginx também monta.
4. **`exec "$@"`** — substitui o shell pelo Gunicorn, que se torna o PID 1 e
   passa a receber os sinais do Docker, permitindo encerramento gracioso.

`set -e` no topo aborta o script no primeiro comando que falhar. Sem isso, se o
`migrate` falhasse, o Gunicorn subiria mesmo assim e o erro real ficaria escondido
atrás de páginas 500.

**Regra geral que resume:** build = o que não depende de nada externo; runtime =
o que depende de banco, rede ou segredos.

### 4.3 `docker-compose.yml`

**Sobre a chave `version:`** que aparece nos slides da aula: era obrigatória no
Compose V1. No Compose V2+ está **obsoleta** — se for declarada, o Docker imprime
um aviso e a ignora. Por isso não é usada aqui.

#### Serviço `db`

Usa a **imagem oficial** `postgres:17-alpine`, sem Dockerfile próprio: não faz
sentido reinventar algo que a comunidade mantém melhor. A versão 17 foi escolhida
porque o Django 6.1 exige PostgreSQL 15 ou superior.

**Não possui `ports:`** — e isso é uma decisão, não um esquecimento. O banco não é
publicado no host; apenas containers na rede `backend` o alcançam. Publicar a 5432
exporia o banco a qualquer processo da máquina (e, num servidor, à internet).

O `healthcheck` usa `pg_isready`, que já vem na imagem oficial. Ele existe porque
"container up" não significa "serviço pronto".

#### Serviço `web`

`build.context: ./app` define a pasta enviada ao daemon como contexto de build.
`env_file: .env` injeta as variáveis de ambiente — é assim que a senha chega ao
Django sem estar no código nem gravada na imagem.

**Também não possui `ports:`.** O Django não fala com o mundo: fala com o Nginx,
que o alcança como `web:8000`. Consequência prática: não existe como burlar o
proxy reverso. Se o `web` fosse publicado, um cliente poderia acessá-lo direto e
pular o limite de upload, os logs e (num cenário real) o HTTPS.

`depends_on` com `condition: service_healthy` espera o healthcheck do banco
passar. O padrão (`service_started`) só garante que o container *iniciou*.

Está nas **duas redes** — é a ponte entre o Nginx e o banco.

#### Serviço `nginx`

`ports: "8090:80"` — formato `HOST:CONTAINER`. É o **único** serviço publicado.
Usa-se 8080 no host porque a 8080 já estava ocupada por outro serviço no host e a porta 80 costuma estar ocupada no Windows.

A configuração é montada como **bind mount** `./nginx/default.conf:...:ro`, e não
como named volume, porque configuração é **código**: mora no repositório e precisa
ser versionada. O `:ro` (read-only) impede o container de alterá-la.

Monta os **mesmos** `media_volume` e `static_volume` do `web`, em modo somente
leitura — é isso que permite servir os arquivos sem acionar o Python.

#### Volumes e redes

Os três volumes são **named volumes**: gerenciados pelo Docker, fora da pasta do
projeto. Sobrevivem a `docker compose down`, `docker rm` e rebuild da imagem.
Morrem **somente** com `docker compose down -v` ou `docker volume rm`.

As duas redes isolam camadas:

```
[ internet ] --8080--> nginx --(frontend)--> web --(backend)--> db
```

O Nginx está só na `frontend`: não possui rota alguma até o banco. Se fosse
comprometido, o atacante ainda não alcançaria o PostgreSQL.

Dentro de cada rede, o **DNS embutido do Docker** resolve o *nome do serviço* para
o IP do container. Por isso o Django se conecta ao host `db` e o Nginx ao host
`web` — nunca a um IP fixo, que mudaria a cada recriação do container.

### 4.4 `nginx/default.conf`

```nginx
upstream django {
    server web:8000;
}
```

`web` é o nome do serviço no Compose, resolvido pelo DNS interno.

```nginx
client_max_body_size 20M;
```

O padrão do Nginx é **1 MB**. Sem esta linha, enviar um arquivo de 5 MB retorna
`413 Request Entity Too Large` e a requisição morre **no Nginx**, sem nunca chegar
ao Django. É a pegadinha clássica de proxy reverso com upload.

```nginx
location /media/  { alias /app/media/; }
location /static/ { alias /app/staticfiles/; }
```

`alias` **substitui** o prefixo da URL pelo caminho em disco:
`/media/documentos/nota.pdf` → `/app/media/documentos/nota.pdf`. (Com `root`, o
prefixo seria **concatenado**, resultando no caminho errado
`/app/media/media/documentos/nota.pdf` — confundir os dois é erro comum.)

```nginx
location / {
    proxy_pass http://django;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Sem esses headers o Django recebe a requisição "vinda do Nginx" e perde toda a
informação do cliente original:

- `Host` — o Django valida contra `ALLOWED_HOSTS` e usa para montar URLs
  absolutas; sem ele chegaria `django` (o nome do upstream) e daria HTTP 400;
- `X-Real-IP` — sem ele, todo log veria apenas o IP interno do Nginx;
- `X-Forwarded-For` — a cadeia de proxies percorrida;
- `X-Forwarded-Proto` — `http` ou `https` original; sem ele, com TLS no Nginx, o
  Django geraria links `http://` dentro de uma página `https://`.

### 4.5 `app/core/settings.py`

Toda a configuração sensível vem de **variáveis de ambiente** (padrão *12-factor
app*), injetadas pelo Compose a partir do `.env`:

```python
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', ...)
DEBUG      = os.environ.get('DJANGO_DEBUG', '0') == '1'
```

A comparação explícita `== '1'` é necessária porque variável de ambiente é sempre
**string**: tanto `"0"` quanto `"False"` são valores verdadeiros em Python se
testados diretamente.

Vantagem central: **a mesma imagem roda em desenvolvimento e em produção**. Muda o
ambiente, não a imagem.

```python
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'HOST': os.environ.get('POSTGRES_HOST', 'db'),
    ...
}}
```

`'db'` não é IP nem domínio: é o nome do serviço no Compose. Se aqui estivesse
`localhost`, o Django procuraria um PostgreSQL dentro do **próprio container**
dele e falharia.

O driver é o **psycopg 3** (`psycopg[binary]`), recomendado pela documentação do
Django 6.1. O extra `[binary]` traz *wheels* já compilados, dispensando instalar
`gcc` e `libpq-dev` na imagem slim.

```python
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL   = '/media/'
MEDIA_ROOT  = BASE_DIR / 'media'
```

**A distinção mais importante da atividade:**

| | STATIC | MEDIA |
|---|---|---|
| Quem cria | o desenvolvedor | o usuário, em execução |
| Exemplos | CSS, JS, assets do admin | os arquivos do upload |
| Conhecido no build? | sim → pode ir na imagem | **não** → precisa de volume |
| Config | `STATIC_ROOT` + `collectstatic` | `MEDIA_ROOT` |

Em cada par, `*_URL` é o prefixo de **URL** (o que o navegador vê) e `*_ROOT` é o
caminho em **disco**. Confundi-los é erro frequente.

`BASE_DIR` vale `/app` dentro do container, portanto `MEDIA_ROOT` é `/app/media` —
exatamente onde o `media_volume` é montado.

### 4.6 `app/uploads/` — a aplicação

**`models.py`** — o model `Documento` tem `titulo` (`CharField`), `arquivo`
(`FileField(upload_to='documentos/')`) e `enviado_em`
(`DateTimeField(auto_now_add=True)`).

`upload_to` é relativo a `MEDIA_ROOT`, resultando em
`/app/media/documentos/<arquivo>`.

**`views.py`** — uma única view lista (GET) e recebe o upload (POST):

```python
form = DocumentoForm(request.POST, request.FILES)
```

`request.FILES` é obrigatório: sem esse segundo argumento o formulário nunca
valida e o upload falha silenciosamente.

```python
return redirect('lista_documentos')
```

Padrão **POST-Redirect-GET**: redirecionar evita que apertar F5 reenvie o
formulário e duplique o upload.

**`templates/uploads/lista.html`** — dois detalhes obrigatórios:

- `enctype="multipart/form-data"` no `<form>`. Sem isso o navegador usa o encoding
  padrão e envia apenas o **nome** do arquivo, não o conteúdo.
- `{% csrf_token %}` — proteção contra *Cross-Site Request Forgery*. O Django
  recusa com HTTP 403 qualquer POST sem esse token.

### 4.7 `.env`, `.env.example` e `.gitignore`

O `.env` contém os valores reais e está no `.gitignore`. O `.env.example`
documenta **quais** variáveis existem, sem revelar nenhum valor, e é versionado —
assim qualquer pessoa clona o repositório e sabe o que configurar.

**Cuidado descoberto durante o desenvolvimento:** valores no `.env` não podem
conter `$` solto, porque o Compose interpreta como interpolação de variável
(`$abc` vira uma variável inexistente e o valor chega truncado). Para um `$`
literal, escreve-se `$$`.

### 4.8 `app/.dockerignore`

Antes de construir, o Docker envia todo o diretório de contexto para o daemon.
Filtrar reduz o tempo de build, diminui a imagem e — o mais importante — evita que
segredos sejam assados dentro de uma camada. Se o `.env` entrasse na imagem, a
senha poderia ser extraída com `docker history`.

---

## 5. Conceitos-chave

### Imagem × Container

> A **imagem** é a classe: molde imutável, somente leitura, armazenado em disco.
> O **container** é a instância: um processo em execução, com uma camada de
> escrita própria e descartável empilhada sobre a imagem (*copy-on-write*).

Da mesma imagem podem ser criados vários containers independentes.

### `docker build` × `docker run`

```
docker build  ->  cria camadas NOVAS na imagem            ->  PERSISTE
docker run    ->  usa a imagem (read-only) + uma camada
                  de escrita temporária                   ->  DESCARTÁVEL
```

`docker run` **nunca** modifica a imagem. É por isso que `RUN pip install` dentro
de um Dockerfile persiste (fica assado na imagem) enquanto um `pip install`
executado via `docker run` desaparece com o container.

### `RUN` × `CMD`

| | Quando executa | Resultado |
|---|---|---|
| `RUN` | durante o `docker build` | gravado na imagem, vira uma camada |
| `CMD` | quando o container sobe | nada é gravado; define o comando padrão |

### Named volume × bind mount

| | bind mount | named volume |
|---|---|---|
| Sintaxe | `./nginx/default.conf:/etc/...` | `media_volume:/app/media` |
| Onde os dados moram | numa pasta do disco do host | área gerenciada pelo Docker |
| Uso típico | configuração versionada, desenvolvimento | dados de produção |
| Portabilidade | depende do caminho da máquina | funciona em qualquer máquina |

Neste projeto: named volumes para banco, uploads e estáticos; bind mount apenas
para a configuração do Nginx.

### WSGI e Gunicorn

**WSGI** (PEP 3333) é o contrato entre servidor web e aplicação Python:
essencialmente uma função que recebe a requisição e devolve a resposta. O arquivo
`core/wsgi.py` expõe essa função.

**Gunicorn** é o *application server* que chama essa função. Ele gerencia vários
processos worker, cada um com uma cópia da aplicação.

O `runserver` do Django **não** é usado porque a própria documentação afirma que
não foi feito nem auditado para produção: é single-process, recarrega ao salvar
arquivo e não suporta concorrência.

### Por que um proxy reverso na frente

O Nginx é a única porta de entrada e acumula funções que o Gunicorn faria mal ou
não faria:

- serve arquivos estáticos e de media diretamente do volume, sem ocupar worker;
- aplica o limite de tamanho de upload antes de a requisição chegar à aplicação;
- absorve clientes lentos, que bloqueariam um worker síncrono do Gunicorn;
- é o ponto natural para terminar TLS, aplicar rate limiting e cache;
- permite escalar a aplicação para N réplicas sem mudar nada no cliente.

---

## 6. Comandos

```bash
# subir tudo (reconstruindo a imagem)
docker compose up --build

# subir em segundo plano
docker compose up -d

# acompanhar os logs
docker compose logs -f
docker compose logs -f nginx
docker compose logs -f web

# ver o estado dos containers
docker compose ps

# abrir um shell dentro do container da aplicação
docker compose exec web sh

# executar um comando do Django
docker compose exec web python manage.py createsuperuser

# parar e REMOVER os containers (volumes preservados)
docker compose down

# parar, remover E APAGAR OS VOLUMES (perde todos os dados)
docker compose down -v

# inspecionar volumes e redes
docker volume ls
docker volume inspect django-docker-compose_media_volume
docker network ls
docker network inspect django-docker-compose_backend
```

---

## 7. Roteiro de demonstração da persistência

Este é o roteiro para provar que o requisito central da atividade foi cumprido.

```bash
# 1. subir
docker compose up -d

# 2. enviar um arquivo em http://localhost:8090

# 3. provar que o arquivo está dentro do container
docker compose exec web ls -la /app/media/documentos/

# 4. DESTRUIR os containers
docker compose down

# 5. provar que os containers sumiram e os volumes não
docker compose ps -a
docker volume ls

# 6. subir de novo e provar que o arquivo continua lá
docker compose up -d
docker compose exec web ls -la /app/media/documentos/
```

O arquivo reaparece no passo 6 porque nunca esteve no container: esteve sempre no
`media_volume`.

**Demonstração complementar** — provar que o Nginx serve o arquivo sem acionar o
Django: com `docker compose logs -f nginx` e `docker compose logs -f web` abertos
em terminais separados, clicar no link de um arquivo. A requisição aparece apenas
no log do Nginx.

---

## 8. Perguntas prováveis na defesa

**Qual a diferença entre imagem e container?**
Imagem é o molde imutável, armazenado em disco. Container é uma instância em
execução dessa imagem, com uma camada de escrita efêmera empilhada por cima. Tudo
escrito nessa camada morre com o container — por isso dados que precisam
sobreviver vão para volumes.

**Por que o `migrate` está no entrypoint e não no Dockerfile?**
Migration precisa de um banco vivo, e durante o `build` não existe container de
banco algum. Build é para o que não depende de nada externo; runtime é para o que
depende de banco, rede ou segredos.

**O que acontece se o Gunicorn escutar em `127.0.0.1:8000`?**
Ele só aceitaria conexões originadas dentro do próprio container. O Nginx, que
roda em outro container com outra pilha de rede, receberia *connection refused*.

**Por que `db` e `web` não têm `ports:`?**
Porque devem ser inalcançáveis a partir do host. A única porta de entrada é o
Nginx. Publicar o `web` permitiria burlar o proxy reverso — pulando o limite de
upload, os logs e, num cenário real, o HTTPS. Publicar o `db` exporia o banco a
tentativas de força bruta.

**Qual a diferença entre `depends_on: - db` e `condition: service_healthy`?**
O primeiro só garante a ordem de *início* dos containers: o `db` começa a subir
antes do `web`, mas o PostgreSQL ainda está inicializando e recusa conexão. O
segundo espera o `healthcheck` (`pg_isready`) passar, ou seja, o banco estar
realmente pronto. Nenhum dos dois reinicia containers — isso é o `restart:`.

**Como o Django encontra o PostgreSQL?**
Pelo nome do serviço, `db`. O Compose cria uma rede própria com um servidor DNS
embutido que resolve nomes de serviço para o IP do container. Nunca se usa IP
fixo, porque ele muda a cada recriação.

**Por que `localhost` não funcionaria nessa conexão?**
Porque dentro de um container `localhost` é o próprio container. Cada container
tem sua própria pilha de rede.

**O que acontece com os arquivos enviados se o container for destruído?**
Nada. Eles estão no `media_volume`, que é gerenciado pelo Docker e existe fora do
ciclo de vida do container. Sobrevivem a `docker compose down` e a rebuild da
imagem. Só são apagados com `docker compose down -v` ou `docker volume rm`.

**Por que o `media_volume` é montado em dois containers?**
Porque a escrita e a leitura são feitas por processos diferentes: o Django escreve
o arquivo durante o upload; o Nginx o lê durante o download, sem acionar o Python.
No Nginx a montagem é `:ro`, pois ele nunca precisa escrever.

**Qual a diferença entre static e media?**
Static são arquivos entregues pelo desenvolvedor (CSS, JS, assets do admin),
conhecidos em tempo de build. Media são arquivos enviados pelo usuário em tempo de
execução, desconhecidos no build — por isso precisam de volume.

**Por que a ordem das instruções no Dockerfile importa?**
Cada instrução gera uma camada, e o Docker reaproveita camadas cujas entradas não
mudaram. Copiando o `requirements.txt` antes do código, alterações no código não
invalidam a camada do `pip install`.

**Por que a imagem `slim`?**
Menos pacotes do sistema: imagem muito menor, deploy mais rápido e menor
superfície de ataque.

**Para que servem as duas redes?**
Para isolar camadas. O Nginx está apenas na `frontend` e não possui rota até o
banco; o `web` está nas duas e funciona como ponte. Se o Nginx fosse comprometido,
o PostgreSQL continuaria inalcançável.

**O que é o `exec "$@"` no fim do entrypoint?**
Substitui o processo do shell pelo Gunicorn, em vez de criar um filho. Assim o
Gunicorn se torna o PID 1 e recebe o `SIGTERM` do `docker compose down`,
encerrando de forma graciosa. Sem o `exec`, o PID 1 seria o shell, que ignora o
sinal, e o Docker mataria o container à força após 10 segundos.

---

## 9. Limitações conhecidas e melhorias

Decisões conscientes tomadas pelo escopo e prazo da atividade:

1. **O container roda como `root`.** Em produção, criar um usuário sem privilégios
   no Dockerfile (`RUN adduser` + `USER appuser`), atentando para a propriedade dos
   diretórios montados como volume.
2. **Sem HTTPS.** O Nginx serve apenas HTTP na porta 80. Em produção, terminar TLS
   no Nginx (Let's Encrypt) e redirecionar HTTP para HTTPS.
3. **Sem multi-stage build.** Para imagens com dependências compiladas, um estágio
   de build separado reduziria ainda mais o tamanho final.
4. **`restart: unless-stopped` em vez de orquestrador.** Para alta disponibilidade
   real, o destino natural seria Docker Swarm ou Kubernetes, com réplicas e health
   checks gerenciados pelo cluster.
5. **Backup dos volumes não automatizado.** Volume persiste, mas não é backup: um
   `docker compose down -v` acidental perde tudo.
