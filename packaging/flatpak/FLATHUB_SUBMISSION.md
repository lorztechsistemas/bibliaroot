# Flathub Submission Checklist (BíbliaRoot)

Este projeto já está preparado para build local via `flatpak-builder`.

## O que já está pronto

- Manifest Flatpak (`packaging/flatpak/io.github.lorztechsistemas.bibliaroot.yml`)
- Desktop file e ícone
- Metainfo AppStream (descrição, URLs, release, keywords)
- Permissões para dados/config do app e import/export local
- App ID, desktop-id e binário alinhados para `io.github.lorztechsistemas.bibliaroot`
- TTS configurado para usar `piper` como backend principal

## Antes de submeter no Flathub

1. Confirmar URLs públicas reais
- `homepage`
- `bugtracker`
- `vcs-browser`

2. Adicionar screenshots públicas no `metainfo`
- Flathub normalmente exige screenshots
- hospedar imagens em URL estável (GitHub Releases/Pages)

3. Validar build com acesso à internet
- o build local depende de baixar fontes externas (`pcaudiolib`, `espeak-ng`)
- em ambiente sem DNS/rede o `flatpak-builder` falha antes da compilação
- valide em uma máquina com acesso à internet antes do PR

4. Revisar permissões
- `xdg-documents:create` e `xdg-download:ro` são usadas para backup/import e import de crossrefs
- manter apenas o mínimo necessário

5. Rodar checklist local
```bash
bash packaging/flatpak/check-release.sh
```

6. Testar build e execução
```bash
flatpak-builder --user --install --force-clean build-flatpak packaging/flatpak/io.github.lorztechsistemas.bibliaroot.yml
flatpak run io.github.lorztechsistemas.bibliaroot
```

## Observações

- O agendamento diário via `systemd --user` deve ser tratado como recurso da edição nativa; no Flatpak sandboxed ele está indisponível.
- Em alguns ambientes a persistência de notificações depende do daemon do desktop.
- O TTS é **Piper-only** (sem fallback): se `piper` não estiver disponível, a leitura em voz é bloqueada e o usuário recebe erro explícito.
- O manifest inclui `piper` e `espeak-ng` no build para manter operação de texto-para-fala no ambiente Flatpak.
