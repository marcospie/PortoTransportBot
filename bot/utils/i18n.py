"""Simple internationalization for the bot. Supports PT and EN."""

import asyncio
import logging

from telegram import Update

logger = logging.getLogger(__name__)

TRANSLATIONS = {
    "pt": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "O teu assistente de transportes do Porto\\.\n\n"
            "🚌 *Autocarros* — tempos reais STCP\n"
            "🚇 *Metro* — horários e frequências\n"
            "🗺 *Rotas* — planeia o teu trajeto\n"
            "📍 *Localização* — paragens perto de ti\n\n"
            "Escolhe uma opção ou escreve o nome de uma paragem:"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "👋 Olá de novo\\! Os teus favoritos:\n"
        ),
        "help": (
            "ℹ️ *Ajuda*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🚍 *Transporte*\n"
            "  /bus — Autocarros STCP\n"
            "  /metro — Metro do Porto\n"
            "  /comboios — Comboios CP urbanos\n"
            "  /metrobus — MetroBus BRT\n"
            "  /stop `BCM2` — Paragem por código\n"
            "  /station `Trindade` — Estação de metro\n"
            "  /estacao `Campanhã` — Estação de comboios\n\n"
            "🗺 *Planeamento*\n"
            "  /route — Planear trajeto\n"
            "  /commuter — Rotinas de quem viaja todos os dias\n"
            "  /tourist — Guia turístico do Porto\n"
            "  /zonas — Calcular zonas e preços Andante\n\n"
            "📢 *Informação*\n"
            "  /alertas — Alertas de serviço\n"
            "  /meteo — Meteorologia e transportes\n"
            "  /eventos — Eventos e como chegar\n"
            "  /acessibilidade — Elevadores e acessos\n\n"
            "⭐ *Pessoal*\n"
            "  /favorites — Os teus favoritos\n"
            "  /fav — Favorito rápido\n"
            "  /settings — Configurações e idioma\n"
            "  /start — Menu principal\n"
            "  /help — Esta ajuda\n\n"
            "*Como usar:*\n"
            "1️⃣ Escolhe 🚌 autocarros ou 🚇 metro\n"
            "2️⃣ Pesquisa por nome ou código\n"
            "3️⃣ Consulta os horários em tempo real\n"
            "4️⃣ Adiciona aos ⭐ favoritos\\!\n\n"
            "*Dicas:*\n"
            "• Escreve o nome da paragem diretamente\n"
            "• 📍 Envia a tua localização para ver paragens perto\n"
            "• 🔄 Atualiza os horários a qualquer momento\n"
            "• Usa @nomedobot numa conversa para pesquisa rápida"
        ),
        # Location / Nearby
        "nearby_title": "📍 *Transportes perto de ti* \\(raio {radius}m\\)",
        "nearby_empty": (
            "📍 Não encontrei paragens ou estações num raio de "
            "{radius}m da tua localização\\.\n\n"
            "Tenta pesquisar por nome no menu\\."
        ),
        "metro_stations": "Estações de metro",
        "bus_stops": "Paragens de autocarro",
        # Night service
        "metro_closed": (
            "🌙 *Metro encerrado*\n\n"
            "O metro funciona das 06:00 às 01:00\\.\n\n"
            "🚌 *Alternativas noturnas STCP:*\n"
            "• Linha *1M* \\- Madrugada\n"
            "• Linha *2M* \\- Madrugada\n"
            "• Linha *3M* \\- Madrugada\n\n"
            "Consulta /bus para mais informações\\."
        ),
        # Zone info
        "zone_info": "📍 Zona Andante: *{zone}*",
        # Navigation
        "back_main": "🔙 Menu principal",
        "back": "🔙 Voltar",
        # Keyboard
        "kb_nearby": "📍 Perto de mim",
        "kb_favorites": "⭐ Favoritos",
        "kb_help": "ℹ️ Ajuda",
        # Settings
        "settings_title": (
            "⚙️ *Configurações*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Personaliza o teu bot\\.\n"
            "Toca numa opção para alterar:"
        ),
        "settings_metro_radius": "🚇 Raio metro: {value}m",
        "settings_bus_radius": "🚌 Raio autocarros: {value}m",
        "settings_max_results": "📊 Máx. resultados: {value}",
        "settings_language": "🌐 Idioma: {value}",
        "settings_reset": "🔄 Repor predefinições",
        "settings_pick_metro_radius": "🚇 *Raio de pesquisa \\- Metro*\n\nEscolhe a distância máxima para encontrar estações de metro perto de ti:",
        "settings_pick_bus_radius": "🚌 *Raio de pesquisa \\- Autocarros*\n\nEscolhe a distância máxima para encontrar paragens perto de ti:",
        "settings_pick_max_results": "📊 *Máximo de resultados*\n\nQuantas paragens/estações mostrar na pesquisa por localização:",
        "settings_pick_language": "🌐 *Idioma*\n\nEscolhe o idioma do bot\\.\n_Automático_ usa o idioma do teu Telegram:",
        "settings_saved": "Guardado!",
        "settings_reset_done": "Configurações repostas!",
        # Notifications (opt-in)
        "settings_notifications": "🔔 Notificações: {value}",
        "settings_notifications_on": "Ligadas",
        "settings_notifications_off": "Desligadas",
        "settings_pick_notifications": (
            "🔔 *Notificações*\n\n"
            "Recebe avisos quando houver alertas de serviço nas tuas linhas "
            "e lembretes das tuas viagens habituais\\.\n"
            "Estão desligadas por predefinição:"
        ),
        "notif_alert_title": "🔔 *Alerta de serviço*",
        "notif_commute_reminder": "🔔 *Lembrete de viagem*",
        # Shared UI labels
        "cancel": "❌ Cancelar",
        "back_to_menu": "🔙 Menu",
        "frequencies": "🕐 Frequências",
        "option_not_available": "⌛ Essa opção já não está disponível\\. Faz a pesquisa outra vez\\.",
        # Shared data-availability messages
        "zones_no_station_in_zone": "Nenhuma estação nesta zona",
        "no_alerts_of_type": "ℹ️ Não há alertas deste tipo neste momento\\.",
        "alerts_source_unavailable": (
            "⚠️ Não foi possível verificar alertas agora\\.\n"
            "Tenta novamente dentro de alguns minutos\\."
        ),
        "stcp_data_unavailable": (
            "⚠️ Dados STCP temporariamente indisponíveis\\.\n"
            "Tenta novamente dentro de alguns minutos\\."
        ),
        "data_estimated": "_frequência típica — não é horário real_",
        # Errors
        "error_generic": "❌ Ocorreu um erro\\. Tenta novamente\\.",
        # Bus
        "bus_title": "🚌 *Autocarros STCP*\n\nEscolhe uma opção:",
        "bus_stop_usage": "Uso: /stop \\<código\\>\nExemplo: `/stop BCM2`",
        "bus_find_title": "🔍 *Encontrar paragem*\n\nToca no botão abaixo e começa a escrever \\- as sugestões aparecem enquanto digitas\\!\n\nExemplo: `BIBG` → BIBG1, BIBG2 \\| `Casa` → Casa da Música",
        "bus_find_button": "🔍 Escrever nome ou código...",
        "bus_code_title": "🔢 *Consultar por código*\n\nToca no botão abaixo e escreve o código \\- as sugestões aparecem enquanto digitas\\!\n\nExemplo: `BCM` → BCM1, BCM2 \\| `TRD` → TRD1, TRD2",
        "bus_code_button": "🔍 Escrever código da paragem...",
        "loading": "A carregar...",
        "loading_lines": "A carregar linhas...",
        "loading_location": "A carregar localização...",
        "error_load_lines": "❌ Não foi possível carregar as linhas\\.\n\nO serviço STCP pode estar temporariamente indisponível\\.\nTenta novamente em alguns minutos\\.",
        "retry": "🔄 Tentar novamente",
        "bus_lines_title": "🚌 *Linhas STCP* \\({count} linhas\\)\n\nSeleciona uma linha:",
        "error_load_stop": "❌ Erro ao carregar paragem *{stop_id}*\\. Tenta novamente\\.",
        "error_load_line": "❌ Não foi possível carregar a linha {route}\\.",
        "error_load_line2": "❌ Erro ao carregar a linha {route}\\. Tenta novamente\\.",
        "bus_line_title": "🚌 *Linha {route}*\n",
        "bus_line_stops": "*Paragens \\({count}\\):*\n",
        "bus_line_stops_short": "*{count} paragens*\n",
        "bus_stops_more": "  ⋮ \\.\\.\\.  {count} paragens \\.\\.\\.",
        "bus_routes_serving": "\n🚌 *Linhas que servem esta paragem:*\n",
        "no_stops_found": "❌ Nenhuma paragem encontrada para *{query}*\\.\nTenta outro nome ou usa o código da paragem\\.",
        "results_for": "🔍 Resultados para *{query}*:\n\nSeleciona uma paragem:",
        "select_line": "Seleciona uma linha:",
        "location_unavailable": "❌ Localização não disponível para *{id}*\\.",
        "error_location": "❌ Erro ao obter localização\\. Tenta novamente\\.",
        "stop_not_found": "❌ Paragem *{stop_id}* não encontrada ou sem dados\\.\nVerifica o código e tenta novamente\\.",
        "tip_direct_search": "💡 *Dica:* Podes escrever o nome ou código de qualquer paragem diretamente no chat, sem usar o menu\\!",
        # Metro
        "metro_title": "🚇 *Metro do Porto*\n\nEscolhe uma opção:",
        "metro_station_usage": "Uso: /station \\<nome\\>\nExemplo: `/station Trindade`",
        "metro_search_title": "🔍 *Pesquisar estação*\n\nToca no botão abaixo e começa a escrever \\- as sugestões aparecem enquanto digitas\\!\n\nExemplo: `Trind` → Trindade, `Bol` → Bolhão",
        "metro_search_button": "🔍 Escrever nome da estação...",
        "metro_lines_title": "🗺 *Linhas do Metro do Porto*\n\n{lines}\n\nSeleciona uma linha para mais detalhes:",
        "metro_stations_count": "\\({count} estações\\)\n",
        "metro_line_not_found": "❌ Linha não encontrada\\.",
        "error_load_metro_line": "❌ Erro ao carregar linha\\. Tenta novamente\\.",
        "metro_freq_title": "🕐 *Frequências do Metro*",
        "metro_peak": "🏢 Hora ponta",
        "metro_offpeak": "☀️ Fora de ponta",
        "metro_weekend": "📅 Fim\\-de\\-semana",
        "metro_schedule": "⏰ *Horário de funcionamento:*",
        "metro_peak_hours": "🏢 *Hora ponta \\(7h\\-9h, 17h\\-19h\\):*",
        "metro_estimated_warning": "_⚠️ Tempos estimados com base nas frequências_",
        "metro_scheduled_note": "_📋 Horários programados \\(fonte: GTFS Metro do Porto\\)_",
        "metro_realtime_note": "_🟢 Dados em tempo real \\(fonte: metrodoporto\\.pt\\)_",
        "no_stations_found": "❌ Nenhuma estação encontrada para *{query}*\\.\nTenta outro nome\\.",
        "metro_results_for": "🔍 Resultados para *{query}*:\n\nSeleciona uma estação:",
        "error_load_station": "❌ Erro ao carregar estação *{name}*\\. Tenta novamente\\.",
        "station_not_found": "❌ Estação *{name}* não encontrada\\.",
        # Favorites
        "favs_title": "⭐ *Os teus favoritos*",
        "favs_empty": "Ainda não tens favoritos\\.\nAdiciona paragens ou estações aos favoritos usando o botão ⭐ nas páginas de consulta\\.",
        "favs_count": "⭐ *Os teus favoritos* \\({count}\\)\n\nSeleciona para consultar:",
        "favs_empty_short": "⭐ Ainda não tens favoritos\\.\nPesquisa uma paragem e usa o botão ⭐ para adicionar\\.",
        "fav_add_error": "Erro ao adicionar favorito",
        "fav_already": "Já está nos favoritos! ⭐",
        "fav_added": "Adicionado aos favoritos! ⭐ {name}",
        "fav_remove_error": "Erro ao remover favorito",
        "fav_removed": "Removido dos favoritos ❌",
        # Route
        "route_title": "🗺 *Planear trajeto*",
        "route_ask_origin": "Envia o nome da paragem ou estação de *origem*:\nExemplo: `Bolhão`, `Trindade`, `BCM2`",
        "route_ask_dest": "Agora envia o nome da paragem ou estação de *destino*:",
        "route_origin_label": "📍 Origem: {emoji} *{name}*",
        "route_not_found": "❌ Não encontrei *{query}*\\. Tenta outro nome\\.",
        "route_found": "🗺 *Trajeto encontrado*\n",
        "route_mixed": "🔄 *Trajeto misto \\(autocarro \\+ metro\\)*\n",
        "route_take_metro": "🚇 Apanha o metro em *{name}*",
        "route_take_bus": "🚌 Apanha um autocarro em *{name}*",
        "route_then_bus": "🚌 Depois apanha um autocarro até *{name}*",
        "route_then_metro": "🚇 Depois apanha o metro em *{name}*",
        "route_tip_nearby": "_💡 Consulta as estações de metro perto da tua paragem_",
        "route_no_direct": "❌ Não foi possível encontrar uma rota direta\\.",
        "route_tip_metro": "_💡 Tenta usar locais mais conhecidos ou estações de metro_",
        "route_new": "🔄 Novo trajeto",
        "route_direct": "🎯 _Viagem direta \\- sem transbordos_",
        "route_transfer": "🔄 Transbordo em *{station}*",
        "route_no_direct_bus": "_Sem linha direta entre estas paragens_",
        "route_tip_via_metro": "💡 _Tenta planear via uma estação de metro_",
        "route_option": "*Opção {n}:*",
        # Trip planner
        "trip_title": "🗺 *Planear viagem*",
        "trip_ask_origin": "Envia o nome da paragem ou estação de *origem*:\nExemplo: `Bolhão`, `Trindade`, `Campanhã`\n\nOu envia a tua 📍 localização\\.",
        "trip_ask_dest": "Agora envia o nome da paragem ou estação de *destino*:",
        "trip_origin_set": "📍 Origem: {emoji} *{name}*",
        "trip_searching": "🔍 A procurar rotas\\.\\.\\.",
        "trip_results_title": "🗺 *Viagem planeada*\n",
        "trip_from_to": "📍 De *{origin}* para *{dest}*\n",
        "trip_option_header": "*Opção {n}* — ⏱ {time} min",
        "trip_option_transfers": " \\| 🔄 {transfers} transbordo\\(s\\)",
        "trip_step_walk": "🚶 Andar {min} min até *{to}*",
        "trip_step_walk_from": "🚶 Andar {min} min desde *{from_name}*",
        "trip_step_metro": "🚇 Metro *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_bus": "🚌 Autocarro *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_train": "🚆 Comboio *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_metrobus": "🚍 MetroBus *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_transfer_at": "🔄 Transbordo em *{station}*",
        "trip_zones": "🎫 Zonas: {zones}",
        "trip_no_routes": "❌ Não foram encontradas rotas entre estes locais\\.\n\n💡 _Tenta locais mais conhecidos ou estações de metro\\._",
        "trip_not_found": "❌ Não encontrei *{query}*\\. Tenta outro nome\\.",
        "trip_new": "🔄 Nova viagem",
        "trip_detail": "ℹ️ Detalhes",
        "trip_use_location": "📍 Usar a minha localização",
        "trip_total_time": "⏱ *Tempo total:* {min} min",
        "trip_transfers_count": "🔄 *Transbordos:* {count}",
        "trip_option_btn": "Opção {n} — {time} min",
        # Keyboard labels
        "kb_buses": "🚌 Autocarros",
        "kb_metro": "🚇 Metro",
        "kb_plan_route": "🗺 Planear rota",
        "kb_settings": "⚙️ Config.",
        "kb_quick_search": "🔍 Pesquisa rápida",
        "kb_search_stop": "🔍 Pesquisar paragem",
        "kb_search_by_code": "🔢 Consultar por código",
        "kb_all_lines": "🚌 Ver todas as linhas",
        "kb_cancel": "❌ Cancelar",
        "kb_back": "🔙 Voltar",
        "kb_back_menu": "🔙 Menu",
        "kb_refresh": "🔄 Atualizar",
        "kb_realtime": "🕐 Carregar dados em tempo real",
        "kb_details": "ℹ️ Detalhes",
        "kb_map": "📍 Mapa",
        "kb_favorite": "⭐ Favoritar",
        "kb_unfavorite": "💔 Remover favorito",
        "kb_search_station": "🔍 Pesquisar estação",
        "kb_lines": "🗺 Linhas",
        "kb_frequencies": "🕐 Frequências",
        "kb_find_stop": "🚌 Encontrar paragem",
        "kb_find_station": "🚇 Encontrar estação",
        "kb_nearby": "📍 Paragens perto de mim",
        "kb_previous": "⬅️ Anterior",
        "kb_next": "Seguinte ➡️",
        "kb_freq_detail": "📊 Frequências",
        # MetroBus
        "metrobus_title": "🚍 *MetroBus \\(BRT\\)*\n\nEscolhe uma opção:",
        "metrobus_lines_title": "🗺 *Linhas MetroBus*\n\n{lines}\n\nSeleciona uma linha para mais detalhes:",
        "metrobus_search_title": "🔍 *Pesquisar paragem MetroBus*\n\nToca no botão abaixo e começa a escrever \\- as sugestões aparecem enquanto digitas\\!",
        "metrobus_search_button": "🔍 Escrever nome da paragem...",
        "metrobus_line_not_found": "❌ Linha MetroBus não encontrada\\.",
        "error_load_metrobus_line": "❌ Erro ao carregar linha MetroBus\\. Tenta novamente\\.",
        "metrobus_freq_title": "🕐 *Frequências MetroBus*",
        "metrobus_estimated_warning": "_⚠️ Tempos estimados com base nas frequências_",
        "no_metrobus_stops_found": "❌ Nenhuma paragem MetroBus encontrada para *{query}*\\.\nTenta outro nome\\.",
        "metrobus_results_for": "🔍 Resultados para *{query}*:\n\nSeleciona uma paragem:",
        "error_load_metrobus_stop": "❌ Erro ao carregar paragem MetroBus *{name}*\\. Tenta novamente\\.",
        "metrobus_stop_not_found": "❌ Paragem MetroBus *{name}* não encontrada\\.",
        "metrobus_stops": "Paragens MetroBus",
        "metrobus_closed": (
            "🌙 *MetroBus encerrado*\n\n"
            "O MetroBus funciona das 06:00 às 01:00\\.\n\n"
            "Consulta /bus para alternativas\\."
        ),
        "kb_metrobus": "🚍 MetroBus",
        "kb_search_metrobus_stop": "🔍 Pesquisar paragem",
        # Alerts
        "alerts_title": "\u26a0\ufe0f *Alertas de Servi\u00e7o*",
        "no_alerts": "\u2705 *Sem alertas*\n\nTodos os servi\u00e7os est\u00e3o a funcionar normalmente\\.",
        "alert_severity_high": "Severidade: Alta",
        "alert_severity_medium": "Severidade: M\u00e9dia",
        "alert_severity_low": "Severidade: Baixa",
        "alert_lines": "\U0001f68c Linhas:",
        "kb_alerts": "\u26a0\ufe0f Alertas",
        "kb_alert_all": "\U0001f4cb Todos",
        "kb_alert_delays": "\u23f3 Atrasos",
        "kb_alert_disruptions": "\u26a0\ufe0f Perturba\u00e7\u00f5es",
        "kb_alert_engineering": "\U0001f6a7 Obras",
        # Onboarding
        "onboard_welcome": "\ud83d\udc4b Ol\u00e1\\! Sou o *Porto Transport Bot*\\.\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\nConsulta transportes p\u00fablicos do Porto em tempo real\\.\n\nPara come\u00e7ar, escolhe uma op\u00e7\u00e3o:",
        # Trains (CP)
        "trains_title": "🚆 *Comboios CP*\n\nEscolhe uma opção:",
        "trains_station_usage": "Uso: /estacao \\<nome\\>\nExemplo: `/estacao Campanha`",
        "trains_search_title": "🔍 *Pesquisar estação CP*\n\nToca no botão abaixo e começa a escrever \\- as sugestões aparecem enquanto digitas\\!\n\nExemplo: `Camp` → Campanha, `Erm` → Ermesinde",
        "trains_search_button": "🔍 Escrever nome da estação...",
        "trains_lines_title": "🗺 *Linhas CP \\- Porto*\n\n{lines}\n\nSeleciona uma linha para mais detalhes:",
        "trains_line_not_found": "❌ Linha não encontrada\\.",
        "error_load_train_line": "❌ Erro ao carregar linha\\. Tenta novamente\\.",
        "trains_freq_title": "🕐 *Frequências CP*",
        "trains_estimated_warning": "_⚠️ Tempos estimados com base nas frequências_",
        "no_train_stations_found": "❌ Nenhuma estação encontrada para *{query}*\\.\nTenta outro nome\\.",
        "trains_results_for": "🔍 Resultados para *{query}*:\n\nSeleciona uma estação:",
        "error_load_train_station": "❌ Erro ao carregar estação *{name}*\\. Tenta novamente\\.",
        "train_station_not_found": "❌ Estação *{name}* não encontrada\\.",
        "kb_trains": "🚆 Comboios",
        "kb_search_train_station": "🔍 Pesquisar estação",
        "kb_train_lines": "🗺 Linhas",
        # Tourist
        "tourist_title": (
            "🗺 *Guia Turístico do Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Descobre como chegar aos principais pontos turísticos\\.\n"
            "Escolhe uma categoria:"
        ),
        "tourist_category_title": "{emoji} *{title}*\n━━━━━━━━━━━━━━━━\n\nEscolhe um destino:",
        "tourist_dest_title": "{emoji} *{name}*\n━━━━━━━━━━━━━━━━\n",
        "tourist_best_transport": "🚇 *Melhor transporte:* Metro",
        "tourist_best_transport_bus": "🚌 *Melhor transporte:* Autocarro",
        "tourist_station": "📍 *Estação/Paragem:* {station}",
        "tourist_line": "🔹 *Linha:* {line}",
        "tourist_bus_alt": "🚌 *Alternativa autocarro:* {buses}",
        "tourist_zone": "🎫 *Zona Andante:* {zone}",
        "tourist_walk": "🚶 *A pé:* \\~{min} min da estação",
        "tourist_walk_zero": "🚶 *A pé:* Saída direta",
        "tourist_tip": "💡 *Dica:* {tip}",
        "tourist_no_destinations": "Sem destinos nesta categoria\\.",
        "kb_tourist": "🗺 Guia Turístico",
        "kb_tourist_back_menu": "🔙 Menu turístico",
        "kb_tourist_show_map": "📍 Ver no mapa",
        "kb_tourist_tickets": "🎫 Bilhetes",
        # Events
        "events_today": (
            "🎉 *Eventos Hoje*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "A acontecer agora no Porto:"
        ),
        "events_none_today": (
            "🎉 *Eventos no Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Sem eventos hoje\\. Próximos eventos:"
        ),
        "events_none_upcoming": (
            "🎉 *Eventos no Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Sem eventos programados de momento\\."
        ),
        "events_title": (
            "🎉 *Eventos no Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Descobre eventos no Porto e como chegar de transportes públicos\\.\n"
            "Escolhe uma categoria:"
        ),
        "events_overview": "{emoji} *{title}*\n━━━━━━━━━━━━━━━━\n\nEscolhe um evento:",
        "events_detail": (
            "{emoji} *{name}*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "📍 *Local:* {venue}\n"
            "📅 *Quando:* {date_info}\n"
            "🚇 *Estação mais próxima:* {station}\n"
        ),
        "events_transport_tip": "\n🗺 *Como chegar:*\n{tip}",
        "events_no_events": "Sem eventos nesta categoria\\.",
        "kb_events": "🎉 Eventos",
        "kb_events_football": "⚽ Futebol",
        "kb_events_festival": "🎉 Festivais",
        "kb_events_music": "🎵 Música",
        "kb_events_culture": "🎭 Cultura",
        "kb_events_all": "📋 Todos",
        "kb_events_back_menu": "🔙 Menu eventos",
        "kb_events_more": "📅 Ver mais eventos",
        # Zone Calculator
        "zones_title": (
            "🎫 *Calculador de Zonas Andante*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Calcula as zonas e preço do bilhete entre duas estações\\.\n\n"
            "Escolhe uma opção:"
        ),
        "zones_ask_origin": "📍 Escreve o nome da estação de *origem*:\n\nExemplo: `Trindade`, `Aeroporto`, `Campanhã`",
        "zones_ask_dest": "📍 Agora escreve o nome da estação de *destino*:",
        "zones_origin_set": "📍 Origem: *{name}* \\(zona {zone}\\)",
        "zones_result": (
            "🎫 *Resultado do cálculo*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "📍 *Origem:* {origin} \\({origin_zone}\\)\n"
            "📍 *Destino:* {dest} \\({dest_zone}\\)\n\n"
            "🔢 *Zonas:* {zones_needed}\n"
            "💰 *Bilhete ocasional:* {price}\n"
            "🕐 *Passe diário \\(24h\\):* {day_pass}\n"
        ),
        "zones_tip_same": "💡 *Dica:* Viagem dentro da mesma zona\\! O bilhete mais barato é suficiente\\.",
        "zones_tip_day_pass": "💡 *Dica:* Se fizeres 3\\+ viagens, o passe diário compensa\\!",
        "zones_tip_airport": "💡 *Dica:* Para o aeroporto, precisas de um bilhete Z4\\. Compra na máquina Andante no aeroporto\\.",
        # Price mirrors bot.services.fares.ANDANTE_TOUR_3_PRICE, which is the
        # authority; format from there rather than editing this literal.
        "zones_tip_tour": "💡 *Dica:* Para turistas, o Andante Tour \\(3 dias, 16\\.55€\\) cobre todas as zonas\\!",
        "zones_not_found": "❌ Estação *{name}* não encontrada\\. Tenta outro nome\\.",
        "zones_map_title": (
            "🗺 *Mapa de Zonas Andante*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Seleciona uma zona para ver as estações:"
        ),
        "zones_zone_detail": "📍 *{zone}* — Estações:\n\n{stations}",
        "zones_quick_usage": "Uso rápido: `/zonas Trindade Aeroporto`",
        "kb_zones": "🎫 Zonas",
        "kb_zones_calculate": "🔢 Calcular zonas",
        "kb_zones_map": "🗺 Mapa de zonas",
        "kb_zones_new_calc": "🔄 Novo cálculo",
        "kb_zones_day_pass": "🕐 Passe diário",
        "kb_zones_back": "🔙 Menu zonas",
        # No results
        "no_results": "🤔 Não encontrei resultados para *{query}*\\.\n\nTenta pesquisar por:\n• Nome de uma paragem STCP\n• Código de paragem \\(ex: BCM2\\)\n• Nome de estação de metro\n\nOu usa o menu abaixo:",
        # Commuter
        "commuter_title": (
            "🧑‍💼 *Perfil Commuter*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Configura o teu trajeto diário para acesso rápido\\."
        ),
        "commuter_no_profile": "Ainda não tens um perfil commuter\\.\nConfigura para acesso rápido ao teu trajeto diário\\!",
        "commuter_profile_summary": (
            "🏠 *Casa:* {home}\n"
            "🏢 *Trabalho:* {work}\n"
            "🚌 *Modo:* {mode}\n"
            "⏰ *Ida:* {departure} \\| *Volta:* {return_time}"
        ),
        "commuter_ask_home": "🏠 *Onde moras\\?*\n\nEnvia o nome da paragem ou estação mais perto de casa:",
        "commuter_ask_work": "🏢 *Onde trabalhas\\?*\n\nEnvia o nome da paragem ou estação mais perto do trabalho:",
        "commuter_ask_mode": "🚌 *Modo de transporte preferido\\?*\n\nEscolhe o teu meio de transporte habitual:",
        "commuter_ask_departure": "⏰ *Hora de ida\\?*\n\nA que horas costumas sair de casa de manhã\\?\n\nEnvia no formato HH:MM \\(ex: 08:30\\):",
        "commuter_ask_return": "⏰ *Hora de volta\\?*\n\nA que horas costumas sair do trabalho\\?\n\nEnvia no formato HH:MM \\(ex: 18:00\\):",
        "commuter_confirm": (
            "✅ *Perfil configurado\\!*\n\n"
            "🏠 Casa: *{home}*\n"
            "🏢 Trabalho: *{work}*\n"
            "🚌 Modo: *{mode}*\n"
            "⏰ Ida: *{departure}* \\| Volta: *{return_time}*\n\n"
            "Usa as ações rápidas abaixo\\!"
        ),
        "commuter_deleted": "🗑 Perfil commuter apagado\\.",
        "commuter_location_not_found": "❌ Não encontrei *{query}*\\. Tenta outro nome\\.",
        "commuter_invalid_time": "❌ Formato inválido\\. Envia no formato HH:MM \\(ex: 08:30\\)\\.",
        "commuter_go_work": "🏠→🏢 Ir para o trabalho",
        "commuter_go_home": "🏢→🏠 Ir para casa",
        "commuter_my_times": "⏰ Os meus horários",
        "commuter_edit": "✏️ Editar perfil",
        "commuter_delete": "🗑 Apagar perfil",
        "commuter_setup": "🆕 Configurar perfil",
        "commuter_route_to_work": (
            "🏠→🏢 *A caminho do trabalho*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "De *{home}* para *{work}*\n"
            "Modo: {mode}"
        ),
        "commuter_route_to_home": (
            "🏢→🏠 *A caminho de casa*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "De *{work}* para *{home}*\n"
            "Modo: {mode}"
        ),
        "commuter_my_times_msg": (
            "⏰ *Os meus horários*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🏠→🏢 Saída de manhã: *{departure}*\n"
            "🏢→🏠 Saída à tarde: *{return_time}*\n\n"
            "🏠 Casa: *{home}*\n"
            "🏢 Trabalho: *{work}*"
        ),
        "commuter_mode_metro": "🚇 Metro",
        "commuter_mode_bus": "🚌 Autocarro",
        "commuter_mode_any": "🔄 Qualquer",
        "kb_commuter": "🧑‍💼 Commuter",
        # Accessibility
        "accessibility_title": (
            "♿ *Acessibilidade \\- Metro do Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Informação sobre acessibilidade nas estações de metro\\.\n\n"
            "Todas as estações do Metro do Porto dispõem de elevadores, "
            "rampas, piso tátil, anúncios sonoros e máquinas acessíveis\\.\n\n"
            "Escolhe uma opção:"
        ),
        "accessibility_overview": (
            "♿ *Resumo de Acessibilidade*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "✅ *{total}* estações totalmente acessíveis\n"
            "🔧 *{maintenance}* elevadores em manutenção\n\n"
            "Todas as estações têm:\n"
            "• 🛗 Elevador\n"
            "• ♿ Rampa de acesso\n"
            "• 🦯 Piso tátil\n"
            "• 🔊 Anúncios sonoros\n"
            "• 🎫 Máquinas acessíveis\n"
            "• 🦽 Espaços para cadeira de rodas"
        ),
        "accessibility_station_info": (
            "♿ *{station}*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "{elevator}\n"
            "{ramp}\n"
            "{tactile}\n"
            "{audio}\n"
            "{machines}\n"
            "{wheelchair}\n"
        ),
        "accessibility_elevator": "🛗 Elevador: {status}",
        "accessibility_ramp": "♿ Rampa: {status}",
        "accessibility_tactile": "🦯 Piso tátil: {status}",
        "accessibility_audio": "🔊 Anúncios sonoros: {status}",
        "accessibility_machines": "🎫 Máquinas acessíveis: {status}",
        "accessibility_wheelchair": "🦽 Espaços cadeira de rodas: {status}",
        "accessibility_notes": "📝 *Notas:* {notes}",
        "accessibility_search_prompt": "🔍 Escreve o nome da estação de metro:",
        "accessibility_not_found": "❌ Estação *{name}* não encontrada\\. Tenta outro nome\\.",
        "accessibility_status_ok": "✅ Operacional",
        "accessibility_status_maintenance": "🔧 Em manutenção",
        "accessibility_status_out": "❌ Fora de serviço",
        "kb_accessibility": "♿ Acessibilidade",
        "kb_accessibility_search": "🔍 Pesquisar estação",
        "kb_accessibility_elevators": "🛗 Estado dos elevadores",
        # Weather
        "weather_title": "Meteorologia Porto",
        "weather_temp": "Temperatura",
        "weather_rain": "Probabilidade de chuva",
        "weather_sunrise": "Nascer do sol",
        "weather_sunset": "Pôr do sol",
        "weather_tip": "Dica de transporte",
        "weather_tip_rain": "Chuva provável \\- prefira o metro",
        "weather_tip_nice": "Bom tempo \\- agradável para caminhar",
        "weather_tip_hot": "Calor \\- prefira transportes com ar condicionado",
        "weather_tip_cold": "Frio \\- abrigue\\-se nas estações",
        "weather_disclaimer": "Fonte: Open\\-Meteo\\.com \\(tempo real\\)",
        "kb_weather": "🌤 Meteo",
    },
    "en": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Your Porto public transport assistant\\.\n\n"
            "🚌 *Buses* — real\\-time STCP arrivals\n"
            "🚇 *Metro* — schedules and frequencies\n"
            "🗺 *Routes* — plan your trip\n"
            "📍 *Location* — nearby stops\n\n"
            "Pick an option or type a stop name:"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "👋 Welcome back\\! Your favorites:\n"
        ),
        "help": (
            "ℹ️ *Help*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🚍 *Transport*\n"
            "  /bus — STCP buses\n"
            "  /metro — Porto Metro\n"
            "  /comboios — CP suburban trains\n"
            "  /metrobus — MetroBus BRT\n"
            "  /stop `BCM2` — Bus stop by code\n"
            "  /station `Trindade` — Metro station\n"
            "  /estacao `Campanhã` — Train station\n\n"
            "🗺 *Planning*\n"
            "  /route — Plan a route\n"
            "  /commuter — Daily commute routines\n"
            "  /tourist — Porto tourist guide\n"
            "  /zonas — Andante zones and fares\n\n"
            "📢 *Information*\n"
            "  /alertas — Service alerts\n"
            "  /meteo — Weather and transport\n"
            "  /eventos — Events and how to get there\n"
            "  /acessibilidade — Lifts and step\\-free access\n\n"
            "⭐ *Personal*\n"
            "  /favorites — Your favorites\n"
            "  /fav — Quick favorite\n"
            "  /settings — Settings and language\n"
            "  /start — Main menu\n"
            "  /help — This help\n\n"
            "*How to use:*\n"
            "1️⃣ Choose 🚌 buses or 🚇 metro\n"
            "2️⃣ Search by name or stop code\n"
            "3️⃣ See real\\-time arrivals\n"
            "4️⃣ Add to ⭐ favorites\\!\n\n"
            "*Tips:*\n"
            "• Type a stop name directly\n"
            "• 📍 Send your location for nearby stops\n"
            "• 🔄 Refresh times anytime\n"
            "• Use @botname in any chat for inline search"
        ),
        # Location / Nearby
        "nearby_title": "📍 *Transport near you* \\(radius {radius}m\\)",
        "nearby_empty": (
            "📍 No stops or stations found within "
            "{radius}m of your location\\.\n\n"
            "Try searching by name in the menu\\."
        ),
        "metro_stations": "Metro stations",
        "bus_stops": "Bus stops",
        # Night service
        "metro_closed": (
            "🌙 *Metro closed*\n\n"
            "Metro operates from 06:00 to 01:00\\.\n\n"
            "🚌 *Night bus alternatives \\(STCP\\):*\n"
            "• Line *1M* \\- Madrugada\n"
            "• Line *2M* \\- Madrugada\n"
            "• Line *3M* \\- Madrugada\n\n"
            "Check /bus for more information\\."
        ),
        # Zone info
        "zone_info": "📍 Andante Zone: *{zone}*",
        # Navigation
        "back_main": "🔙 Main menu",
        "back": "🔙 Back",
        # Keyboard
        "kb_nearby": "📍 Near me",
        "kb_favorites": "⭐ Favorites",
        "kb_help": "ℹ️ Help",
        # Settings
        "settings_title": (
            "⚙️ *Settings*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Customise your bot\\.\n"
            "Tap an option to change:"
        ),
        "settings_metro_radius": "🚇 Metro radius: {value}m",
        "settings_bus_radius": "🚌 Bus radius: {value}m",
        "settings_max_results": "📊 Max results: {value}",
        "settings_language": "🌐 Language: {value}",
        "settings_reset": "🔄 Reset defaults",
        "settings_pick_metro_radius": "🚇 *Search radius \\- Metro*\n\nChoose the max distance to find metro stations near you:",
        "settings_pick_bus_radius": "🚌 *Search radius \\- Buses*\n\nChoose the max distance to find bus stops near you:",
        "settings_pick_max_results": "📊 *Maximum results*\n\nHow many stops/stations to show in location search:",
        "settings_pick_language": "🌐 *Language*\n\nChoose the bot language\\.\n_Auto_ uses your Telegram language:",
        "settings_saved": "Saved!",
        "settings_reset_done": "Settings reset!",
        # Notifications (opt-in)
        "settings_notifications": "🔔 Notifications: {value}",
        "settings_notifications_on": "On",
        "settings_notifications_off": "Off",
        "settings_pick_notifications": (
            "🔔 *Notifications*\n\n"
            "Get a heads\\-up when there are service alerts on your lines "
            "and reminders for your usual trips\\.\n"
            "They are off by default:"
        ),
        "notif_alert_title": "🔔 *Service alert*",
        "notif_commute_reminder": "🔔 *Commute reminder*",
        # Shared UI labels
        "cancel": "❌ Cancel",
        "back_to_menu": "🔙 Menu",
        "frequencies": "🕐 Frequencies",
        "option_not_available": "⌛ That option is no longer available\\. Please search again\\.",
        # Shared data-availability messages
        "zones_no_station_in_zone": "No station in this zone",
        "no_alerts_of_type": "ℹ️ There are no alerts of this type right now\\.",
        "alerts_source_unavailable": (
            "⚠️ Could not check alerts right now\\.\n"
            "Please try again in a few minutes\\."
        ),
        "stcp_data_unavailable": (
            "⚠️ STCP data temporarily unavailable\\.\n"
            "Please try again in a few minutes\\."
        ),
        "data_estimated": "_typical frequency — not a real timetable_",
        # Errors
        "error_generic": "❌ An error occurred\\. Please try again\\.",
        # Bus
        "bus_title": "🚌 *STCP Buses*\n\nChoose an option:",
        "bus_stop_usage": "Usage: /stop \\<code\\>\nExample: `/stop BCM2`",
        "bus_find_title": "🔍 *Find stop*\n\nTap the button below and start typing \\- suggestions appear as you type\\!\n\nExample: `BIBG` → BIBG1, BIBG2 \\| `Casa` → Casa da Música",
        "bus_find_button": "🔍 Type name or code...",
        "bus_code_title": "🔢 *Look up by code*\n\nTap the button below and type the code \\- suggestions appear as you type\\!\n\nExample: `BCM` → BCM1, BCM2 \\| `TRD` → TRD1, TRD2",
        "bus_code_button": "🔍 Type stop code...",
        "loading": "Loading...",
        "loading_lines": "Loading lines...",
        "loading_location": "Loading location...",
        "error_load_lines": "❌ Could not load lines\\.\n\nThe STCP service may be temporarily unavailable\\.\nTry again in a few minutes\\.",
        "retry": "🔄 Try again",
        "bus_lines_title": "🚌 *STCP Lines* \\({count} lines\\)\n\nSelect a line:",
        "error_load_stop": "❌ Error loading stop *{stop_id}*\\. Try again\\.",
        "error_load_line": "❌ Could not load line {route}\\.",
        "error_load_line2": "❌ Error loading line {route}\\. Try again\\.",
        "bus_line_title": "🚌 *Line {route}*\n",
        "bus_line_stops": "*Stops \\({count}\\):*\n",
        "bus_line_stops_short": "*{count} stops*\n",
        "bus_stops_more": "  ⋮ \\.\\.\\.  {count} stops \\.\\.\\.",
        "bus_routes_serving": "\n🚌 *Lines serving this stop:*\n",
        "no_stops_found": "❌ No stops found for *{query}*\\.\nTry another name or use the stop code\\.",
        "results_for": "🔍 Results for *{query}*:\n\nSelect a stop:",
        "select_line": "Select a line:",
        "location_unavailable": "❌ Location not available for *{id}*\\.",
        "error_location": "❌ Error getting location\\. Try again\\.",
        "stop_not_found": "❌ Stop *{stop_id}* not found or has no data\\.\nCheck the code and try again\\.",
        "tip_direct_search": "💡 *Tip:* You can type any stop name or code directly in the chat, without using the menu\\!",
        # Metro
        "metro_title": "🚇 *Porto Metro*\n\nChoose an option:",
        "metro_station_usage": "Usage: /station \\<name\\>\nExample: `/station Trindade`",
        "metro_search_title": "🔍 *Search station*\n\nTap the button below and start typing \\- suggestions appear as you type\\!\n\nExample: `Trind` → Trindade, `Bol` → Bolhão",
        "metro_search_button": "🔍 Type station name...",
        "metro_lines_title": "🗺 *Porto Metro Lines*\n\n{lines}\n\nSelect a line for more details:",
        "metro_stations_count": "\\({count} stations\\)\n",
        "metro_line_not_found": "❌ Line not found\\.",
        "error_load_metro_line": "❌ Error loading line\\. Try again\\.",
        "metro_freq_title": "🕐 *Metro Frequencies*",
        "metro_peak": "🏢 Peak hours",
        "metro_offpeak": "☀️ Off\\-peak",
        "metro_weekend": "📅 Weekend",
        "metro_schedule": "⏰ *Operating hours:*",
        "metro_peak_hours": "🏢 *Peak hours \\(7am\\-9am, 5pm\\-7pm\\):*",
        "metro_estimated_warning": "_⚠️ Estimated times based on frequencies_",
        "metro_scheduled_note": "_📋 Scheduled times \\(source: GTFS Metro do Porto\\)_",
        "metro_realtime_note": "_🟢 Real\\-time data \\(source: metrodoporto\\.pt\\)_",
        "no_stations_found": "❌ No stations found for *{query}*\\.\nTry another name\\.",
        "metro_results_for": "🔍 Results for *{query}*:\n\nSelect a station:",
        "error_load_station": "❌ Error loading station *{name}*\\. Try again\\.",
        "station_not_found": "❌ Station *{name}* not found\\.",
        # Favorites
        "favs_title": "⭐ *Your favorites*",
        "favs_empty": "You have no favorites yet\\.\nAdd stops or stations to favorites using the ⭐ button on lookup pages\\.",
        "favs_count": "⭐ *Your favorites* \\({count}\\)\n\nSelect to look up:",
        "favs_empty_short": "⭐ You have no favorites yet\\.\nSearch for a stop and use the ⭐ button to add\\.",
        "fav_add_error": "Error adding favorite",
        "fav_already": "Already in favorites! ⭐",
        "fav_added": "Added to favorites! ⭐ {name}",
        "fav_remove_error": "Error removing favorite",
        "fav_removed": "Removed from favorites ❌",
        # Route
        "route_title": "🗺 *Plan route*",
        "route_ask_origin": "Send the name of the *origin* stop or station:\nExample: `Bolhão`, `Trindade`, `BCM2`",
        "route_ask_dest": "Now send the name of the *destination* stop or station:",
        "route_origin_label": "📍 Origin: {emoji} *{name}*",
        "route_not_found": "❌ Could not find *{query}*\\. Try another name\\.",
        "route_found": "🗺 *Route found*\n",
        "route_mixed": "🔄 *Mixed route \\(bus \\+ metro\\)*\n",
        "route_take_metro": "🚇 Take the metro at *{name}*",
        "route_take_bus": "🚌 Take a bus at *{name}*",
        "route_then_bus": "🚌 Then take a bus to *{name}*",
        "route_then_metro": "🚇 Then take the metro at *{name}*",
        "route_tip_nearby": "_💡 Check metro stations near your stop_",
        "route_no_direct": "❌ Could not find a direct route\\.",
        "route_tip_metro": "_💡 Try using well\\-known locations or metro stations_",
        "route_new": "🔄 New route",
        "route_direct": "🎯 _Direct trip \\- no transfers_",
        "route_transfer": "🔄 Transfer at *{station}*",
        "route_no_direct_bus": "_No direct line between these stops_",
        "route_tip_via_metro": "💡 _Try planning via a metro station_",
        "route_option": "*Option {n}:*",
        # Trip planner
        "trip_title": "🗺 *Plan trip*",
        "trip_ask_origin": "Send the name of the *origin* stop or station:\nExample: `Bolhão`, `Trindade`, `Campanhã`\n\nOr send your 📍 location\\.",
        "trip_ask_dest": "Now send the name of the *destination* stop or station:",
        "trip_origin_set": "📍 Origin: {emoji} *{name}*",
        "trip_searching": "🔍 Searching for routes\\.\\.\\.",
        "trip_results_title": "🗺 *Trip planned*\n",
        "trip_from_to": "📍 From *{origin}* to *{dest}*\n",
        "trip_option_header": "*Option {n}* — ⏱ {time} min",
        "trip_option_transfers": " \\| 🔄 {transfers} transfer\\(s\\)",
        "trip_step_walk": "🚶 Walk {min} min to *{to}*",
        "trip_step_walk_from": "🚶 Walk {min} min from *{from_name}*",
        "trip_step_metro": "🚇 Metro *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_bus": "🚌 Bus *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_train": "🚆 Train *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_step_metrobus": "🚍 MetroBus *{line}* — *{from}* → *{to}* \\({min} min\\)",
        "trip_transfer_at": "🔄 Transfer at *{station}*",
        "trip_zones": "🎫 Zones: {zones}",
        "trip_no_routes": "❌ No routes found between these locations\\.\n\n💡 _Try well\\-known locations or metro stations\\._",
        "trip_not_found": "❌ Could not find *{query}*\\. Try another name\\.",
        "trip_new": "🔄 New trip",
        "trip_detail": "ℹ️ Details",
        "trip_use_location": "📍 Use my location",
        "trip_total_time": "⏱ *Total time:* {min} min",
        "trip_transfers_count": "🔄 *Transfers:* {count}",
        "trip_option_btn": "Option {n} — {time} min",
        # Keyboard labels
        "kb_buses": "🚌 Buses",
        "kb_metro": "🚇 Metro",
        "kb_plan_route": "🗺 Plan route",
        "kb_settings": "⚙️ Settings",
        "kb_quick_search": "🔍 Quick search",
        "kb_search_stop": "🔍 Search stop",
        "kb_search_by_code": "🔢 Look up by code",
        "kb_all_lines": "🚌 All lines",
        "kb_cancel": "❌ Cancel",
        "kb_back": "🔙 Back",
        "kb_back_menu": "🔙 Menu",
        "kb_refresh": "🔄 Refresh",
        "kb_realtime": "🕐 Load real-time data",
        "kb_details": "ℹ️ Details",
        "kb_map": "📍 Map",
        "kb_favorite": "⭐ Favorite",
        "kb_unfavorite": "💔 Remove favorite",
        "kb_search_station": "🔍 Search station",
        "kb_lines": "🗺 Lines",
        "kb_frequencies": "🕐 Frequencies",
        "kb_find_stop": "🚌 Find stop",
        "kb_find_station": "🚇 Find station",
        "kb_nearby": "📍 Stops near me",
        "kb_previous": "⬅️ Previous",
        "kb_next": "Next ➡️",
        "kb_freq_detail": "📊 Frequencies",
        # MetroBus
        "metrobus_title": "🚍 *MetroBus \\(BRT\\)*\n\nChoose an option:",
        "metrobus_lines_title": "🗺 *MetroBus Lines*\n\n{lines}\n\nSelect a line for more details:",
        "metrobus_search_title": "🔍 *Search MetroBus stop*\n\nTap the button below and start typing \\- suggestions appear as you type\\!",
        "metrobus_search_button": "🔍 Type stop name...",
        "metrobus_line_not_found": "❌ MetroBus line not found\\.",
        "error_load_metrobus_line": "❌ Error loading MetroBus line\\. Try again\\.",
        "metrobus_freq_title": "🕐 *MetroBus Frequencies*",
        "metrobus_estimated_warning": "_⚠️ Estimated times based on frequencies_",
        "no_metrobus_stops_found": "❌ No MetroBus stops found for *{query}*\\.\nTry another name\\.",
        "metrobus_results_for": "🔍 Results for *{query}*:\n\nSelect a stop:",
        "error_load_metrobus_stop": "❌ Error loading MetroBus stop *{name}*\\. Try again\\.",
        "metrobus_stop_not_found": "❌ MetroBus stop *{name}* not found\\.",
        "metrobus_stops": "MetroBus stops",
        "metrobus_closed": (
            "🌙 *MetroBus closed*\n\n"
            "MetroBus operates from 06:00 to 01:00\\.\n\n"
            "Check /bus for alternatives\\."
        ),
        "kb_metrobus": "🚍 MetroBus",
        "kb_search_metrobus_stop": "🔍 Search stop",
        # Alerts
        "alerts_title": "\u26a0\ufe0f *Service Alerts*",
        "no_alerts": "\u2705 *No alerts*\n\nAll services are running normally\\.",
        "alert_severity_high": "Severity: High",
        "alert_severity_medium": "Severity: Medium",
        "alert_severity_low": "Severity: Low",
        "alert_lines": "\U0001f68c Lines:",
        "kb_alerts": "\u26a0\ufe0f Alerts",
        "kb_alert_all": "\U0001f4cb All",
        "kb_alert_delays": "\u23f3 Delays",
        "kb_alert_disruptions": "\u26a0\ufe0f Disruptions",
        "kb_alert_engineering": "\U0001f6a7 Engineering",
        # Onboarding
        "onboard_welcome": "\ud83d\udc4b Hello\\! I'm the *Porto Transport Bot*\\.\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\nLook up Porto public transport in real time\\.\n\nTo get started, choose an option:",
        # Trains (CP)
        "trains_title": "🚆 *CP Trains*\n\nChoose an option:",
        "trains_station_usage": "Usage: /estacao \\<name\\>\nExample: `/estacao Campanha`",
        "trains_search_title": "🔍 *Search CP station*\n\nTap the button below and start typing \\- suggestions appear as you type\\!\n\nExample: `Camp` → Campanha, `Erm` → Ermesinde",
        "trains_search_button": "🔍 Type station name...",
        "trains_lines_title": "🗺 *CP Lines \\- Porto*\n\n{lines}\n\nSelect a line for more details:",
        "trains_line_not_found": "❌ Line not found\\.",
        "error_load_train_line": "❌ Error loading line\\. Try again\\.",
        "trains_freq_title": "🕐 *CP Frequencies*",
        "trains_estimated_warning": "_⚠️ Estimated times based on frequencies_",
        "no_train_stations_found": "❌ No stations found for *{query}*\\.\nTry another name\\.",
        "trains_results_for": "🔍 Results for *{query}*:\n\nSelect a station:",
        "error_load_train_station": "❌ Error loading station *{name}*\\. Try again\\.",
        "train_station_not_found": "❌ Station *{name}* not found\\.",
        "kb_trains": "🚆 Trains",
        "kb_search_train_station": "🔍 Search station",
        "kb_train_lines": "🗺 Lines",
        # Tourist
        "tourist_title": (
            "🗺 *Porto Tourist Guide*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Discover how to reach Porto's main attractions\\.\n"
            "Choose a category:"
        ),
        "tourist_category_title": "{emoji} *{title}*\n━━━━━━━━━━━━━━━━\n\nChoose a destination:",
        "tourist_dest_title": "{emoji} *{name}*\n━━━━━━━━━━━━━━━━\n",
        "tourist_best_transport": "🚇 *Best transport:* Metro",
        "tourist_best_transport_bus": "🚌 *Best transport:* Bus",
        "tourist_station": "📍 *Station/Stop:* {station}",
        "tourist_line": "🔹 *Line:* {line}",
        "tourist_bus_alt": "🚌 *Bus alternative:* {buses}",
        "tourist_zone": "🎫 *Andante Zone:* {zone}",
        "tourist_walk": "🚶 *Walk:* \\~{min} min from station",
        "tourist_walk_zero": "🚶 *Walk:* Direct exit",
        "tourist_tip": "💡 *Tip:* {tip}",
        "tourist_no_destinations": "No destinations in this category\\.",
        "kb_tourist": "🗺 Tourist Guide",
        "kb_tourist_back_menu": "🔙 Tourist menu",
        "kb_tourist_show_map": "📍 Show on map",
        "kb_tourist_tickets": "🎫 Tickets",
        # Events
        "events_today": (
            "🎉 *Events Today*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Happening now in Porto:"
        ),
        "events_none_today": (
            "🎉 *Events in Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "No events today\\. Coming up next:"
        ),
        "events_none_upcoming": (
            "🎉 *Events in Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "No events scheduled at the moment\\."
        ),
        "events_title": (
            "🎉 *Events in Porto*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Discover events in Porto and how to get there by public transport\\.\n"
            "Choose a category:"
        ),
        "events_overview": "{emoji} *{title}*\n━━━━━━━━━━━━━━━━\n\nChoose an event:",
        "events_detail": (
            "{emoji} *{name}*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "📍 *Venue:* {venue}\n"
            "📅 *When:* {date_info}\n"
            "🚇 *Nearest station:* {station}\n"
        ),
        "events_transport_tip": "\n🗺 *How to get there:*\n{tip}",
        "events_no_events": "No events in this category\\.",
        "kb_events": "🎉 Events",
        "kb_events_football": "⚽ Football",
        "kb_events_festival": "🎉 Festivals",
        "kb_events_music": "🎵 Music",
        "kb_events_culture": "🎭 Culture",
        "kb_events_all": "📋 All",
        "kb_events_back_menu": "🔙 Events menu",
        "kb_events_more": "📅 More events",
        # Zone Calculator
        "zones_title": (
            "🎫 *Andante Zone Calculator*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Calculate zones and ticket price between two stations\\.\n\n"
            "Choose an option:"
        ),
        "zones_ask_origin": "📍 Type the name of the *origin* station:\n\nExample: `Trindade`, `Aeroporto`, `Campanhã`",
        "zones_ask_dest": "📍 Now type the name of the *destination* station:",
        "zones_origin_set": "📍 Origin: *{name}* \\(zone {zone}\\)",
        "zones_result": (
            "🎫 *Calculation Result*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "📍 *Origin:* {origin} \\({origin_zone}\\)\n"
            "📍 *Destination:* {dest} \\({dest_zone}\\)\n\n"
            "🔢 *Zones:* {zones_needed}\n"
            "💰 *Single ticket:* {price}\n"
            "🕐 *Day pass \\(24h\\):* {day_pass}\n"
        ),
        "zones_tip_same": "💡 *Tip:* Travel within the same zone\\! The cheapest ticket is enough\\.",
        "zones_tip_day_pass": "💡 *Tip:* If you make 3\\+ trips, the day pass is worth it\\!",
        "zones_tip_airport": "💡 *Tip:* For the airport, you need a Z4 ticket\\. Buy it at the Andante machine at the airport\\.",
        "zones_tip_tour": "💡 *Tip:* For tourists, the Andante Tour \\(3 days, 16\\.55€\\) covers all zones\\!",
        "zones_not_found": "❌ Station *{name}* not found\\. Try another name\\.",
        "zones_map_title": (
            "🗺 *Andante Zone Map*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Select a zone to see stations:"
        ),
        "zones_zone_detail": "📍 *{zone}* — Stations:\n\n{stations}",
        "zones_quick_usage": "Quick usage: `/zonas Trindade Aeroporto`",
        "kb_zones": "🎫 Zones",
        "kb_zones_calculate": "🔢 Calculate zones",
        "kb_zones_map": "🗺 Zone map",
        "kb_zones_new_calc": "🔄 New calculation",
        "kb_zones_day_pass": "🕐 Day pass",
        "kb_zones_back": "🔙 Zone menu",
        # No results
        "no_results": "🤔 No results found for *{query}*\\.\n\nTry searching for:\n• An STCP bus stop name\n• A stop code \\(e\\.g\\. BCM2\\)\n• A metro station name\n\nOr use the menu below:",
        # Commuter
        "commuter_title": (
            "🧑‍💼 *Commuter Profile*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Set up your daily commute for quick access\\."
        ),
        "commuter_no_profile": "You don't have a commuter profile yet\\.\nSet one up for quick access to your daily route\\!",
        "commuter_profile_summary": (
            "🏠 *Home:* {home}\n"
            "🏢 *Work:* {work}\n"
            "🚌 *Mode:* {mode}\n"
            "⏰ *Departure:* {departure} \\| *Return:* {return_time}"
        ),
        "commuter_ask_home": "🏠 *Where do you live\\?*\n\nSend the name of the stop or station nearest to home:",
        "commuter_ask_work": "🏢 *Where do you work\\?*\n\nSend the name of the stop or station nearest to work:",
        "commuter_ask_mode": "🚌 *Preferred transport mode\\?*\n\nChoose your usual means of transport:",
        "commuter_ask_departure": "⏰ *Departure time\\?*\n\nWhat time do you usually leave home in the morning\\?\n\nSend in HH:MM format \\(e\\.g\\. 08:30\\):",
        "commuter_ask_return": "⏰ *Return time\\?*\n\nWhat time do you usually leave work\\?\n\nSend in HH:MM format \\(e\\.g\\. 18:00\\):",
        "commuter_confirm": (
            "✅ *Profile set up\\!*\n\n"
            "🏠 Home: *{home}*\n"
            "🏢 Work: *{work}*\n"
            "🚌 Mode: *{mode}*\n"
            "⏰ Departure: *{departure}* \\| Return: *{return_time}*\n\n"
            "Use the quick actions below\\!"
        ),
        "commuter_deleted": "🗑 Commuter profile deleted\\.",
        "commuter_location_not_found": "❌ Could not find *{query}*\\. Try another name\\.",
        "commuter_invalid_time": "❌ Invalid format\\. Send in HH:MM format \\(e\\.g\\. 08:30\\)\\.",
        "commuter_go_work": "🏠→🏢 Go to work",
        "commuter_go_home": "🏢→🏠 Go home",
        "commuter_my_times": "⏰ My times",
        "commuter_edit": "✏️ Edit profile",
        "commuter_delete": "🗑 Delete profile",
        "commuter_setup": "🆕 Set up profile",
        "commuter_route_to_work": (
            "🏠→🏢 *Going to work*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "From *{home}* to *{work}*\n"
            "Mode: {mode}"
        ),
        "commuter_route_to_home": (
            "🏢→🏠 *Going home*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "From *{work}* to *{home}*\n"
            "Mode: {mode}"
        ),
        "commuter_my_times_msg": (
            "⏰ *My times*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "🏠→🏢 Morning departure: *{departure}*\n"
            "🏢→🏠 Evening departure: *{return_time}*\n\n"
            "🏠 Home: *{home}*\n"
            "🏢 Work: *{work}*"
        ),
        "commuter_mode_metro": "🚇 Metro",
        "commuter_mode_bus": "🚌 Bus",
        "commuter_mode_any": "🔄 Any",
        "kb_commuter": "🧑‍💼 Commuter",
        # Accessibility
        "accessibility_title": (
            "♿ *Accessibility \\- Porto Metro*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Accessibility information for metro stations\\.\n\n"
            "All Porto Metro stations have elevators, "
            "ramps, tactile guidance, audio announcements and accessible machines\\.\n\n"
            "Choose an option:"
        ),
        "accessibility_overview": (
            "♿ *Accessibility Overview*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "✅ *{total}* fully accessible stations\n"
            "🔧 *{maintenance}* elevators under maintenance\n\n"
            "All stations have:\n"
            "• 🛗 Elevator\n"
            "• ♿ Wheelchair ramp\n"
            "• 🦯 Tactile guidance\n"
            "• 🔊 Audio announcements\n"
            "• 🎫 Accessible ticket machines\n"
            "• 🦽 Wheelchair spaces"
        ),
        "accessibility_station_info": (
            "♿ *{station}*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "{elevator}\n"
            "{ramp}\n"
            "{tactile}\n"
            "{audio}\n"
            "{machines}\n"
            "{wheelchair}\n"
        ),
        "accessibility_elevator": "🛗 Elevator: {status}",
        "accessibility_ramp": "♿ Ramp: {status}",
        "accessibility_tactile": "🦯 Tactile guidance: {status}",
        "accessibility_audio": "🔊 Audio announcements: {status}",
        "accessibility_machines": "🎫 Accessible machines: {status}",
        "accessibility_wheelchair": "🦽 Wheelchair spaces: {status}",
        "accessibility_notes": "📝 *Notes:* {notes}",
        "accessibility_search_prompt": "🔍 Type the name of the metro station:",
        "accessibility_not_found": "❌ Station *{name}* not found\\. Try another name\\.",
        "accessibility_status_ok": "✅ Operational",
        "accessibility_status_maintenance": "🔧 Under maintenance",
        "accessibility_status_out": "❌ Out of service",
        "kb_accessibility": "♿ Accessibility",
        "kb_accessibility_search": "🔍 Search station",
        "kb_accessibility_elevators": "🛗 Elevator status",
        # Weather
        "weather_title": "Porto Weather",
        "weather_temp": "Temperature",
        "weather_rain": "Rain probability",
        "weather_sunrise": "Sunrise",
        "weather_sunset": "Sunset",
        "weather_tip": "Transport tip",
        "weather_tip_rain": "Rain likely \\- prefer metro",
        "weather_tip_nice": "Nice weather \\- pleasant for walking",
        "weather_tip_hot": "Hot \\- prefer air\\-conditioned transport",
        "weather_tip_cold": "Cold \\- shelter in stations",
        "weather_disclaimer": "Source: Open\\-Meteo\\.com \\(real\\-time\\)",
        "kb_weather": "🌤 Weather",
    },
}

# Zone code to readable name mapping
ZONE_NAMES = {
    "PRT": "Porto (Z2)",
    "MTS": "Matosinhos (Z2-Z4)",
    "VNG": "Vila Nova de Gaia (Z3-Z5)",
    "MAI": "Maia (Z3-Z6)",
    "GDM": "Gondomar (Z3-Z4)",
    "VLG": "Valongo (Z4-Z5)",
    "VCD": "Vila do Conde (Z7-Z8)",
    "PVZ": "Póvoa de Varzim (Z8-Z10)",
}


# ---------------------------------------------------------------------------
# Language resolution
#
# The user can pick Auto / Português / English in /settings, and that choice is
# persisted as the ``language`` setting. Reading that setting is async, while
# ``get_lang()`` is called from ~200 places including sync code, so we keep a
# small in-process cache of each user's *preference* ('auto' | 'pt' | 'en'):
#
#   * ``get_lang(update)``      -- sync, consults the cache first and falls back
#                                  to the Telegram locale. Signature unchanged.
#   * ``resolve_lang(update)``  -- async, reads (and caches) the stored setting.
#   * ``set_lang_preference()`` -- write-through, called by the settings handler
#                                  the moment the user changes the setting.
#
# ``get_lang()`` also kicks off a fire-and-forget prime of the cache when it is
# called from inside a running event loop, so from the user's *second* message
# onwards the stored preference is honoured everywhere without touching any of
# the existing call sites.
# ---------------------------------------------------------------------------

