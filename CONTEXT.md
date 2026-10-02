# CONTEXT.md — SGC DFe Inutilização

Documento de contexto técnico e funcional do projeto **SGC DFe Inutilização**: aplicação local (web app empacotável em `.exe`) para automatizar a **Inutilização de Numeração de DF-e (NF-e/NFC-e)** junto à SEFAZ, atuando como módulo auxiliar de **qualquer** sistema de emissão de DF-e já existente (independente de linguagem/plataforma — o acoplamento é só via um arquivo JSON de configuração, nunca em código), com transmissão via **qualquer software que opere por monitoramento de pastas**.

> **Nota de genericidade:** a arquitetura não depende de nenhum software específico — os caminhos de pasta e as convenções de nome de arquivo são 100% configuráveis (ver §3.1). Este documento nomeia o **UniNFe (Unimake)** com frequência a partir daqui porque foi o software efetivamente usado para validar tudo isso em produção, e as seções §4/§9/§10 descrevem o comportamento real e testado dele especificamente — não uma dependência da arquitetura.

---

## 1. Visão Geral da Arquitetura

```
┌──────────────────────┐        ┌───────────────────────────┐        ┌───────────────┐
│  Frontend Web Local  │  HTTP  │   Backend Python          │ arquivo│  Software de   │  SOAP  ┌────────┐
│  HTML5 + Tailwind/   │◄──────►│   (FastAPI + Uvicorn)     │  XML   │  transmissão   │◄──────►│ SEFAZ  │
│  Bootstrap + JS      │  SSE   │   - Monta XML de pedido   │───────►│  (monitor de   │        └────────┘
│  (status em tempo    │        │   - Grava na pasta Entrada│        │  pastas, ex.   │
│  real)               │        │   - Observa pasta Retorno │◄───────│  UniNFe)       │
└──────────────────────┘        │   - Faz parse do retorno  │  XML   │  - Assina      │
                                │   - Atualiza status/fila  │        │    (cert. A1/A3)│
                                └───────────────────────────┘        │  - Transmite   │
                                                                     │  - Recebe      │
                                                                     └───────────────┘
```

O sistema de emissão de DF-e já existente do cliente **não é alterado**. Esta aplicação Python é um satélite que:

1. Lê a lista de números/faixas a inutilizar (informada manualmente, exportada pelo escritório de contabilidade, ou gravada pelo sistema de emissão/vendas já existente do cliente) a partir de `sgc_dfe_inutilizacao.json`.
2. Monta o XML de **Pedido de Inutilização de Numeração** (schema `inutNFe`, layout SEFAZ v4.00) para cada faixa.
3. Grava o XML na pasta de **Entrada/Envio** monitorada pelo software de transmissão.
4. Aguarda (via polling) o arquivo de **retorno** na pasta correspondente — é o software de transmissão quem assina digitalmente (certificado A1/A3) e transmite à SEFAZ, não esta aplicação.
5. Faz o parse do XML de retorno (`retInutNFe`), interpreta o `cStat`, atualiza o status de cada solicitação e move os XMLs finais para a pasta de destino/arquivo morto.
6. Expõe tudo isso em uma interface web local com atualização de status em tempo real (Server-Sent Events).

**Responsabilidade explícita do software de transmissão** (fora do escopo desta aplicação): assinatura digital com certificado, comunicação SOAP/TLS com o webservice da SEFAZ, retentativas de rede, contingência de transmissão. Esta aplicação **nunca** manipula certificados digitais nem chaves privadas — apenas troca arquivos XML em pastas de convenção com ele.

---

## 2. Diretórios do Projeto e do Ambiente Virtual

| Finalidade | Caminho |
|---|---|
| Pasta raiz do projeto (código-fonte) | `D:\meus documentos_desenvolvimento\OneDrive\fontes\sgc_dfe_inutilizacao` |
| Ambiente virtual Python (venv) | `D:\projetos_python_venv\sgc_dfe_inutilizacao\venv` |
| Interpretador Python do venv | `D:\projetos_python_venv\sgc_dfe_inutilizacao\venv\Scripts\python.exe` |
| Script de ativação (PowerShell) | `D:\projetos_python_venv\sgc_dfe_inutilizacao\venv\Scripts\Activate.ps1` |

> O venv fica **fora** da pasta do projeto (que está sob OneDrive) propositalmente, para evitar sincronização de milhares de arquivos de `site-packages` pelo OneDrive e problemas de path longo/lock de arquivos.

### Estrutura de pastas proposta dentro do projeto

```
sgc_dfe_inutilizacao/                # em dev: JSON fica na raiz do projeto
├── app/
│   ├── main.py                    # ponto de entrada FastAPI
│   ├── config.py                  # carregamento/validação, logging, manutenção de logs
│   ├── models/                    # modelos Pydantic (Configuracao, Empresa, Inutilizacao)
│   ├── services/
│   │   ├── xml_builder.py         # monta o XML -ped-inu.xml
│   │   ├── xml_parser.py          # parse do XML de retorno da SEFAZ
│   │   ├── uninfe_integration.py  # grava pedidos / monitora pastas do UniNFe
│   │   └── status_manager.py      # fila/estado em memória de cada solicitação
│   ├── api/
│   │   └── routes.py              # endpoints REST + endpoint SSE de status
│   ├── static/                    # CSS/JS/favicon (Tailwind ou Bootstrap)
│   └── templates/                 # HTML (Jinja2)
├── sgc_dfe_inutilizacao.json       # empresa + inutilizacao + limpeza (ver §3) — sem subpasta
├── xml_output/
│   ├── enviados/                  # cópia dos pedidos gerados
│   ├── autorizados/                # XMLs de retorno homologados
│   └── logs/                      # logs diários em modo dev (mesmo padrão do .exe)
├── tests/
├── requirements.txt
├── run.py
├── sgc_icone1.ico                  # ícone do .exe e favicon da página
├── CONTEXT.md
└── DIRETRIZES.md                   # convenções e regras de desenvolvimento do projeto
```

