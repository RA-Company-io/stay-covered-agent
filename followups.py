"""
Follow-up scheduler
Checks every minute for leads that stopped responding and sends automated messages.

Stages:
  0 = no follow-up sent yet
  1 = sent at 7 min
  2 = sent at 2h
  3 = sent at 24h
  4 = sent at 48h → status = "FUP EXTENDIDO"
"""

import asyncio
from datetime import datetime, timedelta

from database import get_leads_for_followup, update_lead_fields, save_message
from whatsapp import enviar_mensagem

# (stage, delay_minutes, message_template)
FOLLOWUP_STAGES = [
    (1, 7,       "Oi! Ainda tô aqui 😊"),
    (2, 120,     "{{nome}}! Ainda consigo ajudar com sua cotação? 🚗"),
    (3, 1440,    "Olá! Sua cotação gratuita ainda está disponível, e estamos com valores especiais nessa semana. Consegue me informar as informações que faltam? 😊"),
    (4, 2880,    "Oi {{nome}}! Faço uma última tentativa porque realmente quero te ajudar a ficar protegido aqui na Flórida. "
                 "Sei que a vida é corrida, mas um seguro de carro é obrigatório no estado e posso conseguir um valor bem acessível pra você. "
                 "Ainda tem interesse em receber sua cotação gratuita? 🙏"),
]


def _format(template: str, nome: str) -> str:
    first_name = (nome or "").split()[0] if nome else "tudo bem"
    return template.replace("{{nome}}", first_name)


async def run_followup_scheduler():
    """Background loop — runs forever, checks every 60 seconds."""
    while True:
        try:
            await _check_followups()
        except Exception as e:
            print(f"[followup] error: {e}")
        await asyncio.sleep(60)


async def _check_followups():
    leads = await get_leads_for_followup()
    if not leads:
        return

    now = datetime.utcnow()

    for lead in leads:
        last_msg_at = lead.get("last_message_at")
        if not last_msg_at:
            continue

        try:
            last_dt = datetime.fromisoformat(last_msg_at)
        except ValueError:
            continue

        current_stage = lead.get("follow_up_stage", 0)
        next_stage_index = current_stage  # index into FOLLOWUP_STAGES

        if next_stage_index >= len(FOLLOWUP_STAGES):
            continue

        stage_num, delay_min, template = FOLLOWUP_STAGES[next_stage_index]
        trigger_at = last_dt + timedelta(minutes=delay_min)

        if now < trigger_at:
            continue

        # Send follow-up
        nome = lead.get("nome") or ""
        message = _format(template, nome)
        numero = lead["numero_wpp"]

        sent = await enviar_mensagem(numero, message)
        if not sent:
            continue

        await save_message(lead["id"], "assistant", message)

        new_status = "FUP EXTENDIDO" if stage_num == 4 else lead["status"]
        await update_lead_fields(lead["id"], {
            "follow_up_stage": stage_num,
            "status": new_status,
        })

        print(f"[followup] stage {stage_num} sent to {numero} ({nome})")
