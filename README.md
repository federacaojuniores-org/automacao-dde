# Automação DDE — Sincronização de Tracking 2026

Este repositório contém a automação completa de download e sincronização em segundo plano para a planilha de Tracking 2026 de faturamento e amadurecimento organizacional da Rede de Empresas Juniores.

A automação elimina todo o trabalho manual diário de login, geração de relatórios, download, limpeza de dados e atualização de planilhas de forma segura e resiliente.

---

## 🚀 Como Funciona (Arquitetura)

1. **Fase 1: Download Invisível (Playwright):** Um navegador *headless* (invisível) faz login no Portal da Brasil Júnior, navega até a aba de relatórios da federação, aciona a atualização de 3 relatórios estratégicos, monitora até que estejam prontos e realiza o download de forma estruturada.
2. **Fase 2: Auto-Alinhamento Inteligente (Python):** O script lê os arquivos Excel locais e a sua planilha de Tracking, mapeia os cabeçalhos por nome (não por posição) e atualiza apenas as células de dados correspondentes. Se a Brasil Júnior mudar o layout ou adicionar novas colunas, elas serão colocadas no final automaticamente **sem quebrar nenhuma fórmula**!
3. **Fase 3: Alertas por Canal Duplo:** Ao final de cada execução, o script emite uma notificação nativa no seu Mac com efeitos sonoros, e envia um card resumido Markdown diretamente para o chat do Hermes.

---

## 📂 Estrutura de Arquivos

*   `daily_sync.py`: Script orquestrador central (Phase 1 -> Phase 2 -> Alertas).
*   `test_exact_downloads.py`: Script do Playwright para navegação e download do portal BJ.
*   `update_sheets.py`: Script de leitura de Excel e escrita auto-alinhada no Google Sheets via API.
*   `validate_sheets.py`: Script de diagnóstico que lê os indicadores do Dashboard para validar a consistência das fórmulas após cada atualização.
*   `TRACKING_ARCH_REPORT.md`: Relatório completo detalhando a arquitetura de dados, fórmulas corrigidas, conceitos de negócio e gotchas da planilha de Tracking.
*   `.gitignore`: Filtro de segurança que impede que suas senhas ou chaves de API cheguem ao GitHub.
*   `.env.example`: Modelo de configuração para variáveis de ambiente locais.

---

## 🛠️ Configuração e Instalação Local

### 1. Pré-requisitos
*   Python 3.11+
*   `uv` instalado no macOS (instalador super rápido do Python)
*   Chave privada da Conta de Serviço do Google (arquivo `.json`)
*   Credenciais do Portal BJ

### 2. Instalação do Ambiente
Navegue até a pasta do projeto e execute os comandos:

```bash
# Criar o ambiente virtual
uv venv

# Instalar as dependências necessárias
.venv/bin/pip install -r requirements.txt

# Instalar os binários do navegador do Playwright
.venv/bin/playwright install chromium
```

### 3. Configuração de Variáveis de Ambiente
1. Copie o arquivo `.env.example` para `.env`:
   ```bash
   cp .env.example .env
   ```
2. Abra o arquivo `.env` no seu editor e preencha com suas credenciais do portal, ID da planilha master e o nome do seu arquivo `.json` de chave do Google.

---

## 🏃‍♂️ Como Executar

### Execução Manual:
Para atualizar a planilha a qualquer momento com os dados em tempo real mais recentes do portal, execute:
```bash
.venv/bin/python daily_sync.py
```

### Execução Agendada (Cron):
A automação está configurada localmente no agendador nativo do Hermes para rodar **todos os dias às 08:00 AM** em segundo plano (`0 8 * * *`). 
Se o seu Mac estiver desligado no horário, o Hermes detectará o atraso e executará a sincronização **imediatamente após você ligar o computador**, garantindo que seus dados estejam sempre frescos ao iniciar o trabalho!
