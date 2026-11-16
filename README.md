# ANM2000 Backup Manager

Automação confiável do **Save Config To Flash** (por OLT) e do **Export Configuration**
(geral do ANM2000), com confirmação real de cada operação, histórico auditável e
agendamento diário com recuperação após queda de energia ou reinício.

O gerenciador **não** guarda credenciais: ele opera o cliente ANM2000 que já está
aberto e autenticado na máquina, identificando janelas e controles em tempo de
execução (nenhum handle fixo).

> Projeto independente, sem vínculo oficial com a Fiberhome.

---

## O problema

O cliente ANM2000 não oferece um agendador nativo confiável para duas rotinas
críticas de operação:

1. **Save Config To Flash** em cada OLT da topologia;
2. **Export Configuration** da base do gerenciador.

Feitas manualmente, essas rotinas são esquecidas, feitas pela metade ou sem
confirmação de que realmente concluíram. Este programa automatiza as duas com
verificação real do resultado.

## O que ele faz

- Executa o flash em **todas as OLTs** (ou apenas nas selecionadas) e confirma
  `Command Succeed` no diálogo do próprio cliente.
- Executa o export e valida o **artefato em disco**: `configtable.xml` presente,
  `anconfigdata.unl` íntegro e quantidade mínima de arquivos.
- Agenda horários diários/semanais com **catch-up**: se o PC estava desligado no
  horário, a execução perdida roda uma vez quando o programa voltar.
- Mantém histórico, logs e alertas em SQLite, com interface gráfica em tema escuro.
- **Nunca sobrescreve** um backup: se a pasta do dia existir, cria `_2`, `_3`…
- **Nunca apaga** backups antigos.
- Sobe com o Windows por Tarefa Agendada e se recupera de quedas.

## Instalação (Windows 10/11 64 bits)

1. Baixe o instalador em [Releases](../../releases/latest):
   `ANM2000-Backup-Manager-Setup-1.0.0.exe`.
2. Execute e siga o assistente. Não é preciso ter Python instalado.
3. Abra o ANM2000 e faça login.
4. Abra o **ANM2000 Backup Manager** e confira a raiz dos backups
   (padrão `C:\ANM2000`).
5. Crie um agendamento na aba **Agendamentos**.
6. Deixe **Iniciar com o Windows** marcado para o programa subir sozinho
   depois de reiniciar o PC.

O instalador é por usuário (não exige administrador) e instala em
`%LOCALAPPDATA%\Programs\ANM2000 Backup Manager`.

### Requisitos

- Windows 10 ou 11 (64 bits);
- cliente ANM2000 instalado, aberto e autenticado;
- sessão do Windows desbloqueada nos horários agendados.

O programa **não armazena senhas** e não faz login no seu lugar.

## Primeiros passos

```powershell
# interface gráfica
python gui.py

# estado atual, OLTs encontradas e últimas execuções
python main.py status

# valida tudo sem enviar nenhum comando ao cliente
python main.py run --dry-run

# flash + export em todas as OLTs
python main.py run

# apenas uma OLT (substring do nome)
python main.py run --olt "OLT-01"

# apenas o export geral
python main.py run --export-only

# espera o ANM2000 abrir/autenticar (até 60 min por padrão)
python main.py run --wait-anm

# histórico, logs e parâmetros
python main.py history -n 10
python main.py logs -n 80
python main.py config show

# inicialização com o Windows
python main.py autostart status
python main.py autostart enable
python main.py autostart disable
python main.py autostart remove
```

Para rodar a partir do código-fonte:

```powershell
git clone https://github.com/<usuario>/anm2000-backup-manager.git
cd anm2000-backup-manager
py -3.13 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python gui.py
```

Requisito de runtime: `comtypes` (a interface usa apenas a biblioteca padrão).

## Dados e backups

Configurável em **Configurações → Raiz dos backups** (padrão `C:\ANM2000`):

```
C:\ANM2000\
  OLT_FLASH\
    2026-11-14\                     <- um diretório por dia (flash não gera arquivo)
  ANM2000_EXPORT\
    ANM2000_Backup_14-11-2026\      <- export validado
    .work\                          <- área de trabalho; nada é apagado sozinho
```

- O export é gravado primeiro em `.work\<data>_<id>`; só depois de validado é
  renomeado para `ANM2000_Backup_DD-MM-AAAA`.
- Export não confirmado permanece em `.work\FAILED_<data>` para inspeção.
- Backups **nunca** são apagados automaticamente. A retenção vale só para logs e
  histórico do banco (`retain_log_days`, `retain_runs_days`).
