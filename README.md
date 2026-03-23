# BíbliaRoot

App de leitura e estudo bíblico offline para Linux (Python + GTK4 + libadwaita + SQLite).

Objetivo de distribuição: funcionar em qualquer distribuição Linux, com empacotamento principal em **Flatpak** (Flathub) e opção nativa para Arch/Manjaro.

## Recursos principais

- Leitura offline de múltiplas traduções (`SQLite`)
- Busca rápida e busca avançada de estudo (frase/termos, AT/NT/livro)
- Favoritos
- Notas por versículo (tags + marcação)
- Cadernos de estudo e entradas recentes
- Planos de leitura com progresso (e controle por dia)
- Comparação de traduções
- Referências cruzadas (com importador Scrollmapper)
- Conteúdo diário com notificação (nativa ou popup do app)
- Tema claro/escuro e UI multilíngue (`pt_BR`, `en`, `es`)
- Backup/exportação de dados de estudo e backup completo do app

## Requisitos (runtime)

- `python`
- `python-gobject`
- `gtk4`
- `libadwaita`
- `python-requests` (para alguns scripts)

### BigLinux / Manjaro

```bash
sudo pacman -S python python-gobject gtk4 libadwaita python-requests
```

## Executar localmente

```bash
python main.py
```

## Dados bíblicos (traduções)

### Setup básico (damarals/biblias)

```bash
python scripts/setup_db.py
```

### Importar traduções multilíngues (Scrollmapper)

```bash
python scripts/import_scrollmapper_sqlite.py --source /caminho/scrollmapper.sqlite --list
python scripts/import_scrollmapper_sqlite.py --source /caminho/scrollmapper.sqlite --translations KJV ARA NVI
```

Ou via setup:

```bash
python scripts/setup_db.py \
  --scrollmapper-source /caminho/scrollmapper.sqlite \
  --scrollmapper-translations KJV ARA NVI \
  --skip-download
```

## Referências cruzadas (Scrollmapper)

Importar um arquivo SQLite (ou pasta com `cross_references_*.db`) para o `study.db`:

```bash
python scripts/import_scrollmapper_crossrefs.py \
  --source /caminho/para/extras \
  --study-db ~/.local/share/bibliaroot/study.db
```

Também é possível usar o botão `Importar` na aba `Estudo > Referências cruzadas`.

## Backup e restauração

### Backup completo (config + favoritos + estudo)

```bash
python scripts/export_full_backup.py
```

### Restaurar backup completo

```bash
python scripts/import_full_backup.py --input /caminho/backup.json
```

## Empacotamento

### Flatpak

```bash
flatpak-builder --user --install --force-clean build-flatpak packaging/flatpak/io.github.lorztechsistemas.bibliaroot.yml
flatpak run io.github.lorztechsistemas.bibliaroot
```

Checklist local de release Flatpak/AppStream:

```bash
bash packaging/flatpak/check-release.sh
```

### Pacote nativo Arch/Manjaro (`PKGBUILD`)

Gerar tarball local + instalar:

```bash
bash packaging/arch/build-local-package.sh
cd packaging/arch
makepkg -si
```

Depois execute:

```bash
bibliaroot
```

## Flathub (preparação)

Foi adicionada documentação específica para submissão:

- `packaging/flatpak/FLATHUB_SUBMISSION.md`

Inclui:
- checklist de submissão
- observações de permissões
- validação local antes de release

## Testes

```bash
pytest -q
```

## Tradução da interface (i18n)

Compilar catálogos:

```bash
bash scripts/compile_locales.sh
```

Idiomas de UI disponíveis:

- `pt_BR`
- `en`
- `es`
