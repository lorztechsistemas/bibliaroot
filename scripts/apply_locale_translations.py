#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path


EN_MAP = {
    "PyGObject/GTK4/libadwaita nao encontrados. ": "PyGObject/GTK4/libadwaita not found. ",
    "Instale as dependencias do sistema antes de rodar o app.": "Install the system dependencies before running the app.",
    "Detalhe": "Detail",
    "Nao foi possivel iniciar a interface GTK (sem display grafico disponivel). ": "Could not start the GTK interface (no graphical display available). ",
    "Execute em uma sessao grafica Linux.": "Run it in a Linux graphical session.",
    "BibliaApp": "BibliaApp",
    "BíbliaApp Linux": "BibliaApp Linux",
    "Leitura, busca e favoritos offline": "Offline reading, search and favorites",
    "Buscar palavra/frase": "Search word/phrase",
    "Buscar": "Search",
    "Favoritos": "Favorites",
    "Configurações": "Settings",
    "Carregando dados...": "Loading data...",
    "Busca": "Search",
    "◀ Capítulo": "◀ Chapter",
    "Capítulo ▶": "Chapter ▶",
    "Fonte": "Font",
    "Ex.: amor, fé, Jesus": "Ex.: love, faith, Jesus",
    "Limite": "Limit",
    "Executar busca": "Run search",
    "Digite uma palavra ou frase para pesquisar.": "Type a word or phrase to search.",
    "Versículos favoritos": "Favorite verses",
    "Atualizar": "Refresh",
    "Nenhum favorito ainda.": "No favorites yet.",
    "Idioma da interface": "Interface language",
    "Escolha o idioma do app (aplica após reiniciar)": "Choose the app language (applies after restart)",
    "Ctrl+F: busca | Ctrl+L: leitura | Ctrl+D: favoritos | Ctrl+, : configurações | ": "Ctrl+F: search | Ctrl+L: reader | Ctrl+D: favorites | Ctrl+, : settings | ",
    "Alt+←/Alt+→: capítulo anterior/próximo": "Alt+←/Alt+→: previous/next chapter",
    "Formato 24h (HH:MM)": "24h format (HH:MM)",
    "Escolha se envia uma vez ao dia ou repetido durante o dia": "Choose whether to send once a day or repeatedly during the day",
    "Usado quando a frequência é repetida": "Used when frequency is repeated",
    "Intervalo entre mensagens (quando repetido)": "Interval between messages (when repeated)",
    "Tenta manter a notificação até interação (depende do daemon do sistema)": "Tries to keep the notification until interaction (depends on the system daemon)",
    "Escolha entre notificação nativa ou popup do BíbliaApp": "Choose between native notification or BibliaApp popup",
    "Tenta tocar um som junto da mensagem (melhor esforço)": "Tries to play a sound with the message (best effort)",
    "Escolha o bipe usado quando 'Tocar som' estiver ativado": "Choose the beep used when 'Play sound' is enabled",
    "Veja a prévia e teste o envio imediatamente": "See the preview and test sending immediately",
    "Usa systemd --user no Linux": "Uses systemd --user on Linux",
    "Consultar status do timer e último erro/sucesso": "Check timer status and last error/success",
    "Nenhum banco encontrado": "No database found",
    "Rode scripts/setup_db.py ou copie os .sqlite para data/bibles/.": "Run scripts/setup_db.py or copy the .sqlite files to data/bibles/.",
    "Nenhum banco SQLite encontrado em data/bibles/.": "No SQLite database found in data/bibles/.",
    "Tradução ativa": "Active translation",
    "traduções disponíveis": "available translations",
    "Banco não encontrado": "Database not found",
    "Sem livros nesta tradução.": "No books in this translation.",
    "Fonte ajustada para": "Font adjusted to",
    "Tema definido": "Theme set",
    "Tradução ativa para busca/leitura": "Active translation for search/reading",
    "livros": "books",
    "Tradução alterada para": "Translation changed to",
    "Idioma salvo. Reinicie o app para aplicar a tradução da interface.": "Language saved. Restart the app to apply the interface translation.",
    "Idioma salvo. Reinicie o app.": "Language saved. Restart the app.",
    "Capítulo não encontrado": "Chapter not found",
    "Nenhum versículo encontrado para este capítulo.": "No verses found for this chapter.",
    "Lendo": "Reading",
    "versículos": "verses",
    "tradução": "translation",
    "Desfavoritar": "Unfavorite",
    "Favoritar": "Favorite",
    "Copiar": "Copy",
    "Sem display gráfico para acessar área de transferência.": "No graphical display to access clipboard.",
    "Versículo copiado para a área de transferência.": "Verse copied to clipboard.",
    "Versículo copiado.": "Verse copied.",
    "Versículo adicionado aos favoritos.": "Verse added to favorites.",
    "Versículo removido dos favoritos.": "Verse removed from favorites.",
    "Favorito salvo.": "Favorite saved.",
    "Favorito removido.": "Favorite removed.",
    "resultado(s)": "result(s)",
    "para": "for",
    "na tradução": "in translation",
    "Nenhum resultado encontrado.": "No results found.",
    "Abrir": "Open",
    "Aberto em leitura": "Opened in reader",
    "Abrindo": "Opening",
    "Prévia diária atualizada.": "Daily preview updated.",
    "Falha ao configurar agendamento.": "Failed to configure schedule.",
    "Falha no agendamento diário": "Daily scheduling failure",
    "Erro ao aplicar agendamento (copiável):": "Error applying schedule (copyable):",
    "Falha no agendamento diário.": "Daily scheduling failed.",
    "Agendamento diário atualizado.": "Daily schedule updated.",
    "Resumo": "Summary",
    "envio(s)": "send(s)",
    "janela": "window",
    "intervalo": "interval",
    "min": "min",
    "Agendamento diário aplicado.": "Daily schedule applied.",
    "Falha ao testar notificação.": "Failed to test notification.",
    "Teste de notificação falhou": "Notification test failed",
    "Teste manual": "Manual test",
    "Falha no teste de notificação.": "Notification test failed.",
    "Notificação de teste enviada.": "Test notification sent.",
    "Teste manual executado com sucesso.": "Manual test executed successfully.",
    "Status do timer atualizado.": "Timer status updated.",
    "Prévia indisponível": "Preview unavailable",
    "ativado": "enabled",
    "desativado": "disabled",
    "a cada": "every",
    "popup do BíbliaApp": "BibliaApp popup",
    "nativa": "native",
    "tradução ativa": "active translation",
    "Status": "Status",
    "Janela": "Window",
    "persistente": "persistent",
    "timeout padrão": "default timeout",
    "som": "sound",
    "som off": "sound off",
    "tradução diária": "daily translation",
    "systemd --user indisponível": "systemd --user unavailable",
    "Timer: falha ao consultar status": "Timer: failed to query status",
    "desconhecido": "unknown",
    "sem próximo disparo": "no next trigger",
    "Timer": "Timer",
    "Próximo": "Next",
    "Nenhum erro/status para copiar.": "No error/status to copy.",
    "Sem display gráfico para copiar texto.": "No graphical display to copy text.",
    "Erro/status copiado.": "Error/status copied.",
    "Horário inválido. Use o formato HH:MM (ex.: 08:00).": "Invalid time. Use HH:MM format (e.g.: 08:00).",
    "Horário inválido. A hora deve estar entre 00:00 e 23:59.": "Invalid time. Time must be between 00:00 and 23:59.",
    "Nenhum favorito salvo ainda.": "No saved favorites yet.",
    "favorito(s) salvos.": "favorite(s) saved.",
    "Remover": "Remove",
    "Nenhum versiculo disponivel no banco atual.": "No verse available in the current database.",
    "Reflexão": "Reflection",
    "Observe o contexto de": "Observe the context of",
    "e destaque uma verdade central. ": "and highlight a central truth. ",
    "Pergunte: o que este texto revela sobre Deus, sobre a pessoa humana e sobre a prática cristã hoje?": "Ask: what does this text reveal about God, the human person, and Christian practice today?",
    "Texto-base": "Base text",
    "Pontos:": "Points:",
    "1. Verdade principal do texto": "1. Main truth of the text",
    "2. Aplicação prática para hoje": "2. Practical application for today",
    "3. Resposta de fé e oração": "3. Response of faith and prayer",
    "O amor de Deus": "God's love",
    "Viver pela fé": "Living by faith",
    "Esperança em Deus": "Hope in God",
    "Salvação e graça": "Salvation and grace",
    "Vida de oração": "Prayer life",
    "Aplicação prática da Palavra": "Practical application of the Word",
    "Envia notificação de conteúdo diário do BíbliaApp.": "Sends a daily content notification from BibliaApp.",
    "Sobrescreve o modo salvo nas configurações.": "Overrides the mode saved in settings.",
    "Apenas imprime o conteúdo no terminal (sem notify-send).": "Only prints the content to the terminal (without notify-send).",
    "Conteúdo diário desativado nas configurações.": "Daily content disabled in settings.",
    "notify-send não encontrado neste ambiente.": "notify-send not found in this environment.",
    "Falha ao enviar notificação": "Failed to send notification",
    "Fechar": "Close",
}