DEFAULT_LANG = "pt"
AUTO_LANG = "auto"

# user_id -> stored preference ('auto' | 'pt' | 'en')
_lang_pref_cache: dict[int, str] = {}
# Strong references to in-flight priming tasks (so they are not GC'd mid-flight)
_priming: dict[int, "asyncio.Task"] = {}


def locale_lang(update: Update) -> str:
    """Return the language implied by the user's Telegram locale.

    Portuguese locales get Portuguese; every other *known* locale gets that
    locale; any other locale (fr, es, de, ...) gets English rather than
    Portuguese -- a tourist who does not read Portuguese is better served by
    English. When no locale is available at all we keep the Porto-local
    default of Portuguese.
    """
    user = getattr(update, "effective_user", None)
    if user is None:
        return DEFAULT_LANG
    code = getattr(user, "language_code", None)
    # Guard against MagicMock / non-string values from odd Update objects.
    if not isinstance(code, str) or not code:
        return DEFAULT_LANG
    code = code[:2].lower()
    if code.startswith("pt"):
        return "pt"
    if code in TRANSLATIONS:
        return code
    return "en"


def _user_id(update: Update):
    """Return the user id if it is usable as a cache key, else None."""
    user = getattr(update, "effective_user", None)
    uid = getattr(user, "id", None) if user is not None else None
    return uid if isinstance(uid, int) else None


