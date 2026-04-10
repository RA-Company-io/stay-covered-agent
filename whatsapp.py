"""
Cliente Z-API para envio/recebimento de mensagens WhatsApp
"""

import httpx
import os
from typing import Optional

ZAPI_INSTANCE = os.getenv("ZAPI_INSTANCE", "3F1758F93BD46253307C667E5D6D48C0")
ZAPI_TOKEN    = os.getenv("ZAPI_TOKEN", "C1694AB45B6FDBC5213DC780")
ZAPI_BASE     = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}"


def _numero_limpo(numero: str) -> str:
    """Remove caracteres não numéricos e garante DDI."""
    n = "".join(c for c in numero if c.isdigit())
    if not n.startswith("55") and len(n) <= 11:
        n = "55" + n
    return n


async def enviar_mensagem(numero: str, texto: str) -> bool:
    """Envia mensagem de texto via Z-API."""
    url = f"{ZAPI_BASE}/send-text"
    payload = {
        "phone": _numero_limpo(numero),
        "message": texto
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Erro ao enviar mensagem para {numero}: {e}")
            return False


async def enviar_para_grupo(grupo_id: str, texto: str) -> bool:
    """Envia mensagem para um grupo do WhatsApp."""
    url = f"{ZAPI_BASE}/send-text"
    payload = {
        "phone": grupo_id,
        "message": texto
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Erro ao enviar para grupo {grupo_id}: {e}")
            return False


async def listar_grupos() -> list:
    """Lista grupos disponíveis."""
    url = f"{ZAPI_BASE}/chats"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            chats = response.json()
            return [
                {"id": c.get("id"), "nome": c.get("name")}
                for c in chats
                if c.get("isGroup")
            ]
        except Exception as e:
            print(f"Erro ao listar grupos: {e}")
            return []


def extrair_numero_e_mensagem(webhook_data: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extrai número, mensagem e tipo do webhook da Z-API.
    Retorna (numero, mensagem, tipo)
    """
    try:
        # Ignora mensagens enviadas pelo próprio bot
        if webhook_data.get("fromMe"):
            return None, None, None

        # Ignora mensagens de grupo
        phone = webhook_data.get("phone", "")
        if "@g.us" in phone or webhook_data.get("isGroup"):
            return None, None, "grupo"

        numero = phone.replace("@c.us", "").replace("+", "")

        # Texto simples
        text_obj = webhook_data.get("text")
        if text_obj and isinstance(text_obj, dict):
            mensagem = text_obj.get("message", "")
            if mensagem:
                return numero, mensagem, "texto"

        # Imagem com legenda
        if webhook_data.get("image"):
            legenda = webhook_data.get("image", {}).get("caption", "")
            return numero, f"[imagem] {legenda}".strip(), "imagem"

        # Documento
        if webhook_data.get("document"):
            return numero, "[documento enviado]", "documento"

        return numero, None, "outro"

    except Exception as e:
        print(f"Erro ao extrair dados do webhook Z-API: {e}")
        return None, None, None
