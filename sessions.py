"""
Gerenciamento de sessões de conversa em memória.
Cada número de telefone tem sua própria sessão com histórico e dados coletados.
"""

from datetime import datetime, timedelta
from typing import Optional


# Sessões ativas: { numero: { historico, dados, airtable_id, ultima_atividade } }
_sessions: dict = {}

SESSION_TIMEOUT_HOURS = 24


def get_or_create_session(numero: str) -> dict:
    """Retorna sessão existente ou cria uma nova."""
    if numero not in _sessions:
        _sessions[numero] = {
            "historico": [],
            "dados": {},
            "airtable_id": None,
            "ultima_atividade": datetime.now(),
            "coleta_completa": False
        }
    else:
        _sessions[numero]["ultima_atividade"] = datetime.now()

    return _sessions[numero]


def salvar_sessao(numero: str, sessao: dict):
    """Atualiza a sessão na memória."""
    sessao["ultima_atividade"] = datetime.now()
    _sessions[numero] = sessao


def sessao_existe(numero: str) -> bool:
    """Verifica se já existe sessão ativa para esse número."""
    return numero in _sessions and len(_sessions[numero]["historico"]) > 0


def limpar_sessoes_antigas():
    """Remove sessões inativas há mais de SESSION_TIMEOUT_HOURS."""
    agora = datetime.now()
    numeros_para_remover = [
        numero for numero, sessao in _sessions.items()
        if agora - sessao["ultima_atividade"] > timedelta(hours=SESSION_TIMEOUT_HOURS)
    ]
    for numero in numeros_para_remover:
        del _sessions[numero]

    if numeros_para_remover:
        print(f"Sessões limpas: {len(numeros_para_remover)}")


def total_sessoes_ativas() -> int:
    return len(_sessions)