ES_MAP = {
    "PyGObject/GTK4/libadwaita nao encontrados. ": "PyGObject/GTK4/libadwaita no encontrados. ",
    "Instale as dependencias do sistema antes de rodar o app.": "Instale las dependencias del sistema antes de ejecutar la app.",
    "Detalhe": "Detalle",
    "Nao foi possivel iniciar a interface GTK (sem display grafico disponivel). ": "No fue posible iniciar la interfaz GTK (sin pantalla gráfica disponible). ",
    "Execute em uma sessao grafica Linux.": "Ejecute en una sesión gráfica de Linux.",
    "BibliaApp": "BibliaApp",
    "BíbliaApp Linux": "BibliaApp Linux",
    "Leitura, busca e favoritos offline": "Lectura, búsqueda y favoritos sin conexión",
    "Buscar palavra/frase": "Buscar palabra/frase",
    "Buscar": "Buscar",
    "Favoritos": "Favoritos",
    "Configurações": "Configuración",
    "Carregando dados...": "Cargando datos...",
    "Busca": "Búsqueda",
    "◀ Capítulo": "◀ Capítulo",
    "Capítulo ▶": "Capítulo ▶",
    "Fonte": "Fuente",
    "Ex.: amor, fé, Jesus": "Ej.: amor, fe, Jesús",
    "Limite": "Límite",
    "Executar busca": "Ejecutar búsqueda",
    "Digite uma palavra ou frase para pesquisar.": "Escriba una palabra o frase para buscar.",
    "Versículos favoritos": "Versículos favoritos",
    "Atualizar": "Actualizar",
    "Nenhum favorito ainda.": "Aún no hay favoritos.",
    "Tamanho da fonte": "Tamaño de fuente",
    "Ajuste da leitura dos versículos": "Ajuste la lectura de los versículos",
    "Tema": "Tema",
    "Escolha entre sistema, claro ou escuro para facilitar a leitura": "Elija entre sistema, claro u oscuro para facilitar la lectura",
    "Sistema": "Sistema",
    "Claro": "Claro",
    "Escuro": "Oscuro",
    "Idioma da interface": "Idioma de la interfaz",
    "Escolha o idioma do app (aplica após reiniciar)": "Elija el idioma de la app (se aplica tras reiniciar)",
    "Ctrl+F: busca | Ctrl+L: leitura | Ctrl+D: favoritos | Ctrl+, : configurações | ": "Ctrl+F: búsqueda | Ctrl+L: lectura | Ctrl+D: favoritos | Ctrl+, : configuración | ",
    "Alt+←/Alt+→: capítulo anterior/próximo": "Alt+←/Alt+→: capítulo anterior/siguiente",
    "Agenda": "Agenda",
    "Defina quando as mensagens devem ser enviadas ao longo do dia.": "Defina cuándo deben enviarse los mensajes a lo largo del día.",
    "Aplicar, testar e consultar o agendamento configurado no sistema.": "Aplicar, probar y consultar la programación configurada en el sistema.",
    "Resumo atual da configuração e status do timer do sistema.": "Resumen actual de la configuración y estado del temporizador del sistema.",
    "Escolha o formato da mensagem diária": "Elija el formato del mensaje diario",
    "Escolha uma tradução fixa ou use a tradução ativa da leitura": "Elija una traducción fija o use la traducción activa de lectura",
    "Formato 24h (HH:MM)": "Formato 24h (HH:MM)",
    "Hora final": "Hora final",
    "Fim da janela diária (HH:MM)": "Fin de la ventana diaria (HH:MM)",
    "Escolha se envia uma vez ao dia ou repetido durante o dia": "Elija si se envía una vez al día o repetido durante el día",
    "Número de envios": "Número de envíos",
    "Usado quando a frequência é repetida": "Usado cuando la frecuencia es repetida",
    "Intervalo (min)": "Intervalo (min)",
    "Intervalo entre mensagens (quando repetido)": "Intervalo entre mensajes (cuando se repite)",
    "Tenta manter a notificação até interação (depende do daemon do sistema)": "Intenta mantener la notificación hasta la interacción (depende del daemon del sistema)",
    "Entrega": "Entrega",
    "Escolha entre notificação nativa ou popup do BíbliaApp": "Elija entre notificación nativa o popup de BibliaApp",
    "Tenta tocar um som junto da mensagem (melhor esforço)": "Intenta reproducir un sonido junto al mensaje (mejor esfuerzo)",
    "Escolha o bipe usado quando 'Tocar som' estiver ativado": "Elija el pitido usado cuando 'Reproducir sonido' esté activado",
    "Suave": "Suave",
    "Sino": "Campana",
    "Alerta": "Alerta",
    "Veja a prévia e teste o envio imediatamente": "Vea la vista previa y pruebe el envío de inmediato",
    "Usa systemd --user no Linux": "Usa systemd --user en Linux",
    "Aplicar": "Aplicar",
    "Diagnóstico": "Diagnóstico",
    "Consultar status do timer e último erro/sucesso": "Consultar estado del temporizador y último error/éxito",
    "Nenhum banco encontrado": "No se encontró ninguna base",
    "Rode scripts/setup_db.py ou copie os .sqlite para data/bibles/.": "Ejecute scripts/setup_db.py o copie los .sqlite a data/bibles/.",
    "Nenhum banco SQLite encontrado em data/bibles/.": "No se encontró ninguna base SQLite en data/bibles/.",
    "Tradução ativa": "Traducción activa",
    "traduções disponíveis": "traducciones disponibles",
    "Banco não encontrado": "Base no encontrada",
    "Sem livros nesta tradução.": "Sin libros en esta traducción.",
    "Fonte ajustada para": "Fuente ajustada a",
    "Tema definido": "Tema definido",
    "Tradução ativa para busca/leitura": "Traducción activa para búsqueda/lectura",
    "livros": "libros",
    "Tradução alterada para": "Traducción cambiada a",
    "Idioma salvo. Reinicie o app para aplicar a tradução da interface.": "Idioma guardado. Reinicie la app para aplicar la traducción de la interfaz.",
    "Idioma salvo. Reinicie o app.": "Idioma guardado. Reinicie la app.",
    "Capítulo não encontrado": "Capítulo no encontrado",
    "Nenhum versículo encontrado para este capítulo.": "No se encontró ningún versículo para este capítulo.",
    "Lendo": "Leyendo",
    "versículos": "versículos",
    "tradução": "traducción",
    "Desfavoritar": "Quitar favorito",
    "Favoritar": "Favorito",
    "Copiar": "Copiar",
    "Sem display gráfico para acessar área de transferência.": "Sin pantalla gráfica para acceder al portapapeles.",
    "Versículo copiado para a área de transferência.": "Versículo copiado al portapapeles.",
    "Versículo copiado.": "Versículo copiado.",
    "Versículo adicionado aos favoritos.": "Versículo agregado a favoritos.",
    "Versículo removido dos favoritos.": "Versículo eliminado de favoritos.",
    "Favorito salvo.": "Favorito guardado.",
    "Favorito removido.": "Favorito eliminado.",
    "resultado(s)": "resultado(s)",
    "para": "para",
    "na tradução": "en la traducción",
    "Nenhum resultado encontrado.": "No se encontraron resultados.",
    "Abrir": "Abrir",
    "Aberto em leitura": "Abierto en lectura",
    "Abrindo": "Abriendo",
    "Prévia diária atualizada.": "Vista previa diaria actualizada.",
    "Falha ao configurar agendamento.": "Error al configurar la programación.",
    "Falha no agendamento diário": "Fallo en la programación diaria",
    "Erro ao aplicar agendamento (copiável):": "Error al aplicar la programación (copiable):",
    "Falha no agendamento diário.": "Falló la programación diaria.",
    "Agendamento diário atualizado.": "Programación diaria actualizada.",
    "Resumo": "Resumen",
    "envio(s)": "envío(s)",
    "janela": "ventana",
    "intervalo": "intervalo",
    "min": "min",
    "Agendamento diário aplicado.": "Programación diaria aplicada.",
    "Falha ao testar notificação.": "Error al probar la notificación.",
    "Teste de notificação falhou": "Falló la prueba de notificación",
    "Teste manual": "Prueba manual",
    "Falha no teste de notificação.": "Falló la prueba de notificación.",
    "Notificação de teste enviada.": "Notificación de prueba enviada.",
    "Teste manual executado com sucesso.": "Prueba manual ejecutada con éxito.",
    "Status do timer atualizado.": "Estado del temporizador actualizado.",
    "Prévia indisponível": "Vista previa no disponible",
    "ativado": "activado",
    "desativado": "desactivado",
    "a cada": "cada",
    "popup do BíbliaApp": "popup de BibliaApp",
    "nativa": "nativa",
    "tradução ativa": "traducción activa",
    "Status": "Estado",
    "Janela": "Ventana",
    "persistente": "persistente",
    "timeout padrão": "timeout predeterminado",
    "som": "sonido",
    "som off": "sonido off",
    "tradução diária": "traducción diaria",
    "systemd --user indisponível": "systemd --user no disponible",
    "Timer: falha ao consultar status": "Temporizador: error al consultar estado",
    "desconhecido": "desconocido",
    "sem próximo disparo": "sin próximo disparo",
    "Timer": "Temporizador",
    "Próximo": "Próximo",
    "Nenhum erro/status para copiar.": "Ningún error/estado para copiar.",
    "Sem display gráfico para copiar texto.": "Sin pantalla gráfica para copiar texto.",
    "Erro/status copiado.": "Error/estado copiado.",
    "Horário inválido. Use o formato HH:MM (ex.: 08:00).": "Horario inválido. Use el formato HH:MM (ej.: 08:00).",
    "Horário inválido. A hora deve estar entre 00:00 e 23:59.": "Horario inválido. La hora debe estar entre 00:00 y 23:59.",
    "Nenhum favorito salvo ainda.": "Aún no hay favoritos guardados.",
    "favorito(s) salvos.": "favorito(s) guardado(s).",
    "Remover": "Eliminar",
    "Nenhum versiculo disponivel no banco atual.": "No hay versículo disponible en la base actual.",
    "Reflexão": "Reflexión",
    "Observe o contexto de": "Observe el contexto de",
    "e destaque uma verdade central. ": "y destaque una verdad central. ",
    "Pergunte: o que este texto revela sobre Deus, sobre a pessoa humana e sobre a prática cristã hoje?": "Pregunte: ¿qué revela este texto sobre Dios, sobre la persona humana y sobre la práctica cristiana hoy?",
    "Texto-base": "Texto base",
    "Pontos:": "Puntos:",
    "1. Verdade principal do texto": "1. Verdad principal del texto",
    "2. Aplicação prática para hoje": "2. Aplicación práctica para hoy",
    "3. Resposta de fé e oração": "3. Respuesta de fe y oración",
    "O amor de Deus": "El amor de Dios",
    "Viver pela fé": "Vivir por la fe",
    "Esperança em Deus": "Esperanza en Dios",
    "Salvação e graça": "Salvación y gracia",
    "Vida de oração": "Vida de oración",
    "Aplicação prática da Palavra": "Aplicación práctica de la Palabra",
    "Envia notificação de conteúdo diário do BíbliaApp.": "Envía notificación de contenido diario de BibliaApp.",
    "Sobrescreve o modo salvo nas configurações.": "Sobrescribe el modo guardado en la configuración.",
    "Apenas imprime o conteúdo no terminal (sem notify-send).": "Solo imprime el contenido en la terminal (sin notify-send).",
    "Conteúdo diário desativado nas configurações.": "Contenido diario desactivado en la configuración.",
    "notify-send não encontrado neste ambiente.": "notify-send no encontrado en este entorno.",
    "Falha ao enviar notificação": "Error al enviar notificación",
    "Fechar": "Cerrar",
}


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def parse_po_entries(text: str):
    blocks = text.split("\n\n")
    out = []
    for block in blocks:
        lines = block.splitlines(keepends=True)
        if not lines:
            out.append(lines)
            continue
        out.append(lines)
    return out


