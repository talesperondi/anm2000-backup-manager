## ANM2000 Backup Manager 1.0.0

Primeira versão pública. Automatiza duas rotinas do cliente ANM2000 (Fiberhome)
com confirmação real de cada operação:

- **Save Config To Flash** em todas as OLTs (ou nas selecionadas), confirmando
  `Command Succeed` no diálogo do cliente;
- **Export Configuration** validado pelo artefato em disco
  (`configtable.xml`, `anconfigdata.unl` e quantidade mínima de arquivos).

### Instalação

1. Baixe `ANM2000-Backup-Manager-Setup-1.0.0.exe` abaixo.
2. Execute o instalador (por usuário, não exige administrador, não precisa de Python).
3. Abra o ANM2000, faça login e depois abra o **ANM2000 Backup Manager**.
4. Crie um agendamento e mantenha **Iniciar com o Windows** marcado.

Requisitos: Windows 10/11 64 bits e o cliente ANM2000 aberto e autenticado.

### Destaques

- Interface escura com painel, execuções, logs, agendamentos e alertas.
- Agendamento diário/semanal com **catch-up** de ocorrências perdidas.
- Execuções serializadas, timeouts, verificação de espaço livre e alertas.
- Backups **nunca** são sobrescritos nem apagados automaticamente.
- Tarefa de logon com instância única e reinício automático.
- CLI de suporte (`anm2000-cli`) para diagnóstico e automação.
- Nenhuma credencial é armazenada.

### Verificação

SHA-256 do instalador:

```
F335CB7444CCB9A36FFD77F0262153AFA9F2F7950C6C48EC5644F2D9651DFE89
```

### Limitações conhecidas

- Depende da árvore de topologia visível e dos textos de confirmação do cliente.
- Após reiniciar o PC, a autenticação do ANM2000 e o login no Windows continuam
  manuais; o backup atrasado roda via catch-up e espera até 60 min.
- Projeto independente, sem vínculo oficial com a Fiberhome.
