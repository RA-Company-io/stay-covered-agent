"""
Stay Covered Insurance - WhatsApp Agent + CRM
Deploy: Railway
"""

import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import (
    init_db, get_or_create_lead, update_lead_fields, update_last_message,
    get_all_leads, get_lead_by_id, save_message, get_messages,
    get_messages_for_agent, get_new_messages_since
)
from agent import processar_mensagem, formatar_notificacao, mensagem_inicial
from whatsapp import enviar_mensagem, enviar_para_grupo, extrair_numero_e_mensagem, listar_grupos
from followups import run_followup_scheduler

# ── Config ────────────────────────────────────────────────────────────────────

GRUPO_SOCIOS_ID  = os.getenv("GRUPO_SOCIOS_ID")
WEBHOOK_TOKEN    = os.getenv("WEBHOOK_TOKEN", "staycovered2024")
CRM_USERNAME     = os.getenv("CRM_USERNAME", "admin")
CRM_PASSWORD     = os.getenv("CRM_PASSWORD", "staycovered2024")
SESSION_TOKEN    = os.getenv("SESSION_TOKEN", "crm_session_secret")

ALL_STATUSES = [
    "Iniciado", "Em andamento", "Pronto para cotar",
    "Cotado", "Fechado", "FUP EXTENDIDO", "Perdido"
]

STATUS_CLASSES = {
    "Iniciado":           "bg-gray-100 text-gray-600",
    "Em andamento":       "bg-blue-100 text-blue-700",
    "Pronto para cotar":  "bg-green-100 text-green-700",
    "Cotado":             "bg-purple-100 text-purple-700",
    "Fechado":            "bg-emerald-100 text-emerald-700",
    "FUP EXTENDIDO":      "bg-yellow-100 text-yellow-700",
    "Perdido":            "bg-red-100 text-red-600",
}

STATS_CONFIG = [
    ("Em andamento",      "bg-blue-400"),
    ("Pronto para cotar", "bg-green-400"),
    ("Cotado",            "bg-purple-400"),
    ("FUP EXTENDIDO",     "bg-yellow-400"),
    ("Perdido",           "bg-red-400"),
]

templates = Jinja2Templates(directory="templates")


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(run_followup_scheduler())
    yield
    task.cancel()

app = FastAPI(title="Stay Covered CRM", lifespan=lifespan)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def is_authenticated(request: Request) -> bool:
    return request.cookies.get("session") == SESSION_TOKEN


def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == CRM_USERNAME and password == CRM_PASSWORD:
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("session", SESSION_TOKEN, httponly=True, max_age=86400 * 30)
        return response
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Usuário ou senha incorretos."
    })


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ── CRM routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    leads = await get_all_leads()

    # Enrich leads for display
    enriched = []
    for lead in leads:
        lead["status_class"] = STATUS_CLASSES.get(lead["status"], "bg-gray-100 text-gray-600")
        lead["tempo_relativo"] = _tempo_relativo(lead.get("updated_at"))
        lead["last_message_preview"] = ""
        enriched.append(lead)

    # Stats
    status_counts = {}
    for lead in leads:
        s = lead["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = [
        {"label": label, "color": color, "count": status_counts.get(label, 0)}
        for label, color in STATS_CONFIG
    ]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "leads": enriched,
        "total_leads": len(leads),
        "stats": stats,
    })


@app.get("/lead/{lead_id}", response_class=HTMLResponse)
async def lead_detail(request: Request, lead_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    lead = await get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    messages = await get_messages(lead_id)
    lead["status_class"] = STATUS_CLASSES.get(lead["status"], "bg-gray-100 text-gray-600")
    last_msg_id = messages[-1]["id"] if messages else 0

    return templates.TemplateResponse("lead.html", {
        "request": request,
        "lead": lead,
        "messages": messages,
        "last_msg_id": last_msg_id,
        "all_statuses": ALL_STATUSES,
    })


# ── CRM API endpoints ─────────────────────────────────────────────────────────

@app.get("/api/lead/{lead_id}/messages")
async def api_get_messages(request: Request, lead_id: int, since: int = 0):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)
    msgs = await get_new_messages_since(lead_id, since)
    return {"messages": msgs}


@app.post("/api/lead/{lead_id}/send")
async def api_send_manual(request: Request, lead_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)

    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    lead = await get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404)

    await enviar_mensagem(lead["numero_wpp"], message)
    await save_message(lead_id, "assistant", message)
    await update_last_message(lead_id)
    return {"ok": True}


@app.post("/api/lead/{lead_id}/bot")
async def api_toggle_bot(request: Request, lead_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)
    body = await request.json()
    active = 1 if body.get("active") else 0
    await update_lead_fields(lead_id, {"bot_ativo": active})
    return {"ok": True, "bot_ativo": active}