def extract_msgid_msgstr(lines: list[str]) -> tuple[str, tuple[int, int] | None]:
    mode = None
    msgid_parts: list[str] = []
    msgstr_start = None
    msgstr_end = None
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if line.startswith("msgid "):
            mode = "id"
            msgid_parts = [line[6:]]
        elif line.startswith("msgstr "):
            mode = "str"
            msgstr_start = i
            msgstr_end = i + 1
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith('"'):
                msgstr_end = i + 1
                i += 1
            continue
        elif line.startswith('"') and mode == "id":
            msgid_parts.append(line)
        i += 1
    if not msgid_parts:
        return "", None
    mid = "".join(ast.literal_eval(p) for p in msgid_parts)
    if msgstr_start is None or msgstr_end is None:
        return mid, None
    return mid, (msgstr_start, msgstr_end)


def replace_msgstr(lines: list[str], span: tuple[int, int], translated: str) -> list[str]:
    start, end = span
    if "\n" not in translated:
        repl = [f"msgstr {q(translated)}\n"]
    else:
        repl = ['msgstr ""\n']
        for part in translated.split("\n"):
            repl.append(f"{q(part + chr(10) if part != translated.split(chr(10))[-1] else part)}\n")
        # fix last line added extra split logic above is messy; rebuild properly
        repl = ['msgstr ""\n']
        chunks = translated.split("\n")
        for idx, chunk in enumerate(chunks):
            suffix = "\n" if idx < len(chunks) - 1 else ""
            repl.append(f"{q(chunk + suffix)}\n")
    return lines[:start] + repl + lines[end:]


def apply_map(po_path: Path, mapping: dict[str, str]) -> int:
    text = po_path.read_text(encoding="utf-8")
    blocks = parse_po_entries(text)
    changed = 0
    new_blocks: list[str] = []
    for lines in blocks:
        if not lines:
            new_blocks.append("")
            continue
        mid, span = extract_msgid_msgstr(lines)
        if mid and mid in mapping and span is not None and mid != "":
            lines = replace_msgstr(lines, span, mapping[mid])
            changed += 1
        new_blocks.append("".join(lines))
    po_path.write_text("\n\n".join(s.rstrip("\n") for s in new_blocks if s is not None) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    en_po = root / "locale" / "en" / "LC_MESSAGES" / "bibliaapp.po"
    es_po = root / "locale" / "es" / "LC_MESSAGES" / "bibliaapp.po"
    c1 = apply_map(en_po, EN_MAP)
    c2 = apply_map(es_po, ES_MAP)
    print(f"en: {c1} entradas atualizadas")
    print(f"es: {c2} entradas atualizadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