def _apply_pref(pref, update: Update) -> str:
    """Turn a stored preference into an actual language code."""
    if isinstance(pref, str) and pref.lower() in TRANSLATIONS:
        return pref.lower()
    return locale_lang(update)


def set_lang_preference(user_id, pref: str) -> None:
    """Write a user's language preference straight into the cache.

    Called by the settings handler so the very next rendered message already
    uses the new language, without waiting for a DB round-trip.
    """
    if not isinstance(user_id, int):
        return
    pref = (pref or AUTO_LANG).lower()
    if pref in TRANSLATIONS or pref == AUTO_LANG:
        _lang_pref_cache[user_id] = pref
    else:
        _lang_pref_cache.pop(user_id, None)


def clear_lang_cache(user_id=None) -> None:
    """Forget cached preferences (all of them, or just one user's)."""
    if user_id is None:
        _lang_pref_cache.clear()
    else:
        _lang_pref_cache.pop(user_id, None)


async def _load_pref(user_id: int) -> str:
    """Read the stored ``language`` setting. Never raises."""
    try:
        from bot.database import get_user_settings

        settings = await get_user_settings(user_id)
        pref = (settings or {}).get("language", AUTO_LANG)
        return pref.lower() if isinstance(pref, str) else AUTO_LANG
    except Exception as err:  # DB down, no pool, unexpected schema...
        logger.debug("Could not load language preference for %s: %s", user_id, err)
        raise


async def _prime(user_id: int) -> None:
    try:
        pref = await _load_pref(user_id)
    except Exception:
        return
    finally:
        _priming.pop(user_id, None)
    _lang_pref_cache[user_id] = pref


def _schedule_prime(user_id: int) -> None:
    """Populate the cache in the background, if we are inside an event loop."""
    if user_id in _lang_pref_cache or user_id in _priming:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # sync context, nothing we can do -- locale fallback applies
    try:
        _priming[user_id] = loop.create_task(_prime(user_id))
    except Exception:  # pragma: no cover - defensive
        _priming.pop(user_id, None)


def get_lang(update: Update) -> str:
    """Detect the language to render for this user (sync, never raises).

    Order: cached stored preference -> Telegram locale -> Portuguese.
    """
    uid = _user_id(update)
    if uid is not None:
        pref = _lang_pref_cache.get(uid)
        if pref is not None:
            return _apply_pref(pref, update)
        _schedule_prime(uid)
    return locale_lang(update)


async def resolve_lang(update: Update) -> str:
    """Async counterpart of :func:`get_lang` that reads the stored setting.

    Reads the persisted ``language`` setting (caching it for all the sync
    ``get_lang()`` call sites) and resolves ``'auto'`` to the Telegram locale.
    Falls back to the locale if the database is unavailable.
    """
    uid = _user_id(update)
    if uid is None:
        return locale_lang(update)

    pref = _lang_pref_cache.get(uid)
    if pref is None:
        try:
            pref = await _load_pref(uid)
        except Exception:
            return locale_lang(update)
        _lang_pref_cache[uid] = pref
    return _apply_pref(pref, update)


def t(key: str, lang: str = "pt") -> str:
    """Get translated string.

    Fallback chain: requested language -> Portuguese -> the raw key.
    Never raises, whatever ``lang`` or ``key`` is.
    """
    translations = TRANSLATIONS.get(lang) if isinstance(lang, str) else None
    if not isinstance(translations, dict):
        translations = TRANSLATIONS["pt"]
    try:
        value = translations.get(key)
        if value is None:
            value = TRANSLATIONS["pt"].get(key)
    except TypeError:  # unhashable key
        return str(key)
    return value if value is not None else str(key)


def get_zone_display(zone_code: str) -> str:
    """Get displayable zone name from zone code."""
    return ZONE_NAMES.get(zone_code, zone_code)
