"""Testes do motor de palavras-chave."""

from __future__ import annotations

from radar_cpsi.config import KeywordConfig
from radar_cpsi.keywords import KeywordMatcher, normalize


def make_matcher() -> KeywordMatcher:
    config = KeywordConfig(
        cpsi_signals=["CPSI", "solução inovadora", "Lei Complementar 182"],
        video_group=["videomonitoramento", "CFTV", "câmeras", "reconhecimento facial"],
    )
    return KeywordMatcher(config)


def test_normalize_removes_accents_and_case():
    assert normalize("Câmeras de Segurança") == "cameras de seguranca"
    assert normalize("VIDEOMONITORAMENTO") == "videomonitoramento"


def test_match_requires_both_groups():
    m = make_matcher()
    # tem CPSI + vídeo -> match
    r = m.evaluate("Contratação de solução inovadora para videomonitoramento urbano")
    assert r.is_match
    assert "solução inovadora" in r.cpsi_hits
    assert "videomonitoramento" in r.video_hits


def test_no_match_when_only_cpsi():
    m = make_matcher()
    r = m.evaluate("Edital de CPSI para gestão de merenda escolar")
    assert not r.is_match
    assert r.cpsi_hits and not r.video_hits


def test_no_match_when_only_video():
    m = make_matcher()
    r = m.evaluate("Licitação para instalação de CFTV e câmeras nas escolas")
    assert not r.is_match
    assert r.video_hits and not r.cpsi_hits


def test_accent_insensitive_match():
    m = make_matcher()
    # sem acentos no texto de entrada
    r = m.evaluate("contratacao de solucao inovadora com cameras e reconhecimento facial")
    assert r.is_match


def test_word_boundary_avoids_false_positive():
    m = make_matcher()
    # "cftvx" não deve casar com "CFTV"
    r = m.evaluate("solução inovadora sistema cftvxyz qualquer")
    assert not r.is_match  # nenhum termo de vídeo real


def test_multiple_fields_combined():
    m = make_matcher()
    # sinal de CPSI no título, termo de vídeo na descrição
    r = m.evaluate("Edital CPSI 01/2025", "Implantação de videomonitoramento com IA")
    assert r.is_match


def test_flexible_whitespace_in_expression():
    m = make_matcher()
    # quebra de linha no meio da expressão (comum em PDFs)
    r = m.evaluate("solução\n  inovadora para videomonitoramento")
    assert r.is_match