> **Em produção (`.exe`)** não existe a árvore de código-fonte acima — apenas `sgc_dfe_inutilizacao.exe`, `sgc_dfe_inutilizacao.json` e a pasta `logs\`, todos na **mesma pasta** onde fica o executável do sistema de emissão/vendas de DF-e já existente do cliente (decisão tomada para não poluir aquela instalação — ver §7).

---

## 3. Schema JSON de Entrada — `sgc_dfe_inutilizacao.json`

Um único arquivo, com dois blocos top-level (`empresa` e `inutilizacao`). Decisão tomada para simplificar a atualização programática por sistemas externos — em particular o sistema de emissão/vendas de DF-e já existente do cliente (qualquer linguagem/plataforma), que pode gravar este arquivo diretamente ao detectar uma quebra de sequência. **Trade-off aceito:** um erro de validação em qualquer um dos dois blocos invalida o carregamento do arquivo inteiro (ver `app/config.py::carregar_configuracao`); antes, com dois arquivos separados, um problema em `inutilizacoes.json` não impedia carregar `empresa.json` (e vice-versa).

```json
{
  "empresa": {
    "razao_social": "EMPRESA EXEMPLO CONTABILIDADE LTDA",
    "nome_fantasia": "Empresa Exemplo",
    "cnpj": "11222333000181",
    "inscricao_estadual": "123456789012",
    "uf": "SP",
    "codigo_uf": 35,
    "ambiente": 2,
    "modelo_dfe": 55,
    "uninfe": {
      "pasta_entrada": "C:\\Unimake\\UniNFe\\{cnpj}\\Envio",
      "pasta_saida": "C:\\Unimake\\UniNFe\\{cnpj}\\Retorno",
      "pasta_erro": "C:\\Unimake\\UniNFe\\{cnpj}\\Erro",
      "pasta_destino_autorizados": "C:\\Unimake\\UniNFe\\{cnpj}\\Enviado\\Autorizados",
      "sufixo_pedido": "-ped-inu.xml",
      "sufixo_retorno": "-inu.xml",
      "sufixo_processo_autorizado": "-procInutNFe.xml",
      "timeout_segundos": 180,
      "intervalo_polling_segundos": 3
    },
    "solicitante": {
      "nome": "Empresa Exemplo Contabilidade",
      "cnpj": "",
      "contato": ""
    },
    "pasta_compactados": null
  },
  "inutilizacao": {
    "justificativa_padrao": "Quebra de sequencia de numeracao solicitada pela contabilidade <razao_social> - CNPJ <cnpj>",
    "solicitacoes": [
      { "id": "1", "serie": 3, "modelo": 55, "numero_inicial": 9434,  "numero_final": 9434,  "justificativa": null, "status": "pendente" },
      { "id": "2", "serie": 3, "modelo": 55, "numero_inicial": 9511,  "numero_final": 9511,  "justificativa": null, "status": "pendente" },
      { "id": "3", "serie": 3, "modelo": 55, "numero_inicial": 9764,  "numero_final": 9764,  "justificativa": null, "status": "pendente" },
      { "id": "4", "serie": 3, "modelo": 55, "numero_inicial": 9832,  "numero_final": 9832,  "justificativa": null, "status": "pendente" },
      { "id": "5", "serie": 3, "modelo": 55, "numero_inicial": 9857,  "numero_final": 9857,  "justificativa": null, "status": "pendente" },
      { "id": "6", "serie": 3, "modelo": 55, "numero_inicial": 9920,  "numero_final": 9920,  "justificativa": null, "status": "pendente" },
      { "id": "7", "serie": 3, "modelo": 55, "numero_inicial": 9977,  "numero_final": 9977,  "justificativa": null, "status": "pendente" },
      { "id": "8", "serie": 3, "modelo": 55, "numero_inicial": 10129, "numero_final": 10129, "justificativa": null, "status": "pendente" },
      { "id": "9", "serie": 3, "modelo": 55, "numero_inicial": 10395, "numero_final": 10395, "justificativa": null, "status": "pendente" }
    ]
  },
  "limpeza": 90
}
```

### 3.1 Bloco `empresa`

| Campo | Tipo | Obrigatório | Observações |
|---|---|---|---|
| `razao_social` | string | sim | Razão social do emitente |
| `cnpj` | string (14 dígitos) | sim | Somente números (pontuação é normalizada na validação) |
| `inscricao_estadual` | string | sim | Somente números |
| `uf` | string (UF) | sim | Sigla da UF, ex. `SP` |
| `codigo_uf` | int | sim | Código IBGE da UF (ex. 35 = SP), usado no campo `cUF` do XML |
| `ambiente` | int (1\|2) | sim | 1 = Produção, 2 = Homologação |
| `modelo_dfe` | int (55\|65) | sim | 55 = NF-e, 65 = NFC-e — modelo "principal" do emitente, informativo (cada solicitação tem seu próprio `modelo` — ver §3.2) |
| `uninfe.pasta_entrada` | string (caminho) | sim | Pasta monitorada pelo UniNFe para receber pedidos (`Envio`) |
| `uninfe.pasta_saida` | string (caminho) | sim | Pasta onde o UniNFe grava as confirmações — sucesso **ou** rejeição (`Retorno`) |
| `uninfe.pasta_erro` | string (caminho) | sim | Pasta com os XMLs que não foram autorizados (`Erro`) |
| `uninfe.pasta_destino_autorizados` | string (caminho) | sim | Pasta onde o UniNFe já copia automaticamente os autorizados (`Enviado\Autorizados`); esta aplicação organiza sua **própria** cópia por data de processamento dentro dela — ver §4 |
| `uninfe.sufixo_pedido` / `sufixo_retorno` | string | sim | Convenção de nomenclatura de arquivos — ver §4, confirmada contra a documentação oficial do UniNFe (Unimake) |
| `uninfe.sufixo_processo_autorizado` | string | não (padrão `-procInutNFe.xml`) | Sufixo do XML "processo" que o **próprio UniNFe** grava em `pasta_destino_autorizados` ao autorizar — ver §4 e §9 |
| `solicitante` | objeto | não | Metadados informativos (quem pediu a inutilização) — não vai para o XML da SEFAZ, apenas para auditoria/log interno |
| `pasta_compactados` | string (caminho) ou `null` | não | Onde salvar o `.zip` de XMLs autorizados — ver §9. Se omitida/`null`, usa fallback automático |

> As pastas do UniNFe (Unimake) são organizadas **por CNPJ do emitente** — um mesmo UniNFe pode atender vários emitentes, cada um com sua própria subárvore `C:\Unimake\UniNFe\<CNPJ>\...`. Confirme o caminho-base exato contra a instalação real (pode não ser `C:\Unimake\UniNFe`) antes de ir para produção.
>
> Os 4 caminhos de `uninfe` aceitam o macro **`{cnpj}`**, substituído pelos dígitos de `empresa.cnpj` na carga do arquivo (`Empresa._substituir_macro_cnpj` em `app/models/empresa.py`) — evita repetir o CNPJ manualmente em cada um dos 4 campos e principalmente evita divergência se o CNPJ mudar e algum campo for esquecido. Usar o caminho literal (sem `{cnpj}`) continua funcionando normalmente, para instalações que não seguem essa convenção.

### 3.2 Bloco `inutilizacao`

Cada item do array `solicitacoes` representa **uma faixa contínua** `numero_inicial`–`numero_final`. O schema `inutNFe` da SEFAZ só aceita uma faixa contígua por pedido; portanto, **números isolados e não sequenciais geram um pedido por número** (`numero_inicial == numero_final`), enquanto lacunas contíguas podem ser agrupadas em uma única faixa.

| Campo | Tipo | Obrigatório | Regras |
|---|---|---|---|
| `justificativa_padrao` | string (≥15 chars) | sim | Usada quando o item não tem `justificativa` própria. Aceita os macros `<razao_social>` e `<cnpj>` (substituídos pela razão social e pelo CNPJ **mascarado** da empresa — `app/services/xml_builder.py::substituir_macros_justificativa`), aplicados antes da sanitização de `xJust`. Também valem numa `solicitacoes[].justificativa` específica de item |
| `solicitacoes[].serie` | int | sim | Série da faixa **desta solicitação** — ver nota abaixo |
| `solicitacoes[].modelo` | int (55\|65) | sim | Modelo da faixa **desta solicitação** — 55 = NF-e, 65 = NFC-e |
| `solicitacoes[].numero_inicial` / `numero_final` | int | sim | `numero_final >= numero_inicial` |
| `solicitacoes[].justificativa` | string ou `null` | não | Se preenchida (≥15 chars), sobrepõe a padrão para aquele item |
| `solicitacoes[].status` | string | gerenciado pela app | `pendente` → `enviado` → `homologado` \| `rejeitado` \| `erro` \| `expirado`. Na UI, `pendente` é rotulado "A enviar" (só exibição — o valor interno/API continua `pendente`) |

> **Por que `serie`/`modelo` são por item, e não um valor único do lote:** um mesmo lote de inutilizações pode misturar séries diferentes (duas séries de NF-e) ou até modelos diferentes (NF-e e NFC-e) — por exemplo, quando a contabilidade detecta quebras de sequência em mais de uma série/modelo no mesmo mês e manda tudo numa remessa só. Cada solicitação é um pedido `inutNFe` independente à SEFAZ de qualquer forma (CONTEXT.md §5), então não há necessidade real de todas compartilharem a mesma série/modelo — exigir isso só criaria trabalho extra (dividir em vários lotes) sem ganho.

Validação obrigatória em `xJust`: **mínimo de 15 caracteres**, conforme schema XSD da SEFAZ (`TXJust`, minLength 15, maxLength 255).

### 3.3 Campo `limpeza` (raiz do arquivo)

| Campo | Tipo | Obrigatório | Regras |
|---|---|---|---|
| `limpeza` | int | não (padrão 90) | Dias de retenção dos logs de auditoria — ver §8 |

---

## 4. Integração com Pastas do UniNFe

O UniNFe opera como um **monitor de pastas** (folder watcher): arquivos XML depositados em sua pasta de entrada, com sufixo reconhecido, disparam o processamento correspondente (assinatura + transmissão SOAP). A convenção abaixo foi **confirmada contra a documentação oficial do UniNFe (Unimake)** — [Manuais:UniNFe/PedInu](https://wiki.unimake.com.br/index.php/Manuais:UniNFe/PedInu) e [Manuais:UniNFe/Integracao do ERP com o UniNFe](https://wiki.unimake.com.br/index.php/Manuais:UniNFe/Integracao_do_ERP_com_o_UniNFe) — mas os **caminhos** continuam específicos de cada instalação (organizados por CNPJ do emitente, ver §3.1) e devem ser checados contra o ambiente real antes de produção.

| Pasta | Papel | Arquivo envolvido |
|---|---|---|
| **Envio** (`uninfe.pasta_entrada`) | A aplicação grava aqui o pedido de inutilização, que o UniNFe lê, assina e envia à SEFAZ | `<IDINUT>-ped-inu.xml` |
| **Retorno** (`uninfe.pasta_saida`) | UniNFe grava aqui a resposta do webservice — **contém tanto homologações quanto rejeições da SEFAZ**, a diferença está no `cStat` dentro do XML, não no nome do arquivo | `<IDINUT>-inu.xml` |
| **Erro** (`uninfe.pasta_erro`) | UniNFe grava aqui um arquivo de **texto puro** (não XML) quando o pedido falha antes de chegar à SEFAZ: erro de validação de schema, conexão ou assinatura digital | `<IDINUT>-inu.err` |
| **Enviado\Autorizados** (`uninfe.pasta_destino_autorizados`) | O próprio UniNFe já grava aqui, na **raiz** (sem subpasta), o XML "processo" completo (pedido + protocolo, moldes de um `procNFe`) assim que a SEFAZ autoriza; esta aplicação usa a mesma pasta como raiz e cria **dentro dela** sua própria organização por data de processamento (`AAAA\MM\`), com uma cópia adicional (crua) do retorno — ver §4.1 e §9 | `<IDINUT>-procInutNFe.xml` (UniNFe, na raiz) + `<IDINUT>-inu.xml` (esta aplicação, em `AAAA\MM\`) |

`IDINUT` é o `Id` do `infInut` **sem o prefixo `"ID"`** (43 dígitos) — confirmado pelo exemplo oficial da documentação Unimake: `26100000000000000055001000000101000000101-ped-inu.xml`. Nosso `xml_builder.calcular_id()` gera exatamente esse valor (ver §5.1); `uninfe_integration.py` usa esse mesmo prefixo para gravar o pedido e para localizar o arquivo de retorno correspondente.

### 4.1 Ciclo de vida de uma inutilização

```
[pendente]
   │  xml_builder gera o <IDINUT>-ped-inu.xml
   ▼
