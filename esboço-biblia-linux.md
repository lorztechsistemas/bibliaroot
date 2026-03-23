# 📖 BíbliaApp Linux — Esboço Completo do Projeto

> App de leitura e estudo bíblico para Linux
> Stack: **Python 3 + GTK4 + libadwaita + SQLite + Flatpak**
> Dados: **github.com/damarals/biblias** (13 versões em português)

---

## 🗂️ Estrutura de Pastas

```
bibliaapp/
│
├── main.py                     # Ponto de entrada da aplicação
│
├── app/
│   ├── __init__.py
│   ├── application.py          # Classe principal Adw.Application
│   ├── window.py               # Janela principal (AdwApplicationWindow)
│   │
│   ├── views/
│   │   ├── reader_view.py      # Tela de leitura dos versículos
│   │   ├── search_view.py      # Tela de busca
│   │   ├── favorites_view.py   # Versículos favoritos
│   │   └── settings_view.py    # Preferências (AdwPreferencesPage)
│   │
│   ├── widgets/
│   │   ├── book_sidebar.py     # Sidebar com lista de livros
│   │   ├── chapter_panel.py    # Painel de seleção de capítulos
│   │   ├── verse_card.py       # Card individual de versículo
│   │   └── translation_switcher.py  # Troca entre versões (ARA, NVI, etc.)
│   │
│   └── models/
│       ├── bible_db.py         # Acesso ao SQLite (consultas)
│       ├── favorites.py        # Lógica de favoritos
│       └── settings.py         # Configurações salvas do usuário
│
├── data/
│   ├── bibles/
│   │   ├── ARA.sqlite          # Baixado do damarals/biblias
│   │   ├── NVI.sqlite
│   │   ├── ARC.sqlite
│   │   └── ...                 # Outras versões
│   └── user/
│       ├── favorites.db        # Banco local do usuário
│       └── settings.json       # Preferências salvas
│
├── resources/
│   ├── bibliaapp.gresource.xml # Manifest dos recursos GTK
│   ├── ui/
│   │   ├── window.ui           # Layout XML da janela (Blueprint/Glade)
│   │   ├── reader.ui
│   │   └── search.ui
│   ├── icons/
│   │   ├── app-icon.svg
│   │   └── ...
│   └── css/
│       └── style.css           # CSS customizado GTK
│
├── scripts/
│   └── setup_db.py             # Script para baixar e configurar os SQLites
│
├── packaging/
│   ├── flatpak/
│   │   └── io.github.bibliaapp.yml   # Manifest do Flatpak
│   ├── debian/
│   │   └── DEBIAN/control            # Para gerar .deb
│   └── appimage/
│       └── AppDir/                   # Para gerar AppImage
│
├── tests/
│   ├── test_db.py
│   └── test_search.py
│
├── setup.py                    # Instalação via pip/setuptools
├── pyproject.toml              # Configuração moderna do projeto
├── requirements.txt            # Dependências Python
└── README.md
```

---

## 🧰 Dependências e Stack

### Runtime (Obrigatórias)
| Pacote | Versão | Uso |
|---|---|---|
| Python | 3.10+ | Linguagem base |
| PyGObject | 3.44+ | Bindings GTK4 para Python |
| GTK4 | 4.10+ | Framework de UI |
| libadwaita | 1.3+ | Componentes de design GNOME |
| sqlite3 | built-in | Acesso ao banco de dados |

### Dev / Build
| Pacote | Uso |
|---|---|
| flatpak-builder | Empacotar para Flatpak |
| fpm | Gerar .deb e .rpm |
| appimagetool | Gerar AppImage |
| pytest | Testes |
| requests | Baixar SQLites no setup |

### Install rápido
```bash
# Ubuntu / Debian
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libadwaita-1-dev

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Arch
sudo pacman -S python-gobject gtk4 libadwaita
```

---

## 🗄️ Banco de Dados — Estrutura SQLite

Os arquivos `.sqlite` do repositório `damarals/biblias` seguem o padrão do OpenLP:

```sql
-- Tabela de informações da versão
CREATE TABLE bible_meta (
    key   TEXT,
    value TEXT
);

-- Livros da Bíblia
CREATE TABLE book (
    id           INTEGER PRIMARY KEY,
    book_reference_id INTEGER,
    name         TEXT NOT NULL
);

-- Versículos
CREATE TABLE verse (
    id       INTEGER PRIMARY KEY,
    book_id  INTEGER NOT NULL,
    chapter  INTEGER NOT NULL,
    verse    INTEGER NOT NULL,
    text     TEXT NOT NULL,
    FOREIGN KEY (book_id) REFERENCES book(id)
);
```

### Exemplo de query no app
```python
# Buscar versículos de João 3
cursor.execute("""
    SELECT v.chapter, v.verse, v.text
    FROM verse v
    JOIN book b ON v.book_id = b.id
    WHERE b.name = 'João' AND v.chapter = 3
    ORDER BY v.verse
""")
```

---

## 🖥️ Interface — Telas e Componentes

### Janela Principal
```
┌─────────────────────────────────────────────────────┐
│ [≡] BíbliaApp          [🔍 Buscar]    [⚙️]  [● ○ ×] │  ← AdwHeaderBar
├──────────────┬──────────────────────────────────────┤
│              │  João  3                              │
│ 📚 Livros    │  ─────────────────────────────────── │
│              │                                      │
│ ▶ Gênesis    │  ¹ Havia entre os fariseus um homem  │
│   Êxodo      │  chamado Nicodemos...                │
│   Levítico   │                                      │
│   ...        │  ² Este foi ter com Jesus de noite   │
│              │  e lhe disse: Rabi, sabemos que és   │
│ 📖 AT / NT   │  mestre vindo de Deus...             │
│              │                                      │
│ [ARA ▾]      │  ³ Jesus respondeu: Em verdade, em   │
│              │  verdade te digo: quem não nascer...  │
│              │                                      │
│              │        [Cap. 2]  [Cap. 3]  [Cap. 4]  │
└──────────────┴──────────────────────────────────────┘
```

