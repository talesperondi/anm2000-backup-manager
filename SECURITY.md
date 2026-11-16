# Política de segurança

## Escopo

Este projeto automatiza a interface do cliente ANM2000 (Fiberhome) no Windows.
Ele **não** armazena, lê ou transmite credenciais: usa a sessão já autenticada do
cliente aberto na máquina.

## Reportando uma vulnerabilidade

Se você encontrar um problema de segurança, **não abra uma issue pública**.

Use o recurso **Report a vulnerability** na aba *Security* do repositório
(GitHub Private Vulnerability Reporting) ou envie um e-mail para o mantenedor
indicado no perfil do GitHub.

Inclua:

- versão do programa (`Ajuda`/rodapé da interface ou `anm2000-cli --version`);
- versão do Windows e do cliente ANM2000;
- descrição do problema e impacto;
- passos para reproduzir, se possível.

Você receberá uma resposta em até 7 dias. Problemas confirmados serão corrigidos
em uma versão nova e divulgados após a correção.

## Boas práticas ao usar

- Baixe o instalador apenas na página oficial de Releases deste repositório.
- Verifique o hash SHA-256 publicado junto de cada release.
- Não execute o programa em contas compartilhadas sem controle de acesso.
- Mantenha o Windows e o cliente ANM2000 atualizados.