- Banco, logs e configurações do gerenciador:
  `%LOCALAPPDATA%\ANM2000BackupManager\`.

## Como cada operação é confirmada

### Save Config To Flash

1. Seleciona a OLT na árvore de objetos via MSAA (`accSelect`) e **confirma a seleção**.
2. Envia `WM_COMMAND 61658` ao frame principal do ANM2000.
3. O diálogo de confirmação precisa citar a OLT alvo (guarda contra alvo errado).
4. Clica em **OK** e acompanha o diálogo.
5. Veredito lido do próprio texto: `Command Succeed` = sucesso; `Command Failed`,
   `Command Overtime`, `Busy In Writing ERPROM...`, `No Operation Privilege`,
   `Configuration Not Changed` = falha tipificada; sem texto = **inconclusivo**.

### Export Configuration

1. Envia `WM_COMMAND 24400`, abre `Choose Directory`.
2. Digita o diretório de trabalho e **relê o campo** (`WM_GETTEXT`); se não bater, cancela.
3. Clica em `Ok` e acompanha `Export Configuration` (nunca clica em `Cancel`).
4. A confirmação oficial é o **artefato em disco**: `configtable.xml` presente,
   `anconfigdata.unl` acima do mínimo e quantidade mínima de arquivos. O popup
   `Export config data success!` é registrado, mas não é a autoridade.

## Segurança operacional

- Execuções **serializadas** por lock de instância (`run.lock`) e pela fila da GUI.
- Nunca envia comando sem o cliente estar responsivo e sem diálogos modais pendentes.
- `Cancel`/`Close` nunca são clicados em diálogos de progresso; só em confirmações.
- Timeouts configuráveis (padrão 300 s) e verificação de espaço livre.
- Toda falha gera alerta no banco e na aba **Alertas**, com detalhe e artefato.
- Nenhuma credencial é lida, gravada ou transmitida.

## Agendamento e recuperação

**Interno**: aba *Agendamentos*. Roda enquanto o gerenciador estiver aberto,
inclusive minimizado. O horário e os dias são salvos no SQLite.

- `next_run_at` é o marcador persistente da próxima execução.
- Se o horário passou com o PC desligado, a ocorrência continua vencida e roda
  uma única vez quando o gerenciador voltar (**catch-up**, ligado por padrão).
- Se já houver uma execução em andamento, o agendador espera o próximo ciclo.
- Execuções que ficaram como `running` viram `aborted` na inicialização e geram alerta
  (não ficam presas para sempre).

**Tarefa de logon**: uma Tarefa Agendada do Windows chamada
**ANM2000 Backup Manager** abre a interface no logon do usuário, com atraso de 40 s,
instância única e reinício automático até 3 vezes em intervalos de 1 min. Ela não
exige privilégios de administrador e **não** substitui o agendador interno: só
garante que o programa esteja aberto.

> **Limite real:** o cliente ANM2000 não tem auto-login utilizável. Nenhuma senha
> é armazenada. Depois de reiniciar o PC, alguém precisa entrar no Windows e
> autenticar o cliente; o backup atrasado roda via catch-up e espera até 60 min
> pela autenticação antes de abortar com alerta. Se o PC ficar desligado ou sem
> sessão de usuário, não há automação de interface possível.

## Arquitetura

```
anmbackup/
  winapi.py     Win32 puro (janelas, mensagens, controles, processos)
  msaa.py       IAccessible: COM por thread, árvore de objetos e seleção de OLT
  anm.py        descoberta dinâmica + fluxos de flash e export
  runner.py     orquestração, validação, nomeação, lock, espera e alertas
  db.py         SQLite (execuções, itens, logs, agendamentos, alertas)
  config.py     parâmetros tipados
  scheduler.py  agendador HH:MM + dias + catch-up
  autostart.py  Tarefa Agendada do Windows e abertura do ANM2000
  gui.py        interface tkinter (tema escuro)
  cli.py        linha de comando
tools/          sondas de diagnóstico e geração de ícone
installer/      PyInstaller (GUI/CLI) e Inno Setup
tests/          testes unitários (unittest)
```

## Compilando o instalador

Pré-requisitos: Python 3.13, `pip install -r requirements-build.txt`,
[Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

O script compila a GUI (onedir), a CLI (onefile) e gera
`dist\ANM2000-Backup-Manager-Setup-1.0.0.exe`.

## Limitações conhecidas

- Depende de o cliente ANM2000 estar aberto/autenticado e da árvore de topologia visível.
- A UI do ANM2000 precisa estar no mesmo idioma/versão esperados pelos textos de
  confirmação. Se a Fiberhome mudar rótulos, ajustes podem ser necessários.
- Não há API/protocolo documentado equivalente; TL1 northbound segue como evolução futura.
- A sessão do Windows precisa permanecer desbloqueada para execuções agendadas.
- Testado com Windows 10/11 64 bits e a versão do cliente ANM2000 em uso na
  operação que originou o projeto. Teste em ambiente controlado antes de produção.

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md). Para reportar falhas de segurança, siga
[SECURITY.md](SECURITY.md).

## Licença

[MIT](LICENSE) © 2026 CHNET
