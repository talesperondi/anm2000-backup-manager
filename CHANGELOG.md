# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [1.0.0] - 2026-11-16

### Adicionado

- Instalador Windows por usuário (Inno Setup), sem exigir Python no destino.
- Executáveis congelados: interface (onedir) e CLI de suporte (`anm2000-cli`).
- Comandos silenciosos `--enable-autostart`, `--disable-autostart` e
  `--remove-autostart` usados pelo instalador/desinstalador.
- Licença MIT, documentação de instalação e script de build (`installer/build.ps1`).

### Corrigido

- Criação da Tarefa Agendada no modo congelado: `New-ScheduledTaskAction` não
  aceita `-Argument` vazio; o parâmetro agora é omitido quando não há argumentos.
- Desinstalação não remove mais uma tarefa de logon que aponte para outro
  executável (protege instalações lado a lado).
- COM/MSAA inicializado sob demanda em cada thread, corrigindo execuções
  agendadas abortadas com `CoInitialize não foi chamado`.
- Execuções `running` órfãs são marcadas como `aborted` na inicialização.

### Mudado

- Produto renomeado para **ANM2000 Backup Manager**; CHNET como autora.
- Dados migrados automaticamente de `%LOCALAPPDATA%\CHNET\ANM2000_BackupManager`
  para `%LOCALAPPDATA%\ANM2000BackupManager`.
- Tarefa de logon renomeada para `ANM2000 Backup Manager`; a tarefa legada
  `CHNET ANM2000 Backup Manager` é removida ao ativar a inicialização automática.