@app.post("/api/lead/{lead_id}/status")
async def api_update_status(request: Request, lead_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)
    body = await request.json()
    status = body.get("status")
    if status not in ALL_STATUSES:
        raise HTTPException(status_code=400, detail="Status inválido")
    await update_lead_fields(lead_id, {"status": status})
    return {"ok": True}


# ── WhatsApp webhook ──────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request):
    # Z-API envia token como query param
    token = request.query_params.get("token", "")
    if token != WEBHOOK_TOKEN:
        print(f"[webhook] token inválido recebido: '{token}'")
        raise HTTPException(status_code=401)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400)

    numero, mensagem, tipo = extrair_numero_e_mensagem(data)
    print(f"[webhook] tipo={tipo} numero={numero} fromMe={data.get('fromMe')} phone={data.get('phone')}")

    if not numero or not mensagem or tipo != "texto":
        return JSONResponse({"status": "ignored", "tipo": tipo})

    asyncio.create_task(_processar_mensagem(numero, mensagem))
    return JSONResponse({"status": "processing"})


async def _processar_mensagem(numero: str, mensagem: str):
    try:
        lead = await get_or_create_lead(numero)
        lead_id = lead["id"]

        # Se bot desativado (atendimento manual), só salva a mensagem
        if not lead.get("bot_ativo", 1):
            await save_message(lead_id, "user", mensagem)
            await update_last_message(lead_id)
            return

        historico = await get_messages_for_agent(lead_id)
        eh_novo = len(historico) == 0

        if eh_novo:
            boas_vindas = mensagem_inicial()
            await enviar_mensagem(numero, boas_vindas)
            await save_message(lead_id, "user", mensagem)
            await save_message(lead_id, "assistant", boas_vindas)
            await update_lead_fields(lead_id, {"status": "Em andamento"})
            await update_last_message(lead_id)
            return

        await save_message(lead_id, "user", mensagem)
        await update_last_message(lead_id)

        historico = await get_messages_for_agent(lead_id)
        dados_atuais = _lead_to_dados(lead)

        resposta, dados_atualizados, coleta_completa = await processar_mensagem(
            numero, mensagem, {"historico": historico, "dados": dados_atuais}
        )

        await enviar_mensagem(numero, resposta)
        await save_message(lead_id, "assistant", resposta)

        # Persist collected fields
        db_fields = {k: v for k, v in dados_atualizados["dados"].items() if v}
        if db_fields:
            await update_lead_fields(lead_id, _dados_to_db(db_fields))

        if coleta_completa and lead["status"] != "Pronto para cotar":
            await update_lead_fields(lead_id, {"status": "Pronto para cotar"})
            if GRUPO_SOCIOS_ID:
                notif = formatar_notificacao(dados_atualizados["dados"], numero)
                await enviar_para_grupo(GRUPO_SOCIOS_ID, notif)

    except Exception as e:
        import traceback
        print(f"[webhook] ERRO ao processar {numero}: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        await enviar_mensagem(numero, "Desculpe, tive um probleminha técnico! 😅 Pode repetir?")


# ── Utility routes ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "online", "empresa": "Stay Covered Insurance"}


@app.get("/grupos")
async def grupos(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)
    return {"grupos": await listar_grupos(), "raw": await _raw_grupos()}


async def _raw_grupos():
    import httpx as _httpx
    from whatsapp import ZAPI_BASE, _headers
    try:
        async with _httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{ZAPI_BASE}/chats", headers=_headers())
            chats = r.json()
            return [c for c in chats if c.get("isGroup")]
    except Exception as e:
        return [{"error": str(e)}]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lead_to_dados(lead: dict) -> dict:
    return {
        "nome_completo":   lead.get("nome"),
        "email":           lead.get("email"),
        "telefone":        lead.get("telefone"),
        "data_nascimento": lead.get("data_nascimento"),
        "driver_license":  lead.get("driver_license"),
        "estado_civil":    lead.get("estado_civil"),
        "endereco":        lead.get("endereco"),
        "vin":             lead.get("vin"),
        "imovel_tipo":     lead.get("imovel_tipo"),
    }


def _dados_to_db(dados: dict) -> dict:
    mapping = {
        "nome_completo":   "nome",
        "email":           "email",
        "telefone":        "telefone",
        "data_nascimento": "data_nascimento",
        "driver_license":  "driver_license",
        "estado_civil":    "estado_civil",
        "endereco":        "endereco",
        "vin":             "vin",
        "imovel_tipo":     "imovel_tipo",
    }
    return {mapping[k]: v for k, v in dados.items() if k in mapping and v}


def _tempo_relativo(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        diff = datetime.utcnow() - dt
        s = int(diff.total_seconds())
        if s < 60:       return "agora"
        if s < 3600:     return f"{s // 60}min"
        if s < 86400:    return f"{s // 3600}h"
        return f"{s // 86400}d"
    except Exception:
        return ""
