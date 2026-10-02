from datetime import date

import pytest
from lxml import etree

from app.models.empresa import Empresa
from app.models.inutilizacao import InutilizacoesConfig, SolicitacaoInutilizacao
from app.services.xml_builder import (
    NFE_NAMESPACE,
    XmlBuilderError,
    calcular_id,
    montar_xml_inutilizacao,
    sanitizar_justificativa,
    substituir_macros_justificativa,
)

ID_REFERENCIA = "ID3526071122233300018155003000009434000009434"
HOJE_REFERENCIA = date(2026, 7, 15)
"""Data do pedido usada no caso de referência (CONTEXT.md §5.1) — o Id
depende de AAMM = data em que o pedido é gerado, não mais de uma
"competência" configurada, então os testes fixam a data explicitamente
para manter o resultado determinístico."""


@pytest.fixture
def empresa(tmp_path):
    for sub in ("entrada", "saida", "erro", "destino"):
        (tmp_path / sub).mkdir()
    return Empresa.model_validate(
        {
            "razao_social": "Empresa Exemplo Contabilidade",
            "cnpj": "11222333000181",
            "inscricao_estadual": "123456789012",
            "uf": "SP",
            "codigo_uf": 35,
            "ambiente": 2,
            "modelo_dfe": 55,
            "uninfe": {
                "pasta_entrada": str(tmp_path / "entrada"),
                "pasta_saida": str(tmp_path / "saida"),
                "pasta_erro": str(tmp_path / "erro"),
                "pasta_destino_autorizados": str(tmp_path / "destino"),
            },
        }
    )


@pytest.fixture
def cfg():
    return InutilizacoesConfig(
        justificativa_padrao="Quebra de sequencia solicitada pela contabilidade Empresa Exemplo",
        solicitacoes=[],
    )


@pytest.fixture
def item_9434():
    return SolicitacaoInutilizacao(id="1", serie=3, modelo=55, numero_inicial=9434, numero_final=9434)


def test_calcular_id_caso_referencia(empresa, item_9434):
    assert calcular_id(empresa, item_9434, hoje=HOJE_REFERENCIA) == ID_REFERENCIA
    assert len(ID_REFERENCIA) == 45


def test_calcular_id_usa_data_atual_por_padrao(empresa, item_9434, monkeypatch):
    """Sem `hoje` explícito, usa a data real do sistema (não uma competência
    configurada) — só confirmamos que o AAMM bate com `date.today()`."""
    id_ = calcular_id(empresa, item_9434)
    aamm_esperado = f"{date.today():%y%m}"
    assert id_[4:8] == aamm_esperado


def test_montar_xml_caso_referencia(empresa, cfg, item_9434):
    pedido = montar_xml_inutilizacao(empresa, cfg, item_9434, hoje=HOJE_REFERENCIA)

    assert pedido.id == ID_REFERENCIA
    assert pedido.nome_base == ID_REFERENCIA[2:]
    assert len(pedido.nome_base) == 43

    root = etree.fromstring(pedido.xml.encode("utf-8"))
    ns = {"nfe": NFE_NAMESPACE}
    assert root.tag == f"{{{NFE_NAMESPACE}}}inutNFe"
    inf_inut = root.find("nfe:infInut", ns)
    assert inf_inut.get("Id") == ID_REFERENCIA
    assert inf_inut.find("nfe:tpAmb", ns).text == "2"
    assert inf_inut.find("nfe:xServ", ns).text == "INUTILIZAR"
    assert inf_inut.find("nfe:cUF", ns).text == "35"
    assert inf_inut.find("nfe:ano", ns).text == "26"
    assert inf_inut.find("nfe:CNPJ", ns).text == "11222333000181"
    assert inf_inut.find("nfe:mod", ns).text == "55"
    assert inf_inut.find("nfe:serie", ns).text == "3"
    assert inf_inut.find("nfe:nNFIni", ns).text == "9434"
    assert inf_inut.find("nfe:nNFFin", ns).text == "9434"
    assert len(inf_inut.find("nfe:xJust", ns).text) >= 15


