"""Registro de fontes oficiais gov.br para o Murdock."""
from dataclasses import dataclass, field


@dataclass
class FonteOficial:
    id: str
    nome: str
    url: str
    source_type: str
    parser: str  # html, api_json, pdf, csv
    orgao: str
    fundamentacao: str
    descricao: str
    requer_auth: bool = False


FONTES: list[FonteOficial] = [
    # ── Legislação Federal ──────────────────────────────────────
    FonteOficial("lc_123_2006", "LC 123/2006 — Simples Nacional",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "LC 123/2006", "Simples Nacional: anexos I-V, faixas, alíquotas, fator R"),
    FonteOficial("lc_87_1996", "LC 87/1996 — Lei Kandir (ICMS)",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "LC 87/1996", "ICMS: fato gerador, base de cálculo, ST, isenções"),
    FonteOficial("lc_116_2003", "LC 116/2003 — ISS",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp116.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "LC 116/2003", "ISS: lista de serviços, local de incidência, alíquotas"),
    FonteOficial("lc_214_2025", "LC 214/2025 — Reforma CBS/IBS",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        "fiscal_reforma", "html", "Presidência da República",
        "LC 214/2025", "CBS/IBS: alíquotas, transição, regimes específicos, split payment"),
    FonteOficial("lei_10637", "Lei 10.637/2002 — PIS não-cumulativo",
        "https://www.planalto.gov.br/ccivil_03/leis/2002/l10637.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "Lei 10.637/2002", "PIS não-cumulativo: 1,65%, créditos, insumos"),
    FonteOficial("lei_10833", "Lei 10.833/2003 — COFINS não-cumulativo",
        "https://www.planalto.gov.br/ccivil_03/leis/2003/l10.833.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "Lei 10.833/2003", "COFINS não-cumulativo: 7,6%, créditos, retenções"),
    FonteOficial("lei_15270", "Lei 15.270/2025 — IRPF e Dividendos",
        "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/L15270.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "Lei 15.270/2025", "IRPF: isenção R$5k, IRPFM 10%, dividendos 10% >R$50k"),
    FonteOficial("ctn", "CTN — Código Tributário Nacional",
        "https://www.planalto.gov.br/ccivil_03/leis/l5172compilado.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "Lei 5.172/1966", "CTN: normas gerais, obrigação tributária, prescrição, decadência"),
    FonteOficial("cf_tributario", "CF/88 — Sistema Tributário Nacional",
        "https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm",
        "fiscal_legislacao", "html", "Presidência da República",
        "CF/88 arts. 145-162", "Competências, imunidades, princípios tributários"),

    # ── Receita Federal ─────────────────────────────────────────
    FonteOficial("siscomex_ncm", "SISCOMEX — NCM (API JSON)",
        "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json",
        "fiscal_ncm", "api_json", "SISCOMEX",
        "Decreto 11.158/2022", "~14.000 NCMs com descrição e alíquota IPI"),

    # ── STF / STJ ───────────────────────────────────────────────
    FonteOficial("stf_rg", "STF — Repercussão Geral",
        "https://portal.stf.jus.br/jurisprudenciaRepercussao/",
        "fiscal_stf", "html", "STF",
        "Art. 102 §3º CF", "Temas tributários com repercussão geral"),
    FonteOficial("stj_repetitivos", "STJ — Recursos Repetitivos",
        "https://processo.stj.jus.br/repetitivos/temas_repetitivos/",
        "fiscal_stj", "html", "STJ",
        "Art. 1.036 CPC", "Temas repetitivos tributários"),

    # ── CONFAZ ──────────────────────────────────────────────────
    FonteOficial("confaz_convenios", "CONFAZ — Convênios ICMS",
        "https://www.confaz.fazenda.gov.br/legislacao/convenios",
        "fiscal_confaz", "html", "CONFAZ",
        "LC 24/1975", "Convênios ICMS: benefícios, reduções, ST"),

    # ── Reforma ─────────────────────────────────────────────────
    FonteOficial("fazenda_reforma", "Min. Fazenda — Reforma Tributária",
        "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria",
        "fiscal_reforma", "html", "Ministério da Fazenda",
        "EC 132/2023 + LC 214/2025", "Materiais oficiais sobre a reforma"),

    # ── Simples Nacional ────────────────────────────────────────
    FonteOficial("cgsn_resolucoes", "CGSN — Resoluções Simples Nacional",
        "https://www8.receita.fazenda.gov.br/SimplesNacional/Legislacao/Resolucoes.aspx",
        "fiscal_simples", "html", "CGSN",
        "LC 123/2006 art. 2º", "Resoluções: tabelas, sublimites, MEI, atividades"),
]


def get_fonte(fonte_id: str) -> FonteOficial | None:
    return next((f for f in FONTES if f.id == fonte_id), None)


def get_fontes_ativas() -> list[FonteOficial]:
    return [f for f in FONTES if not f.requer_auth]
