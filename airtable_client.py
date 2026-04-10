"""
Cliente Airtable para salvar leads da Stay Covered Insurance
"""

import httpx
import os
from datetime import datetime
from typing import Optional


AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "Leads")


def get_headers() -> dict:
    return {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }


async def salvar_lead(dados: dict, numero_wpp: str, status: str = "Em andamento") -> Optional[str]:
    """
    Salva ou atualiza um lead no Airtable.
    Retorna o ID do registro criado/atualizado.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"

    campos = {
        "Nome": dados.get("nome_completo", ""),
        "Email": dados.get("email", ""),
        "Telefone": dados.get("telefone", numero_wpp),
        "WhatsApp": numero_wpp,
        "Data de Nascimento": dados.get("data_nascimento", ""),
        "Driver's License": dados.get("driver_license", ""),
        "Estado Civil": dados.get("estado_civil", ""),
        "Endereço": dados.get("endereco", ""),
        "VIN": dados.get("vin", ""),
        "Imóvel": dados.get("imovel_tipo", ""),
        "Status": status,
        "Data de Entrada": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    # Remove campos vazios
    campos = {k: v for k, v in campos.items() if v}

    payload = {"fields": campos}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload, headers=get_headers())
            response.raise_for_status()
            record = response.json()
            return record.get("id")
        except Exception as e:
            print(f"Erro ao salvar lead no Airtable: {e}")
            return None


async def atualizar_status_lead(record_id: str, status: str) -> bool:
    """Atualiza o status de um lead existente."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"

    payload = {
        "fields": {"Status": status}
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.patch(url, json=payload, headers=get_headers())
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Erro ao atualizar lead {record_id}: {e}")
            return False


async def buscar_lead_por_wpp(numero_wpp: str) -> Optional[dict]:
    """Busca um lead existente pelo número de WhatsApp."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"

    params = {
        "filterByFormula": f"{{WhatsApp}}='{numero_wpp}'",
        "maxRecords": 1,
        "sort[0][field]": "Data de Entrada",
        "sort[0][direction]": "desc"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, params=params, headers=get_headers())
            response.raise_for_status()
            records = response.json().get("records", [])
            if records:
                return {"id": records[0]["id"], **records[0]["fields"]}
            return None
        except Exception as e:
            print(f"Erro ao buscar lead: {e}")
            return None