def test_calcular_id_faixa_diferente_de_numero_unico(empresa):
    item = SolicitacaoInutilizacao(id="2", serie=3, modelo=55, numero_inicial=100, numero_final=105)
    id_ = calcular_id(empresa, item, hoje=HOJE_REFERENCIA)
    assert id_.endswith("000000100000000105")


def test_calcular_id_varia_com_serie_e_modelo_do_item(empresa):
    """Motivação da mudança: solicitações do mesmo lote podem ter
    serie/modelo diferentes (ex.: NF-e série 3 x NFC-e série 1)."""
    item_nfe = SolicitacaoInutilizacao(id="1", serie=3, modelo=55, numero_inicial=1, numero_final=1)
    item_nfce = SolicitacaoInutilizacao(id="2", serie=1, modelo=65, numero_inicial=1, numero_final=1)

    id_nfe = calcular_id(empresa, item_nfe, hoje=HOJE_REFERENCIA)
    id_nfce = calcular_id(empresa, item_nfce, hoje=HOJE_REFERENCIA)

    assert id_nfe != id_nfce
    # mod(2) + serie(3) ficam logo após cUF(2)+AAMM(4)+CNPJ(14) = posição 22
    assert id_nfe[22:27] == "55003"
    assert id_nfce[22:27] == "65001"


def test_sanitizar_justificativa_remove_acentos_e_simbolos():
    assert sanitizar_justificativa("Emissão inválida: número duplicado!!") == (
        "Emissao invalida: numero duplicado"
    )


def test_montar_xml_justificativa_curta_apos_sanitizacao_falha(empresa, cfg):
    # 17 caracteres, todos fora do conjunto permitido -> sanitiza para "" (< 15)
    item = SolicitacaoInutilizacao(
        id="4", serie=3, modelo=55, numero_inicial=1, numero_final=1, justificativa="!!!!!!!!!!!!!!!!!"
    )
    with pytest.raises(XmlBuilderError):
        montar_xml_inutilizacao(empresa, cfg, item, hoje=HOJE_REFERENCIA)


def test_substituir_macros_justificativa(empresa):
    texto = substituir_macros_justificativa(
        "Solicitado por <razao_social> - CNPJ <cnpj>", empresa
    )
    assert texto == "Solicitado por Empresa Exemplo Contabilidade - CNPJ 11.222.333/0001-81"


def test_substituir_macros_justificativa_sem_macros_nao_altera(empresa):
    texto = substituir_macros_justificativa("Texto fixo sem nenhum macro", empresa)
    assert texto == "Texto fixo sem nenhum macro"


def test_montar_xml_aplica_macros_na_justificativa_padrao(empresa, item_9434):
    cfg = InutilizacoesConfig(
        justificativa_padrao="Quebra solicitada pela contabilidade <razao_social> - CNPJ <cnpj>",
        solicitacoes=[],
    )
    pedido = montar_xml_inutilizacao(empresa, cfg, item_9434, hoje=HOJE_REFERENCIA)

    assert "Empresa Exemplo Contabilidade" in pedido.xml
    assert "11.222.333/0001-81" in pedido.xml
    assert "<razao_social>" not in pedido.xml
    assert "<cnpj>" not in pedido.xml


def test_montar_xml_usa_justificativa_especifica_do_item(empresa, cfg):
    item = SolicitacaoInutilizacao(
        id="5",
        serie=3,
        modelo=55,
        numero_inicial=1,
        numero_final=1,
        justificativa="Justificativa especifica deste item de teste",
    )
    pedido = montar_xml_inutilizacao(empresa, cfg, item, hoje=HOJE_REFERENCIA)
    assert "Justificativa especifica" in pedido.xml