[enviado]  ── grava em pasta_entrada (Envio), contador de tentativas/timeout inicia
   │
   │  uninfe_integration faz polling em pasta_saida (Retorno) e pasta_erro (Erro)
   ▼
   ├──► arquivo <IDINUT>-inu.err em pasta_erro      → [erro]        (falha antes da SEFAZ: schema/conexão/assinatura)
   ├──► arquivo <IDINUT>-inu.xml em pasta_saida,
   │    cStat=102                                    → [homologado]  (SEFAZ aceitou)
   ├──► arquivo <IDINUT>-inu.xml em pasta_saida,
   │    cStat≠102                                    → [rejeitado]   (SEFAZ recusou — resposta válida, não é erro de comunicação)
   └──► nenhum retorno após timeout_segundos          → [expirado]    (alerta para o usuário)
```

O `status_manager` mantém esse estado em memória (processo único, sem necessidade de banco de dados) e publica mudanças via SSE para o frontend. Quando `[homologado]`, esta aplicação copia o XML de retorno cru para dentro de `pasta_destino_autorizados`, organizado pela data em que o retorno foi processado (ex. `Enviado\Autorizados\2026\07\<IDINUT>-inu.xml`) — isso é só o histórico/registro desta própria aplicação.

Separadamente, `app/services/uninfe_integration.py::localizar_processo_autorizado` procura o XML **"processo" completo** que o próprio UniNFe grava na raiz de `pasta_destino_autorizados` (`<IDINUT>-procInutNFe.xml`, sem subpasta `AAAA\MM`) — é esse arquivo, não a cópia crua acima, que `item.xml_retorno_path` passa a apontar quando encontrado, pois é o documento correto para arquivar/enviar à contabilidade (§9). Se ainda não existir no instante em que o retorno é processado (ex.: UniNFe ainda terminando de gravá-lo), cai de volta pra cópia crua, com aviso no log — não é tratado como erro, e nada impede uma nova tentativa manual de localizá-lo depois.

### 4.2 Estratégia de detecção de retorno

Como não há um identificador de protocolo antes do envio, a correlação pedido↔retorno é feita pelo **nome base do arquivo**: o mesmo `IDINUT` usado no pedido (`<IDINUT>-ped-inu.xml`) é o prefixo tanto do retorno de sucesso/rejeição (`<IDINUT>-inu.xml`) quanto do erro pré-SEFAZ (`<IDINUT>-inu.err`). A implementação busca por *prefixo* (`<IDINUT>*`) em vez de sufixo exato, o que a torna resiliente a pequenas variações de convenção entre versões do UniNFe.

### 4.3 Verificação de histórico na inicialização

Esta aplicação não persiste status em disco entre execuções (decisão registrada nas diretrizes de desenvolvimento do projeto — estado só em memória, no `status_manager`). Se o app for fechado com solicitações ainda "a enviar" e reaberto depois, o `sgc_dfe_inutilizacao.json` continua dizendo `"status": "pendente"` para elas — mas o UniNFe pode já ter processado o pedido enquanto o app estava fechado (ou numa execução anterior).

Por isso, a cada início da aplicação (`app/main.py::lifespan`, via `uninfe_integration.verificar_historico_na_inicializacao`), cada solicitação pendente é checada contra `pasta_saida`/`pasta_erro` **antes** de qualquer pedido novo ser gerado. A diferença para o polling normal (§4.2) é que aqui não se sabe a data exata em que o pedido original foi gerado — o `AAMM` do `Id` (CONTEXT.md §5.1) muda todo dia — então a busca usa curinga (`?`) no lugar do `AAMM`: `<cUF>????<CNPJ><mod><serie><nNFIni><nNFFin>*`. Os demais 39 dígitos do `Id` são fixos para uma dada solicitação, então o curinga não gera falsos positivos entre solicitações diferentes.

---

## 5. Modelo de XML — Pedido de Inutilização (`inutNFe`)

Schema oficial SEFAZ (Manual de Orientação do Contribuinte, layout NF-e versão 4.00), elemento raiz `inutNFe`, namespace `http://www.portalfiscal.inf.br/nfe`.

