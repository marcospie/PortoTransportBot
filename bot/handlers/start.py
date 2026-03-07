"""Start and help command handlers."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import main_menu_keyboard
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

WELCOME_TEXT = """
🚌🚇 *Porto Transport Bot*

Bem\\-vindo\\! Sou o teu assistente de transportes públicos do Porto\\.

Posso ajudar\\-te a consultar:

🚌 *Autocarros \\(STCP\\)* \\- tempos reais de chegada
🚇 *Metro do Porto* \\- horários e frequências

Escolhe uma opção abaixo ou usa os comandos:

/bus \\- Menu autocarros
/metro \\- Menu metro
/stop \\<código\\> \\- Consulta rápida de paragem
/station \\<nome\\> \\- Consulta rápida de estação
/favorites \\- Os teus favoritos
"""

HELP_TEXT = """
ℹ️ *Ajuda*

*Comandos disponíveis:*

/start \\- Menu principal
/bus \\- Autocarros STCP
/metro \\- Metro do Porto
/stop BCM2 \\- Consultar paragem por código
/station Trindade \\- Consultar estação de metro
/favorites \\- Gerir favoritos
/help \\- Esta mensagem

*Como usar:*

1️⃣ Escolhe entre 🚌 autocarros ou 🚇 metro
2️⃣ Pesquisa por nome ou código da paragem/estação
3️⃣ Vê os tempos de chegada em tempo real
4️⃣ Adiciona aos favoritos para acesso rápido\\!

*Dicas:*
• Podes enviar o nome de uma paragem diretamente
• 📍 Envia a tua localização para ver paragens perto de ti
• Os tempos dos autocarros são em tempo real
• Os tempos do metro são estimados com base nas frequências
• Usa o botão 🔄 para atualizar os dados
"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )


async def main_menu_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        WELCOME_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )


async def help_callback(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        HELP_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )
