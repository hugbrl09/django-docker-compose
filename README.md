# Django + Gunicorn + Nginx + PostgreSQL com Docker Compose

Aplicação Django com upload de arquivos, orquestrada em três containers com
Docker Compose. Os arquivos enviados são persistidos em um **volume Docker**,
sobrevivendo à destruição dos containers.

Atividade avaliativa — Computação em Nuvem, ULBRA 2026/02.

---

## Arquitetura

```
                    http://localhost:8090
                             |
   +-------------------------v-------------------------+
   |                   rede: frontend                   |
   |   +-----------+                  +-------------+   |
   |   |   nginx   | --proxy_pass-->  |     web     |   |
   |   | porta 80  |    web:8000      |  gunicorn   |   |
   |   +-----+-----+                  +------+------+   |
   +---------|-------------------------------|----------+
             |                               |
             |               +---------------v----------+
             |               |     rede: backend        |
             |               |     +--------------+     |
             |               |     |      db      |     |
             |               |     | postgres:17  |     |
             |               |     +------+-------+     |
             |               +------------|-------------+
             |                            |
             |    +------------------+    |
             +--->|   media_volume   |    |   arquivos enviados
             |    +------------------+    |
             |    +------------------+    |
             +--->|  static_volume   |    |   CSS/JS coletados
                  +------------------+    |
                  +------------------+    |
                  |  postgres_data   |<---+   dados do banco
                  +------------------+
```

| Serviço | Imagem | Porta publicada | Papel |
|---|---|---|---|
| `nginx` | `nginx:1.27-alpine` | **8090** | proxy reverso, única entrada |
| `web` | build local (`python:3.12-slim`) | nenhuma | Django servido pelo Gunicorn |
| `db` | `postgres:17-alpine` | nenhuma | banco de dados |

Apenas o Nginx é publicado no host. Django e PostgreSQL são alcançáveis somente
pelas redes internas do Compose, resolvidos pelo DNS embutido do Docker através
do nome do serviço (`web`, `db`).

---

## Requisitos

- Docker Engine 20.10+
- Docker Compose V2

---

## Como executar

```bash
git clone <URL-DO-REPOSITORIO>
cd django-docker-compose
```

Crie o arquivo de variáveis de ambiente a partir do modelo e preencha os valores:

```bash
cp .env.example .env
```

Gere uma `SECRET_KEY` e uma senha para o banco:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

> Não use caracteres `$` nos valores do `.env`: o Docker Compose interpreta `$`
> como interpolação de variável e o valor chega truncado à aplicação.

Suba os três containers:

```bash
docker compose up --build
```

Acesse **http://localhost:8090**

O painel administrativo fica em `/admin/`. Para criar um usuário:

```bash
docker compose exec web python manage.py createsuperuser
```

### Mudar a porta

A porta publicada é definida em `docker-compose.yml` (`ports: "8090:80"`).
Ao alterá-la, atualize também `DJANGO_CSRF_TRUSTED_ORIGINS` no `.env`, senão o
Django recusa o POST do formulário com HTTP 403.

---

## Demonstração da persistência

```bash
# 1. subir e enviar um arquivo pela interface web
docker compose up -d

# 2. o arquivo está no volume, visto de dentro do container
docker compose exec web ls -la /app/media/documentos/

# 3. destruir os containers
docker compose down

# 4. containers removidos, volumes intactos
docker compose ps -a
docker volume ls

# 5. recriar e conferir: o arquivo continua lá, com o mesmo timestamp
docker compose up -d
docker compose exec web ls -la /app/media/documentos/
```

O arquivo sobrevive porque nunca esteve na camada de escrita do container:
está no volume `media_volume`, gerenciado pelo Docker e externo ao ciclo de vida
dos containers. Só é apagado com `docker compose down -v` ou `docker volume rm`.

---

## Estrutura

```
django-docker-compose/
├── docker-compose.yml       orquestração dos serviços, volumes e redes
├── .env.example             modelo das variáveis de ambiente
├── DOCUMENTACAO.md          documentação técnica detalhada
│
├── app/                     contexto de build da aplicação
│   ├── Dockerfile
│   ├── entrypoint.sh        aguarda o banco, migra, coleta estáticos
│   ├── requirements.txt
│   ├── core/                projeto Django (settings, urls, wsgi)
│   └── uploads/             app de upload (model, form, view, template)
│
└── nginx/
    └── default.conf         configuração do proxy reverso
```

---

## Comandos úteis

```bash
docker compose up -d              # subir em segundo plano
docker compose logs -f            # acompanhar os logs
docker compose logs -f nginx      # logs de um serviço
docker compose ps                 # estado dos containers
docker compose exec web sh        # shell dentro da aplicação
docker compose down               # remover containers (volumes preservados)
docker compose down -v            # remover containers E VOLUMES (apaga tudo)
docker volume ls                  # listar volumes
```

---

## Stack

| Componente | Versão | Função |
|---|---|---|
| Django | 6.1.1 | framework web |
| Gunicorn | 23+ | application server WSGI |
| psycopg | 3.2+ | driver PostgreSQL |
| Nginx | 1.27 | proxy reverso e servidor de arquivos |
| PostgreSQL | 17 | banco de dados |
| Python | 3.12-slim | imagem base |

---

## Documentação

A [DOCUMENTACAO.md](DOCUMENTACAO.md) detalha a arquitetura, explica arquivo por
arquivo o porquê de cada decisão, os conceitos envolvidos (camadas de imagem,
volumes, redes, WSGI, proxy reverso) e as limitações conhecidas do projeto.