### 5.1 Formação do atributo `Id`

```
Id = "ID" + cUF(2) + AAMM(4) + CNPJ(14) + mod(2) + serie(3, zero-padded) + nNFIni(9, zero-padded) + nNFFin(9, zero-padded)
```

Total: 45 caracteres (`ID` + 43 dígitos).

`AAMM` e o campo `<ano>` do XML (§5.2) refletem **a data em que o pedido está sendo gerado** — não uma "competência" configurada no JSON. Isso já foi analisado e decidido explicitamente: uma versão anterior deste arquivo tinha um campo `inutilizacao.competencia` (`"2026-07"`) usado para preencher esses valores, mas isso não corresponde ao que a SEFAZ espera (o `ano`/AAMM do pedido de inutilização é sempre o do **momento do envio**, não o período/competência a que as notas puladas pertencem) e, na prática, era só uma fonte de erro — bastava esquecer de atualizar o JSON no mês seguinte para o `Id`/`ano` saírem errados. `calcular_id()`/`montar_xml_inutilizacao()` agora usam `date.today()` diretamente (com um parâmetro `hoje` opcional só para testes determinísticos), então não existe mais campo `competencia` no `sgc_dfe_inutilizacao.json`.

`mod`/`serie` vêm da própria solicitação (`solicitacoes[].modelo`/`.serie` — §3.2), não mais de um valor único do lote.

**Exemplo (caso de referência — número 9434, série 3, modelo 55/NF-e, SP, pedido gerado em 15/07/2026; CNPJ fictício, usado só para ilustrar o cálculo):**

```
cUF    = 35
AAMM   = 2607   (pedido gerado em julho/2026)
CNPJ   = 11222333000181
mod    = 55
serie  = 003
nNFIni = 000009434
nNFFin = 000009434

Id = ID3526071122233300018155003000009434000009434
```

### 5.2 XML de pedido (exemplo)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<inutNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <infInut Id="ID3526071122233300018155003000009434000009434">
    <tpAmb>2</tpAmb>
    <xServ>INUTILIZAR</xServ>
    <cUF>35</cUF>
    <ano>26</ano>
    <CNPJ>11222333000181</CNPJ>
    <mod>55</mod>
    <serie>3</serie>
    <nNFIni>9434</nNFIni>
    <nNFFin>9434</nNFFin>
    <xJust>Quebra de sequencia de numeracao solicitada pela contabilidade Empresa Exemplo - CNPJ 11.222.333/0001-81</xJust>
  </infInut>
  <!-- A tag <Signature> é adicionada pelo UniNFe no momento da assinatura digital.
       Esta aplicação grava o XML SEM assinatura. -->
</inutNFe>
```

Campos fixos: `xServ` sempre `"INUTILIZAR"`. `tpAmb` reflete `empresa.ambiente` (1 ou 2) dentro de `sgc_dfe_inutilizacao.json`. Acentos e caracteres especiais devem ser removidos/normalizados em `xJust` (o schema não aceita determinados caracteres especiais — sanitizar para ASCII básico ou usar apenas letras, números, espaço e pontuação simples).

Antes da sanitização, `xJust` passa pela substituição dos macros `<razao_social>`/`<cnpj>` (§3.2) — o exemplo acima já mostra o resultado final (pós-substituição e sanitização) do template `"... contabilidade <razao_social> - CNPJ <cnpj>"`.

### 5.3 XML de retorno (`retInutNFe`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<retInutNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <infInut>
    <tpAmb>2</tpAmb>
    <verAplic>SP_UNINFE_1.0.0</verAplic>
    <cStat>102</cStat>
    <xMotivo>Inutilização de número homologado</xMotivo>
    <cUF>35</cUF>
    <ano>26</ano>
    <CNPJ>11222333000181</CNPJ>
    <mod>55</mod>
    <serie>3</serie>
    <nNFIni>9434</nNFIni>
    <nNFFin>9434</nNFFin>
    <dhRecbto>2026-07-15T10:32:00-03:00</dhRecbto>
    <nProt>135260000012345</nProt>
  </infInut>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">...</Signature>
</retInutNFe>
```

### 5.4 Tratamento de `cStat`

| `cStat` | Significado | Ação da aplicação |
|---|---|---|
| `102` | Inutilização de número homologado | Marca item como `homologado`; move XML para `pasta_destino_autorizados`; registra `nProt`/`dhRecbto` |
| `563` | Rejeição: já existe pedido de inutilização para a faixa | Marca `rejeitado`; expõe motivo na UI |
| `999` | Rejeição: erro não catalogado / erro de schema | Marca `erro`; expõe `xMotivo` bruto na UI para diagnóstico |
| demais códigos de rejeição (5xx/9xx) | Diversas causas (CNPJ divergente, faixa inválida, ambiente incorreto, série inexistente etc.) | Marca `rejeitado`; **não tentar reenviar automaticamente** — exige revisão humana |

> ⚠️ A tabela completa e oficial de códigos `cStat` para o serviço de Inutilização deve ser conferida no **Manual de Orientação do Contribuinte (MOC)** vigente e nas Notas Técnicas da SEFAZ, pois pode variar por UF/versão de schema. Implementar o parser de forma genérica (armazenar `cStat` + `xMotivo` sempre, tratando apenas `102` como caminho feliz) em vez de hardcodar uma tabela extensa de códigos.

---

## 6. Considerações de Segurança e Ambiente

- **Nenhum certificado digital é manipulado por esta aplicação.** Toda assinatura/transmissão é responsabilidade do UniNFe.
- A aplicação roda **localmente** (`127.0.0.1`), sem exposição em rede — não requer autenticação HTTP própria, mas o binário `.exe` deve deixar isso explícito na UI (ex. "Aplicação local — não acesse via rede").
- Caminhos de pastas do software de transmissão são específicos de cada estação de trabalho/servidor; `sgc_dfe_inutilizacao.json` deve ficar **fora do executável** (arquivo externo editável, inclusive por sistemas externos — o sistema de emissão de DF-e já existente do cliente), nunca embutido no build do PyInstaller.
- Ambiente de **Homologação (`tpAmb=2`)** deve ser o padrão de testes antes de qualquer execução em Produção (`tpAmb=1`), especialmente por se tratar de uma operação **irreversível** perante a SEFAZ (número inutilizado não pode ser reutilizado).

---

## 7. Empacotamento (PyInstaller) — considerações de arquitetura

