"""
Stay Covered Insurance - WhatsApp Agent
Coleta dados de leads brasileiros para cotação de seguro de carro
"""

import anthropic
import json
from typing import Optional

# Campos necessários para cotação
REQUIRED_FIELDS = [
    "nome_completo",
    "email",
    "telefone",
    "data_nascimento",
    "driver_license",
    "estado_civil",
    "endereco",
    "vin",
    "imovel_tipo",
]

FIELD_LABELS = {
    "nome_completo": "Nome completo",
    "email": "E-mail",
    "telefone": "Telefone",
    "data_nascimento": "Data de nascimento",
    "driver_license": "Número da carteira de motorista (Driver's License)",
    "estado_civil": "Estado civil",
    "endereco": "Endereço residencial completo",
    "vin": "VIN do veículo",
    "imovel_tipo": "Imóvel alugado ou próprio",
}

SYSTEM_PROMPT = """Você é a assistente virtual da Stay Covered Insurance, uma corretora de seguros em Orlando, Flórida, especializada em atender brasileiros.

Seu nome é Sofia. Você fala português, é simpática, direta e eficiente — como uma amiga que entende de seguros.

Seu objetivo é coletar as informações necessárias para fazer uma cotação de seguro de carro.

CAMPOS QUE VOCÊ PRECISA COLETAR (nessa ordem):
1. nome_completo — Nome completo
2. email — E-mail
3. telefone — Número de telefone (pode ser o próprio WPP)
4. data_nascimento — Data de nascimento
5. driver_license — Número da carteira de motorista americana (Driver's License)
6. estado_civil — Estado civil (solteiro, casado, divorciado, viúvo)
7. endereco — Endereço residencial completo (rua, cidade, estado, CEP)
8. vin — VIN do veículo (número de 17 dígitos no documento do carro)
9. imovel_tipo — O imóvel onde mora é alugado ou próprio?

REGRAS IMPORTANTES:
- Colete um campo por vez, de forma natural na conversa
- Se o cliente mandar múltiplas infos de uma vez, extraia todas e confirme
- Se uma informação parecer inválida (ex: VIN com menos de 17 caracteres), peça confirmação
- Nunca invente ou suponha dados — sempre confirme com o cliente
- Seja sempre educada, paciente e prestativa
- Se o cliente tiver dúvida sobre onde encontrar o VIN, explique: "O VIN fica no documento do veículo (title), no painel do carro (canto inferior do parabrisa) ou no seguro atual"
- Se o cliente tiver dúvida sobre Driver's License, lembre que é o número na carteira de motorista americana
- Ao finalizar, confirme todos os dados coletados com o cliente antes de encerrar

DADOS JÁ COLETADOS:
{dados_coletados}

PRÓXIMO CAMPO A COLETAR:
{proximo_campo}

Responda apenas com sua próxima mensagem para o cliente. Seja natural, não mencione "campo" ou listas técnicas."""


client = anthropic.AsyncAnthropic()


def get_next_field(dados: dict) -> Optional[str]:
    """Retorna o próximo campo que precisa ser coletado."""
    for field in REQUIRED_FIELDS:
        if not dados.get(field):
            return field
    return None


async def extract_data_from_conversation(historico: list, dados_atuais: dict) -> dict:
    """Usa Claude para extrair dados estruturados da conversa."""

    campos_faltando = [f for f in REQUIRED_FIELDS if not dados_atuais.get(f)]
    if not campos_faltando:
        return dados_atuais

    historico_texto = "\n".join([
        f"{'Cliente' if msg['role'] == 'user' else 'Sofia'}: {msg['content']}"
        for msg in historico[-6:]  # últimas 6 mensagens
    ])

    prompt = f"""Analise essa conversa e extraia os dados que o cliente forneceu.

CONVERSA:
{historico_texto}

DADOS JÁ CONFIRMADOS:
{json.dumps(dados_atuais, ensure_ascii=False, indent=2)}

CAMPOS QUE AINDA PRECISAM SER EXTRAÍDOS: {campos_faltando}

Retorne APENAS um JSON com os novos dados encontrados na última mensagem do cliente.
Se um campo não foi mencionado, não inclua no JSON.
Formato: {{"campo": "valor"}}
Apenas o JSON, sem explicações."""

    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        texto = response.content[0].text.strip()
        # Remove markdown se houver
        if "```" in texto:
            texto = texto.split("```")[1].replace("json", "").strip()
        novos_dados = json.loads(texto)
        dados_atuais.update(novos_dados)
    except Exception:
        pass

    return dados_atuais


async def gerar_resposta(historico: list, dados: dict) -> str:
    """Gera a próxima mensagem da Sofia baseada no histórico e dados coletados."""

    proximo_campo = get_next_field(dados)

    if proximo_campo is None:
        proximo_campo_texto = "TODOS OS CAMPOS COLETADOS - confirme os dados com o cliente e encerre"
    else:
        proximo_campo_texto = f"{proximo_campo} ({FIELD_LABELS[proximo_campo]})"

    dados_texto = json.dumps(dados, ensure_ascii=False, indent=2) if dados else "Nenhum dado coletado ainda"

    system = SYSTEM_PROMPT.format(
        dados_coletados=dados_texto,
        proximo_campo=proximo_campo_texto
    )

    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=system,
        messages=historico
    )

    return response.content[0].text


async def processar_mensagem(numero_telefone: str, mensagem: str, sessao: dict) -> tuple[str, dict, bool]:
    """
    Processa uma mensagem recebida e retorna (resposta, sessao_atualizada, coleta_completa).

    sessao = {
        "historico": [...],
        "dados": {...}
    }
    """

    # Adiciona mensagem do cliente ao histórico
    sessao["historico"].append({
        "role": "user",
        "content": mensagem
    })

    # Extrai dados da conversa
    sessao["dados"] = await extract_data_from_conversation(
        sessao["historico"],
        sessao["dados"]
    )

    # Verifica se coleta está completa
    coleta_completa = get_next_field(sessao["dados"]) is None

    # Gera resposta da Sofia
    resposta = await gerar_resposta(sessao["historico"], sessao["dados"])

    # Adiciona resposta ao histórico
    sessao["historico"].append({
        "role": "assistant",
        "content": resposta
    })

    return resposta, sessao, coleta_completa


def formatar_notificacao(dados: dict, numero_lead: str) -> str:
    """Formata a mensagem de notificação para o grupo dos sócios."""

    estado_civil_emoji = {
        "solteiro": "💍",
        "casado": "💑",
        "divorciado": "💔",
        "viúvo": "🕊️"
    }.get(dados.get("estado_civil", "").lower(), "💍")

    return f"""🔔 *Novo lead pronto para cotação!*
━━━━━━━━━━━━━━━━━━━━

👤 *Nome:* {dados.get('nome_completo', '-')}
📧 *E-mail:* {dados.get('email', '-')}
📱 *Tel:* {dados.get('telefone', '-')}
🎂 *Nascimento:* {dados.get('data_nascimento', '-')}
🪪 *Driver's License:* {dados.get('driver_license', '-')}
{estado_civil_emoji} *Estado civil:* {dados.get('estado_civil', '-')}
🏠 *Endereço:* {dados.get('endereco', '-')}
🚗 *VIN:* {dados.get('vin', '-')}
🏡 *Imóvel:* {dados.get('imovel_tipo', '-')}

📲 *WPP do lead:* {numero_lead}
━━━━━━━━━━━━━━━━━━━━
✅ Todos os dados coletados. Pronto para cotação!"""


def mensagem_inicial() -> str:
    """Retorna a mensagem de boas-vindas quando um novo lead inicia conversa."""
    return """Olá! 👋 Aqui é a Sofia da *Stay Covered Insurance*!

Vi que você tem interesse em um seguro aqui na Flórida. Que ótimo! 😊

Somos especializados em atender a comunidade brasileira, com atendimento 100% em português.

Para preparar sua cotação gratuita, preciso de algumas informações básicas. Não vai demorar nada, prometo!

Para começar: qual é o seu *nome completo*?"""
