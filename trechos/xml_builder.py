"""Montagem do XML de Pedido de Inutilização de Numeração (``inutNFe``).

Função pura: recebe os dados já validados pelo Pydantic e devolve o XML
como string, sem qualquer efeito colateral (gravação em disco é
responsabilidade de ``uninfe_integration.py``). O XML gerado aqui **não é
assinado** — a assinatura digital (certificado A1/A3) é feita pelo UniNFe
ao processar o arquivo na pasta de entrada.

Referência de cálculo do ``Id`` e layout de campos: CONTEXT.md §5.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from lxml import etree

from app.formatadores import mascarar_cnpj
from app.models.empresa import Empresa
from app.models.inutilizacao import (
    JUSTIFICATIVA_MAX_LEN,
    JUSTIFICATIVA_MIN_LEN,
    InutilizacoesConfig,
    SolicitacaoInutilizacao,
)

NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
XSERV_INUTILIZAR = "INUTILIZAR"

# Caracteres aceitos em xJust após remoção de acentuação: letras/dígitos ASCII,
# espaço e pontuação básica presente nos exemplos oficiais de justificativa.
_CARACTERES_PERMITIDOS_RE = re.compile(r"[^A-Za-z0-9 .,;:\-/()]")
_ESPACOS_RE = re.compile(r"\s+")


class XmlBuilderError(Exception):
    """Dados insuficientes/inválidos para montar o XML de inutilização."""


@dataclass(frozen=True)
class PedidoInutilizacaoXML:
    """Resultado da montagem: XML pronto para gravação + identificadores."""

    id: str
    """Id de 45 caracteres do elemento ``infInut`` (com prefixo ``ID``)."""

    nome_base: str
    """``id`` sem o prefixo ``ID`` — usado para nomear os arquivos trocados
    com o UniNFe e correlacionar pedido↔retorno (CONTEXT.md §4.2)."""

    xml: str


def substituir_macros_justificativa(texto: str, empresa: Empresa) -> str:
    """Substitui macros de identificação da empresa em ``justificativa_padrao``
    (ou numa justificativa específica de item) — evita repetir razão
    social/CNPJ manualmente em cada instalação, mesmo espírito do ``{cnpj}``
    nos caminhos do UniNFe (``MACRO_CNPJ``/CONTEXT.md §3.1), mas com sintaxe
    ``<...>`` por ser texto livre lido por humanos (não um caminho de
    arquivo). O CNPJ entra mascarado, pois é texto que vai pro xJust lido
    por quem recebe o pedido, não um valor interno de correlação.
    """
    macros = {
        "<razao_social>": empresa.razao_social,
        "<cnpj>": mascarar_cnpj(empresa.cnpj),
    }
    for macro, valor in macros.items():
        texto = texto.replace(macro, valor)
    return texto


def sanitizar_justificativa(texto: str) -> str:
    """Remove acentuação e caracteres fora do conjunto aceito em ``xJust``.

    Ponto único de sanitização, por convenção do projeto — nenhum outro módulo
    deve tocar em ``xJust``.
    """
    normalizado = unicodedata.normalize("NFKD", texto)
    sem_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    limpo = _CARACTERES_PERMITIDOS_RE.sub("", sem_acentos)
    return _ESPACOS_RE.sub(" ", limpo).strip()


def calcular_id(
    empresa: Empresa, item: SolicitacaoInutilizacao, *, hoje: date | None = None
) -> str:
    """``Id = "ID" + cUF(2) + AAMM(4) + CNPJ(14) + mod(2) + serie(3) + nNFIni(9) + nNFFin(9)``.

    ``AAMM`` reflete a data em que o pedido está sendo gerado — não uma
    "competência" configurada previamente. É assim que a SEFAZ espera o
    campo (ano/mês do pedido, não do período de emissão das notas) e evita
    depender de um valor que o usuário precisaria lembrar de manter em dia
    a cada mês — ver CONTEXT.md §5.1.
    """
    hoje = hoje or date.today()
    cuf = str(empresa.codigo_uf).zfill(2)
    aamm = f"{hoje:%y%m}"
    mod = str(item.modelo.value).zfill(2)
    serie = str(item.serie).zfill(3)
    n_ini = str(item.numero_inicial).zfill(9)
    n_fin = str(item.numero_final).zfill(9)
    return f"ID{cuf}{aamm}{empresa.cnpj}{mod}{serie}{n_ini}{n_fin}"


def montar_xml_inutilizacao(
    empresa: Empresa,
    cfg: InutilizacoesConfig,
    item: SolicitacaoInutilizacao,
    *,
    hoje: date | None = None,
) -> PedidoInutilizacaoXML:
    hoje = hoje or date.today()
    justificativa_com_macros = substituir_macros_justificativa(cfg.justificativa_para(item), empresa)
    justificativa = sanitizar_justificativa(justificativa_com_macros)
    if not (JUSTIFICATIVA_MIN_LEN <= len(justificativa) <= JUSTIFICATIVA_MAX_LEN):
        raise XmlBuilderError(
            f"Justificativa da solicitação {item.id!r} tem {len(justificativa)} "
            f"caracteres após sanitização (mínimo {JUSTIFICATIVA_MIN_LEN}, máximo "
            f"{JUSTIFICATIVA_MAX_LEN}): {justificativa!r}"
        )

    id_ = calcular_id(empresa, item, hoje=hoje)

    inut_nfe = etree.Element(
        "inutNFe", nsmap={None: NFE_NAMESPACE}, versao="4.00"
    )
    inf_inut = etree.SubElement(inut_nfe, "infInut", Id=id_)
    etree.SubElement(inf_inut, "tpAmb").text = str(empresa.ambiente.value)
    etree.SubElement(inf_inut, "xServ").text = XSERV_INUTILIZAR
    etree.SubElement(inf_inut, "cUF").text = str(empresa.codigo_uf)
    etree.SubElement(inf_inut, "ano").text = f"{hoje:%y}"
    etree.SubElement(inf_inut, "CNPJ").text = empresa.cnpj
    etree.SubElement(inf_inut, "mod").text = str(item.modelo.value)
    etree.SubElement(inf_inut, "serie").text = str(item.serie)
    etree.SubElement(inf_inut, "nNFIni").text = str(item.numero_inicial)
    etree.SubElement(inf_inut, "nNFFin").text = str(item.numero_final)
    etree.SubElement(inf_inut, "xJust").text = justificativa

    xml_bytes = etree.tostring(
        inut_nfe, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )

    return PedidoInutilizacaoXML(
        id=id_, nome_base=id_[2:], xml=xml_bytes.decode("utf-8")
    )