### Componentes GTK4 + libadwaita usados
| Componente | Widget |
|---|---|
| Janela principal | `AdwApplicationWindow` |
| Barra de título | `AdwHeaderBar` |
| Sidebar de livros | `AdwNavigationSplitView` |
| Lista de livros | `GtkListBox` com `AdwActionRow` |
| Card de versículo | `AdwExpanderRow` ou `GtkLabel` estilizado |
| Troca de tradução | `GtkDropDown` |
| Busca | `AdwSearchEntry` |
| Configurações | `AdwPreferencesPage` + `AdwPreferencesGroup` |
| Toast (notificação) | `AdwToast` |
| Modo escuro | Automático via `AdwStyleManager` |

---

## ⚙️ Funcionalidades — v1.0 (MVP)

### Status atual (implementado no protótipo)
- Backend funcional com SQLite real (`damarals/biblias`) e 13 traduções locais
- Front funcional em GTK4/libadwaita com leitura, busca e favoritos
- Persistência local de favoritos e histórico/configurações
- Testes automatizados básicos de backend (`pytest`)

### Core
- [x] Navegação por livro → capítulo → versículo
- [x] Leitura de versículos com tipografia legível
- [x] Troca de tradução em tempo real (ARA, NVI, ARC, etc.)
- [x] Modo escuro automático (segue o sistema)
- [x] Busca por palavra/frase em toda a Bíblia

### Extras v1.0
- [x] Copiar versículo para área de transferência
- [x] Marcar versículos como favoritos
- [x] Ajuste de tamanho de fonte
- [x] Histórico de leitura (último livro/capítulo aberto)
- [x] Painel de configurações visual (UI dedicada)
- [x] Atalhos de teclado (ex.: busca, navegação)
- [x] Tema claro/escuro/sistema com persistência
- [x] Conteúdo diário (versículo/estudo/esboço) com configuração local
- [x] Toasts/ações de copiar e favoritos refinados (polimento inicial)

### Futuro (v2.0+)
- [ ] Comparação lado a lado de duas traduções
- [ ] Anotações pessoais por versículo
- [ ] Planos de leitura
- [ ] Referências cruzadas (scrollmapper/bible_databases)
- [ ] Exportar versículos como imagem/texto

---

## 📦 Empacotamento

### Flatpak (Recomendado)
```yaml
# io.github.bibliaapp.yml
app-id: io.github.bibliaapp
runtime: org.gnome.Platform
runtime-version: '45'
sdk: org.gnome.Sdk
command: bibliaapp

finish-args:
  - --share=ipc
  - --socket=fallback-x11
  - --socket=wayland
  - --filesystem=home  # Para salvar favoritos/configurações

modules:
  - name: bibliaapp
    buildsystem: simple
    build-commands:
      - pip3 install --prefix=/app .
    sources:
      - type: dir
        path: .
```

### .deb (Ubuntu/Debian)
```bash
# Usando fpm
fpm -s python -t deb \
    --name bibliaapp \
    --version 1.0.0 \
    --depends python3-gi \
    --depends gir1.2-adw-1 \
    setup.py
```

### AppImage (Universal)
```bash
# Usando appimagetool
mkdir -p AppDir/usr/bin
cp -r app AppDir/usr/bin/
appimagetool AppDir BíbliaApp-1.0.0-x86_64.AppImage
```

---

## 🚀 Setup Inicial — Passo a Passo

### 1. Clonar e instalar dependências
```bash
git clone https://github.com/seu-usuario/bibliaapp
cd bibliaapp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Em Arch/Manjaro/BigLinux, prefira `venv` (PEP 668) e instale dependências do sistema com `pacman`.

### 2. Baixar os bancos de dados
```bash
python scripts/setup_db.py
# Baixa automaticamente os .sqlite do damarals/biblias
# para a pasta data/bibles/
```

### 3. Rodar o app
```bash
python main.py
```

---

## 📋 requirements.txt

```
PyGObject>=3.44.0
requests>=2.28.0        # Para download dos SQLites no setup
```

---

## 🗓️ Roadmap de Desenvolvimento

| Fase | O que fazer | Estimativa | Status atual |
|---|---|---|
| **Fase 1** | Setup do projeto + download dos SQLites | Semana 1 | ✅ Concluída |
| **Fase 2** | Janela principal + sidebar de livros | Semana 2 | ✅ Concluída |
| **Fase 3** | Leitor de versículos + troca de tradução | Semana 3 | ✅ Concluída |
| **Fase 4** | Busca + favoritos | Semana 4 | ✅ Concluída |
| **Fase 5** | Configurações + polimento visual | Semana 5 | ✅ Concluída (v1) |
| **Fase 6** | Empacotamento Flatpak + testes | Semana 6 | 🟡 Em progresso (manifest/base) |

---

## 📝 Convenções do Projeto

- **Idioma do código**: Inglês (variáveis, funções, comentários)
- **Idioma da UI**: Português (textos exibidos ao usuário)
- **Estilo Python**: PEP8, com Black como formatter
- **Commits**: Mensagens em português no imperativo ("Adiciona sidebar de livros")
- **Versão inicial**: 1.0.0

---

> **Próximo passo recomendado (atual):** Finalizar a **Fase 5** com painel de configurações visual, atalhos de teclado e polimento de UX. Em seguida, partir para a **Fase 6** (empacotamento Flatpak/AppImage e testes de distribuição).