- `sgc_dfe_inutilizacao.json`, `templates/` e `static/` devem ser tratados como recursos externos ou incluídos via `--add-data`, mas a leitura em runtime deve resolver caminhos via `sys._MEIPASS` (quando congelado) vs. diretório do projeto (quando em dev) — encapsulado em `app/config.py::get_paths()`.
- O servidor Uvicorn deve subir em modo *embedded* (`run.py` importa o objeto `app` diretamente — **não** passar a string `"app.main:app"` para `uvicorn.run()`, pois isso esconde `app.main` e todo o seu grafo de imports da análise estática do PyInstaller, quebrando o build) e abrir o navegador padrão automaticamente (`webbrowser.open`) apontando para `http://127.0.0.1:<porta>`.
- Build final usa `--windowed` (sem console/tela preta) e `--icon sgc_icone1.ico` (também servido como favicon da página, em `/static/favicon.ico`). Em modo `--windowed`, `sys.stdout`/`sys.stderr` não têm para onde escrever — os logs (inclusive os do próprio Uvicorn, via `log_config=None` em `uvicorn.run()`) vão para `logs/sgc_dfe_inutilizacao_dd-mm-aaaa.log` ao lado do `.exe` — ver §8.
- Usa `--onefile` (um único `.exe`, sem pasta `_internal\`) em vez de `--onedir`: este app é implantado na **mesma pasta** do executável do sistema de emissão/vendas de DF-e já existente do cliente, e o `--onedir` poluiria/arriscaria conflitar com aquela instalação. Trade-off aceito: abertura um pouco mais lenta (extrai o bundle para uma pasta temporária a cada execução) — irrelevante para o uso pontual deste app (processar um lote e fechar). Importante: `data_dir`/`logs_dir` em `app/config.py::get_paths()` resolvem via `Path(sys.executable).parent` (a pasta real do `.exe`), **não** via `sys._MEIPASS` (a pasta temporária de extração do `--onefile`) — só `templates_dir`/`static_dir` (recursos somente-leitura) usam `_MEIPASS`.
- `--onefile` no Windows sobe **dois processos** com o mesmo nome no Gerenciador de Tarefas: o bootloader (pai, poucos MB, extrai o bundle e supervisiona) e o processo Python real rodando o Uvicorn/FastAPI (filho, maior). Encerrar só o filho é suficiente — o pai detecta a saída dele e também termina.
- **Fechar a aba do navegador não encerra o processo** — é só um cliente HTTP do servidor local, que continua rodando em segundo plano. Por isso existe `POST /api/encerrar` (chamado pelo botão "Encerrar aplicativo" na UI): agenda `os._exit(0)` ~300ms depois de responder (tempo pro navegador receber a resposta), matando o processo de propósito sem tentar um shutdown gracioso do Uvicorn — não há nada a perder, já que `status_manager` é só em memória e os logs são escritos linha a linha.
- Gerar o build com `--workpath`/`--distpath` **fora** da pasta do projeto quando o projeto estiver sob uma pasta sincronizada por OneDrive/Dropbox/etc. — builds sucessivos do PyInstaller geram/removem muitos arquivos pequenos que o serviço de sincronização tenta indexar em tempo real, causando `PermissionError` ao limpar/recriar `dist\` (documentado nas diretrizes de desenvolvimento do projeto).

## 8. Auditoria: logs diários, compactação e expurgo

Cada execução do `.exe` grava em `logs/sgc_dfe_inutilizacao_dd-mm-aaaa.log` (uma linha por evento relevante — pedidos gravados, retornos processados, erros). Execuções repetidas no mesmo dia acrescentam ao mesmo arquivo.

A cada início da aplicação, `app/config.py::limpar_e_compactar_logs()` roda automaticamente (modo congelado apenas) e:

1. Compacta em `.zip` todo `.log` que não seja do dia corrente (o `.log` original é removido depois de compactar com sucesso).
2. Exclui definitivamente qualquer arquivo (`.log` ou `.log.zip`) cuja data no nome seja mais antiga que `limpeza` dias — chave configurável em `sgc_dfe_inutilizacao.json` (raiz do arquivo, padrão 90 dias se omitida).

```json
{
  "empresa": { ... },
  "inutilizacao": { ... },
  "limpeza": 90
}
```

Arquivos na pasta `logs/` que não seguem o padrão de nome esperado são ignorados (nunca excluídos/compactados por engano).

## 9. Envio para a contabilidade: compactação + texto de e-mail sugerido

Depois de processar um lote, o botão **"Compactar autorizados"** na UI (`POST /api/compactar-autorizados`, implementado em `app/services/compactacao.py`) junta os XMLs de retorno já `homologado` **da sessão atual** (em memória, no `status_manager`) num único `.zip`, para mandar para a contabilidade. Só entram no `.zip` itens com `xml_retorno_path` apontando para um arquivo que ainda existe em disco — itens sem retorno arquivado, ou cujo arquivo foi movido/apagado manualmente, são ignorados silenciosamente (com aviso no log).

O arquivo que entra no `.zip` é, preferencialmente, o XML **"processo"** que o próprio UniNFe grava (`<IDINUT>-procInutNFe.xml`, pedido + protocolo completo — §4.1), não a cópia crua do retorno que esta aplicação arquiva por conta própria; é o documento correto a manter/enviar, equivalente ao `procNFe` de notas normais.

Nome do arquivo: `<nome_fantasia ou razão_social>_<CNPJ>_dfe-inutilizações-autorizadas_dd-mm-aaaa_HH-MM-SS.zip`. `nome_fantasia`/`razao_social` passam por `compactacao._sanitizar_para_nome_arquivo` (troca `<>:"/\|?*` por `_`) antes de virar nome de arquivo — são texto livre, podem conter qualquer caractere.

**Onde o `.zip` é salvo** (`app/services/compactacao.py::resolver_pasta_destino`):
1. `empresa.pasta_compactados`, se configurada e existir (ou puder ser criada);
2. senão, Área de Trabalho do usuário (`~/Desktop`);
3. senão, Documentos (`~/Documents`);
4. por fim, a pasta do usuário (`~`) — nunca falha silenciosamente por falta de pasta configurada.

**Texto de e-mail sugerido**: junto com o resultado da compactação, a API devolve um texto pronto (empresa, CNPJ formatado, lista de séries/números inutilizados) que a UI exibe num `<textarea>` com botão "Copiar". Esta aplicação **não envia e-mail** — nenhuma integração SMTP foi adicionada (fora do escopo definido nas diretrizes de desenvolvimento do projeto); o texto é só para o usuário colar no cliente de e-mail dele junto do `.zip`.

---

## 10. Verificação e controle do processo do UniNFe

Campo opcional `empresa.uninfe.executavel` (caminho completo, ex.: `C:\Unimake\UniNFe\UniNFe.exe` — a **raiz** da instalação, não a subpasta por CNPJ). Se configurado, a UI chama `GET /api/uninfe-status` a cada carregamento da página (antes de conectar o SSE/liberar os botões), implementado em `app/services/uninfe_processo.py`:

| Situação | Estado | Ação da UI |
|---|---|---|
| Pasta de instalação (`executavel.parent`) não existe | `nao_instalado` | Bloqueia o uso (botões desabilitados, banner vermelho + modal) com mensagem pedindo para instalar o UniNFe |
| Pasta existe, mas o arquivo do executável não | `executavel_nao_encontrado` | Mesmo bloqueio, mensagem indicando o caminho esperado |
| Processo já está rodando (`tasklist`) | `ativo` | Libera o uso normalmente |
| Instalado mas não está rodando | — | Tenta iniciar (`subprocess.Popen`) e faz polling via `tasklist` até detectar o processo (timeout configurável, padrão 20s) — se conseguir, trata como `ativo`; se não, `falha_ao_iniciar` (bloqueia) |
| `executavel` não configurado no JSON | `nao_configurado` | Não bloqueia — comportamento anterior (sem essa verificação) |

**Limitação assumida conscientemente:** não existe uma forma simples de checar a presença de um ícone na bandeja do Windows sem depender da API de shell do Windows (COM, via `pywin32` — uma dependência nova, evitada por decisão de manter dependências ao mínimo necessário). "Processo em execução" (via `tasklist`) + uma folga de ~2s depois de detectado é usado como aproximação prática de "UniNFe estabilizou" — não é uma confirmação de que o ícone realmente apareceu na bandeja.

`tasklist`/`taskkill` rodam via `subprocess` com `creationflags=CREATE_NO_WINDOW` (evita o flash de uma janela de console a cada verificação, já que o `.exe` final é `--windowed`).

**Encerrar aplicativo** (`POST /api/encerrar`) também chama `taskkill /IM UniNFe.exe /F` (best-effort — falha ao encerrar o UniNFe não impede o encerramento do próprio processo desta aplicação) quando `executavel` está configurado.

---

## 11. Instância única

`run.py::main()` chama `app/services/instancia_unica.py::tentar_reservar_porta(HOST, PORT)` **antes** de tentar subir o próprio servidor: tenta um `bind()` de verdade em `127.0.0.1:8000` (sem `SO_REUSEADDR`, de propósito — no Windows essa opção afrouxa a exclusividade do bind e anularia a checagem).

- Se conseguir reservar → fecha esse socket de prova (libera a porta pro Uvicorn bindar de verdade logo em seguida) e segue o fluxo normal.
- Se a porta já estiver ocupada (`OSError`) → outra instância já está rodando; só abre o navegador nela (`webbrowser.open`) e sai, **sem** chamar `uvicorn.run()`.

**Por que `bind()` e não "perguntar antes" (checar `tasklist`/`GET /health` se já existe outra instância):** a primeira versão desta checagem fazia exatamente isso, e tinha uma brecha real — reproduzida com um teste de lançamento simultâneo de verdade: duas instâncias abertas quase ao mesmo tempo rodaram a checagem no mesmo intervalo, **as duas concluíram "já tem outra rodando" e as duas desistiram**, e nenhum servidor subiu. `bind()` não tem essa brecha: o sistema operacional só deixa **um** processo reivindicar um `(host, porta)` por vez, de forma atômica — não existe "os dois acham que o outro ganhou". A janela entre fechar o socket de prova e o Uvicorn bindar de novo é só overhead de Python (microssegundos), não mais o tempo de inicialização inteiro (import de libs, extração do `--onefile`) que motivou a checagem em primeiro lugar.

**Por que isso importa especificamente para o build `--onefile`:** sem essa checagem, abrir o `.exe` uma segunda vez faz o novo processo tentar ocupar a porta 8000 já em uso, falhar com erro de bind, e esse crash no processo filho pode deixar o processo bootloader pai pendurado no Gerenciador de Tarefas (o bootloader só limpa direito quando o filho termina normalmente). Com a checagem, a segunda tentativa nunca chega a tentar o bind pelo Uvicorn — só abre o navegador e retorna de `main()` normalmente, processo termina limpo.

**Nota sobre uma linha de log aparentemente duplicada:** num teste real de lançamento quase simultâneo das duas instâncias, o log mostrou `Started server process [PID]` **duas vezes**, uma para cada processo — mesmo com a checagem acima funcionando corretamente. Isso é esperado e inofensivo: o próprio Uvicorn roda o `lifespan` da aplicação (e loga esse banner) **antes** de tentar o `bind()` real do socket de rede (`Server.startup()` chama `self.lifespan.startup()` primeiro, só then `loop.create_server(host, port)`). Então é possível, numa janela de tempo muito estreita, as duas instâncias passarem pela checagem `tentar_reservar_porta()` (por ex. se uma fechou o socket de prova bem no instante em que a outra tentava reservar) e ambas chegarem ao banner do Uvicorn — mas só uma consegue o bind de verdade; a perdedora recebe `OSError` (`WinError 10048`), loga o erro, desliga o `lifespan` de forma limpa (`Application shutdown complete`) e sai (`sys.exit`). Ou seja: o `bind()` do Uvicorn é uma segunda camada de arbitragem atômica, igualmente segura — não há processo órfão nem UI travada nesse cenário, só uma linha de log a mais que pode confundir quem estiver investigando.

Uma alternativa cogitada foi passar o socket de prova diretamente pro Uvicorn via `uvicorn.run(..., fd=...)` em vez de fechá-lo e deixar o Uvicorn bindar de novo — eliminaria até essa janela estreita. **Descartada**: o código do Uvicorn (`Config.bind_socket`/`Server.startup`, caminho `fd is not None`) constrói o socket com `socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)` — família `AF_UNIX` fixa, e esse trecho é explicitamente marcado `pragma: py-win32` (excluído da cobertura no Windows) no código-fonte do próprio Uvicorn. Não é a família certa pra um socket TCP, e não é um caminho exercitado/suportado no Windows, que é a plataforma alvo deste app — usar `fd=` arriscaria trocar um problema cosmético (linha de log a mais, sem efeito real) por um bug de verdade.

---

## 12. Ferramenta auxiliar de detecção de lacunas (`scanner_lacunas`) — **proposta, ainda não implementada**

> Diferente das seções anteriores (que descrevem comportamento já implementado e validado em homologação/produção), esta seção é um **desenho em aberto**, registrado aqui antes de codificar (prática padrão deste projeto: desenho primeiro, código depois) para o usuário validar/corrigir. Nada abaixo deve ser tratado como implementado até que os testes unitários existam, seguindo o checklist de implementação do projeto.

### 12.1 Motivação e escopo

Hoje a detecção de lacunas de numeração é 100% manual: o sistema de contabilidade aponta a quebra, e o operador digita cada número/faixa direto no `sgc_dfe_inutilizacao.json` (ou numa versão futura, numa tela própria). Esta ferramenta auxilia essa etapa, **sem** assumir o envio à SEFAZ:

- **Faz:** varre XMLs de DF-e já emitidos (autorizados, eventos de cancelamento, denegados), calcula as faixas de numeração realmente "em uso" por `(CNPJ, modelo, série)`, identifica os números faltantes dentro do intervalo observado, e grava/atualiza um `sgc_dfe_inutilizacao.json` pronto para o `sgc_dfe_inutilizacao.exe` consumir.
- **Não faz:** não chama a SEFAZ, não grava nada na pasta de entrada do UniNFe, não altera o status de nenhuma solicitação existente. O envio continua 100% manual, pela UI já existente — mantém a regra do projeto de nunca automatizar uma ação irreversível perante a SEFAZ.

Dois ambientes de uso, sem diferença de código — só de qual pasta o operador aponta:
- **Ambiente 1** — computador do próprio emitente, lendo os XMLs no local real de emissão.
- **Ambiente 2** — computador da contabilidade, lendo XMLs recebidos do cliente (mesma estrutura de pastas ou não — daí os seletores de pasta manuais, §12.3).

### 12.2 Estrutura e nome

Vive no **mesmo repositório**, como um componente irmão de `app/`, não dentro dele — é uma ferramenta de preparação, com ciclo de vida e interface próprios, não uma rota do FastAPI:

```
sgc_dfe_inutilizacao/
├── app/                        # aplicação principal (sem mudanças)
├── scanner_lacunas/
│   ├── main.py                 # ponto de entrada (abre a janela Tkinter)
│   ├── gui.py                  # janela Tkinter: 3 seletores de pasta + botão Processar + log
│   ├── leitor_xml.py           # parse/classificação de procNFe, procNFCe, procEventoNFe, denegados
│   ├── detector_lacunas.py     # agrupamento por (CNPJ, modelo, serie) + cálculo de faixas faltantes
│   └── gerador_json.py         # cria/mescla sgc_dfe_inutilizacao.json de saída
├── tests/
│   └── test_scanner_lacunas/   # espelha a estrutura acima
└── ...
```

Reaproveita os modelos Pydantic já existentes (`app.models.empresa.Empresa`, `app.models.inutilizacao.SolicitacaoInutilizacao`/`InutilizacoesConfig`) para montar e validar o JSON de saída — evita duplicar regras de schema em dois lugares.

Interface **Tkinter** (stdlib, zero dependência nova) em vez de um mini web app: é uma ferramenta de uso pontual ("selecionar pastas → processar → conferir → fechar"), sem necessidade de tempo real/SSE como o app principal, e ganha de graça o diálogo nativo "Procurar pasta..." do Windows — um navegador não tem acesso equivalente sem gambiarras.

### 12.3 Interface — seleção de pastas

Três campos de pasta, cada um com botão "Procurar..." (`tkinter.filedialog.askdirectory`), **independentes entre si**:

| Campo | Papel |
|---|---|
| Pasta de autorizados | Onde estão os XMLs `procNFe`/`procNFCe` (documentos realmente emitidos e autorizados) |
| Pasta de eventos/cancelamentos | Onde estão os XMLs `procEventoNFe` de cancelamento |
| Pasta de denegados | Onde estão os XMLs de denegação |

> **Importante — não force 3 pastas fisicamente distintas:** no UniNFe (Unimake) real, confirmado pelo usuário, os eventos de cancelamento ficam **misturados dentro da própria pasta de Autorizados** (diferenciados pelo nome do arquivo/tag, não por subpasta separada) — só os denegados têm pasta própria (`Enviado\Denegados`). Nesse caso o operador aponta "Pasta de autorizados" e "Pasta de eventos/cancelamentos" para o **mesmo diretório físico**; o scanner filtra pelo conteúdo do XML, não assume que cada campo é uma pasta exclusiva. Três campos independentes existem para suportar outros ERPs/emissores que de fato separam fisicamente essas pastas.

### 12.4 Classificação dos XMLs

Classificação pela **tag raiz do XML**, nunca só pelo nome do arquivo (nomes variam entre instalações/versões do UniNFe):

| Tag raiz | Classificação | Números extraídos |
|---|---|---|
| `procNFe` / `nfeProc` (mod=55) | Documento autorizado | `<ide><nNF>`, `<serie>`, `<mod>`, `<emit><CNPJ>` diretamente |
| `procNFCe` (mod=65, conforme instalação) | Documento autorizado | idem |
| `procEventoNFe` | Evento — só interessa se `<infEvento><tpEvento>` = `110111` (Cancelamento); outros tipos (carta de correção `110110`, etc.) são ignorados para esta finalidade | `<infEvento><chNFe>` (chave de acesso, 44 dígitos) — não tem `<ide>` direto; decodificar por posição: `cUF(2)+AAMM(4)+CNPJ(14)+mod(2)+serie(3)+nNF(9)+tpEmis(1)+cNF(8)+cDV(1)` |
| XML de denegação | Denegado | `<ide>` quando presente, senão decodificar da chave de acesso como acima |

Conjunto de números **confirmados como "tratados"** por grupo `(CNPJ, modelo, série)` = autorizados ∪ cancelados ∪ denegados. Arquivos que não casam com nenhuma dessas classificações são ignorados silenciosamente (log de aviso, não erro).

### 12.5 Cálculo de lacunas e janela de segurança

Para cada grupo `(CNPJ, modelo, série)`: lacuna = número dentro de `[min, max]` observado que **não** está no conjunto confirmado.

**Janela de segurança (parametrizável, padrão proposto: últimos 15 números abaixo do maior `nNF` do grupo nunca entram na lista de lacunas confirmadas)** — motivo: um número muito próximo do topo da sequência pode estar apenas **em trânsito** (já emitido, ainda não sincronizado para a pasta de autorizados local) em vez de ser uma lacuna real; números no meio da sequência (cercados de números maiores já autorizados dos dois lados) não sofrem desse risco e são sinalizados sem essa cautela. Esse parâmetro é um ponto aberto de validação — ajustável conforme a experiência real de uso.

### 12.6 Geração/mescla do `sgc_dfe_inutilizacao.json` de saída

- **Arquivo inexistente na pasta de destino escolhida:** cria do zero — bloco `empresa` com os dados inferidos do primeiro `<emit>` lido (razão social, CNPJ, IE, UF); campos que o scanner não tem como descobrir (`uninfe.*`, `ambiente`) ficam com placeholder e um aviso explícito no log/relatório pedindo conferência manual antes do primeiro uso no `sgc_dfe_inutilizacao.exe`.
- **Arquivo já existente:** mescla **idempotente** — nunca altera nem remove nenhuma `solicitacoes[]` existente, **nunca toca no bloco `empresa`/`uninfe` já configurado**; só acrescenta entradas novas para lacunas ainda não presentes (casadas por `serie`+`modelo`+`numero`), com `id` sequencial a partir do maior `id` já usado, `status: "pendente"`, `justificativa: null`. Rodar o scanner várias vezes sobre o mesmo diretório de saída é seguro.
- O scanner **nunca** define `status` diferente de `pendente` nem grava fora do array `solicitacoes` — tudo o mais do ciclo de vida (§4.1) continua controlado exclusivamente pelo app principal.
