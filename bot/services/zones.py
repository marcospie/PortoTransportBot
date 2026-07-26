"""Andante zone calculator for Porto public transport.

Andante does **not** use concentric numbered rings.  The Área Metropolitana do
Porto is divided into 154 irregular zones whose real, signposted names are a
municipality prefix plus a number -- ``PRT1``, ``PRT2``, ``PRT3`` for the city
of Porto, ``VNG1``..``VNG12`` for Vila Nova de Gaia, ``MTS1``..``MTS3`` for
Matosinhos, and so on.  (Before May 2019 the Porto zones were called ``C1``,
``C2`` and ``C6``; those names are gone.)

The fare for a journey is the number of zone *rings* you have to traverse,
counted outwards from the zone where you validate -- i.e. the shortest path
through the zone adjacency graph.  A journey inside one zone counts as 1, a
journey into a bordering zone counts as 2, and so on.  The title you buy is
``Z<count>`` with a minimum of ``Z2``; see :mod:`bot.services.fares`.

``Z2``..``Z19`` are therefore *ticket* names, not zone names.  The old version
of this module used ``Z2``..``Z12`` as if they were zone identifiers and
computed ``abs(dest_index - origin_index) + 1``, which is a one-dimensional
model of a two-dimensional map.  It produced badly wrong answers (Trindade ->
Santo Ovídio came out as 4 zones / 3.05€ when the real answer is 2 zones /
1.40€) and the codes it showed users matched nothing on station signage.

Data provenance
---------------
``ZONE_ADJACENCY``
    Derived from the official zone-to-zone distance matrix published with
    Andante's own zone map,
    https://andante.pt/wp-content/uploads/maps/data/distances.csv (a complete,
    symmetric 154x154 matrix; the map itself is
    https://andante.pt/wp-content/uploads/maps/mapa_rede.html and the polygons
    are https://andante.pt/wp-content/uploads/maps/data/zAndante.geojson).
    Two zones are adjacent here iff the official matrix gives them distance 2.
    Breadth-first search over this graph reproduces all 23,716 published
    distances exactly, so :func:`zone_distance` is not an approximation.

Metro station zones (``_METRO_ZONES``)
    Official.  From Metro do Porto's own "Contar as Zonas" data set,
    https://www.metrodoporto.pt/assets/metrodoporto/metroporto/javascripts/\
metro_viajar_stations-v3-2414818d42.min.js, cross-checked against the
    ``zone_id`` column of the Metro GTFS feed on opendata.porto.digital and
    against point-in-polygon containment in ``zAndante.geojson`` (85/85 agree).

CP station zones (``_CP_ZONES``)
    Mostly official, from CP's "Zonamento Andante - Rede CP" map,
    https://www.cp.pt/info/documents/d/cp/zonamento-andante-rede-cp .  That PDF
    stores its labels as vector outlines so it cannot be parsed; the values
    below were read off the rendered map and, where they could be, confirmed by
    point-in-polygon containment.  Stations where the two disagreed, or whose
    coordinates we could not confirm, are listed in :data:`ESTIMATED_ZONES`.

MetroBus stop zones (``_METROBUS_ZONES``)
    The real MetroBus network is a single line, Boavista, with seven stops:
    Casa da Música, Guerra Junqueiro, Bessa, Pinheiro Manso, Serralves, João de
    Barros, Império.  Reported to run entirely inside PRT1 and PRT2
    (https://www.idealista.pt/news/ferias/viagens/2026/04/22/\
75077-metrobus-do-porto-passa-a-ser-pago-guia-para-entender-como-funciona).
    Casa da Música is official (it is also a metro station); the per-stop split
    between PRT1 and PRT2 is our best reading of the corridor and every other
    stop is therefore in :data:`ESTIMATED_ZONES`.

Anything flagged in :data:`ESTIMATED_ZONES` makes
:func:`calculate_zones` return ``exact=False`` so the handler can tell the user
the answer is an estimate instead of presenting a guess as fact.
"""

import logging

from bot.services import fares

logger = logging.getLogger(__name__)

# Backwards-compatible aliases -- every price now lives in bot.services.fares.
ZONE_PRICES = fares.OCCASIONAL_PRICES
DAY_PASS_PRICES = fares.DAY_PASS_PRICES
ANDANTE_TOUR_PRICE = fares.ANDANTE_TOUR_PRICE
LAST_VERIFIED = fares.LAST_VERIFIED
SOURCE_URL = fares.SOURCE_URL
TARIFF_EFFECTIVE_FROM = fares.TARIFF_EFFECTIVE_FROM


# ---------------------------------------------------------------------------
# Official Andante zones
# ---------------------------------------------------------------------------

#: Every zone in the Andante network, with its real signposted name.
ANDANTE_ZONES: tuple[str, ...] = (
    "ARC1", "ARC10", "ARC11", "ARC12", "ARC13", "ARC14", "ARC15", "ARC16",
    "ARC17", "ARC18", "ARC19", "ARC2", "ARC20", "ARC21", "ARC3", "ARC4",
    "ARC5", "ARC6", "ARC7", "ARC8", "ARC9", "AVE1", "AVE2", "AVE3", "AVE4",
    "AVE5", "CAV1", "CAV2", "CAV3", "ESP1", "GDM1", "GDM2", "GDM3", "GDM4",
    "GDM5", "GDM6", "GDM7", "GDM8", "GDM9", "MAI1", "MAI2", "MAI3", "MAI4",
    "MAI5", "MTS1", "MTS2", "MTS3", "OAZ1", "OAZ2", "OAZ3", "OAZ4", "OAZ5",
    "OAZ6", "OAZ7", "OAZ8", "PRD1", "PRD2", "PRD3", "PRD4", "PRD5", "PRD6",
    "PRD7", "PRD8", "PRD9", "PRT1", "PRT2", "PRT3", "PVZ2", "PVZ3", "PVZ4",
    "PVZ5", "PVZ6", "PV_VC", "RAV1", "RAV10", "RAV2", "RAV3", "RAV4",
    "RAV5", "RAV6", "RAV7", "RAV8", "RAV9", "SJM1", "SMF1", "SMF10",
    "SMF11", "SMF12", "SMF2", "SMF3", "SMF4", "SMF5", "SMF6", "SMF7",
    "SMF8", "SMF9", "STR1", "STR2", "STR3", "STR4", "STR5", "STR6", "STR7",
    "STR8", "TES1", "TES10", "TES11", "TES12", "TES2", "TES3", "TES4",
    "TES5", "TES6", "TES7", "TES8", "TES9", "TRF1", "TRF2", "TRF3", "VCB1",
    "VCB2", "VCB3", "VCB4", "VCB5", "VCB6", "VCB7", "VCB8", "VCB9", "VCD10",
    "VCD11", "VCD12", "VCD2", "VCD3", "VCD4", "VCD5", "VCD6", "VCD7",
    "VCD8", "VCD9", "VLG1", "VLG2", "VLG3", "VNG1", "VNG10", "VNG11",
    "VNG12", "VNG2", "VNG3", "VNG4", "VNG5", "VNG6", "VNG7", "VNG8", "VNG9"
)

#: Prefix -> municipality / territory the zone belongs to.
ZONE_TERRITORIES: dict[str, str] = {
    "ARC": "Arouca",
    "AVE": "Vila Nova de Famalicão (Ave)",
    "CAV": "Cávado",
    "ESP": "Espinho",
    "GDM": "Gondomar",
    "MAI": "Maia",
    "MTS": "Matosinhos",
    "OAZ": "Oliveira de Azeméis",
    "PRD": "Paredes",
    "PRT": "Porto",
    "PVZ": "Póvoa de Varzim",
    "PV_VC": "Póvoa de Varzim / Vila do Conde",
    "RAV": "Região de Aveiro",
    "SJM": "São João da Madeira",
    "SMF": "Santa Maria da Feira",
    "STR": "Santo Tirso",
    "TES": "Tâmega e Sousa",
    "TRF": "Trofa",
    "VCB": "Vale de Cambra",
    "VCD": "Vila do Conde",
    "VLG": "Valongo",
    "VNG": "Vila Nova de Gaia",
}

#: Zone adjacency (honeycomb neighbours).  See the module docstring for how
#: this was derived and verified.
ZONE_ADJACENCY: dict[str, tuple[str, ...]] = {
    "ARC1": ("ARC2", "ARC3", "ARC4", "ARC5", "ARC6", "ARC7"),
    "ARC10": ("ARC11", "ARC3", "ARC9"),
    "ARC11": ("ARC10", "ARC12", "ARC18", "ARC3", "ARC4"),
    "ARC12": ("ARC11", "ARC4", "ARC5"),
    "ARC13": ("ARC5", "ARC6", "VCB5", "VCB8"),
    "ARC14": ("ARC15", "ARC6", "ARC7", "VCB2", "VCB5"),
    "ARC15": ("ARC14", "ARC16", "ARC19", "ARC20", "ARC7", "VCB2"),
    "ARC16": ("ARC15", "ARC20", "ARC21", "ARC7"),
    "ARC17": ("ARC9",),
    "ARC18": ("ARC11",),
    "ARC19": ("ARC15", "ARC20", "OAZ8", "SMF12", "SMF9", "VCB2"),
    "ARC2": ("ARC1", "ARC3", "ARC8", "ARC9"),
    "ARC20": ("ARC15", "ARC16", "ARC19", "ARC21", "SMF11", "SMF12"),
    "ARC21": ("ARC16", "ARC20", "GDM8", "SMF11"),
    "ARC3": ("ARC1", "ARC10", "ARC11", "ARC2", "ARC4", "ARC9"),
    "ARC4": ("ARC1", "ARC11", "ARC12", "ARC3", "ARC5"),
    "ARC5": ("ARC1", "ARC12", "ARC13", "ARC4", "ARC6"),
    "ARC6": ("ARC1", "ARC13", "ARC14", "ARC5", "ARC7", "VCB5"),
    "ARC7": ("ARC1", "ARC14", "ARC15", "ARC16", "ARC6"),
    "ARC8": ("ARC2",),
    "ARC9": ("ARC10", "ARC17", "ARC2", "ARC3"),
    "AVE1": ("AVE2", "AVE5", "TRF1"),
    "AVE2": ("AVE1", "AVE5"),
    "AVE3": ("AVE4", "STR5", "STR7"),
    "AVE4": ("AVE3", "AVE5", "STR2", "STR5"),
    "AVE5": ("AVE1", "AVE2", "AVE4", "STR1", "STR2"),
    "CAV1": ("CAV2", "CAV3", "PVZ4"),
    "CAV2": ("CAV1", "CAV3", "PVZ4"),
    "CAV3": ("CAV1", "CAV2"),
    "ESP1": ("RAV1", "SMF5", "VNG10", "VNG8"),
    "GDM1": ("GDM2", "GDM3", "MAI4", "PRT3", "VLG1"),
    "GDM2": ("GDM1", "GDM3", "GDM4", "PRD9", "VLG1"),
    "GDM3": ("GDM1", "GDM2", "GDM4", "PRT3", "VNG1", "VNG2"),
    "GDM4": ("GDM2", "GDM3", "GDM5", "PRD9", "VNG2", "VNG6"),
    "GDM5": ("GDM4", "GDM6", "PRD9", "VNG11", "VNG6", "VNG9"),
    "GDM6": ("GDM5", "GDM7", "PRD9", "SMF10", "VNG11"),
    "GDM7": ("GDM6", "GDM8", "GDM9", "PRD9", "SMF10"),
    "GDM8": ("ARC21", "GDM7", "GDM9", "SMF10", "SMF11", "TES9"),
    "GDM9": ("GDM7", "GDM8", "PRD8", "PRD9", "TES10", "TES9"),
    "MAI1": ("MAI2", "MAI3", "MAI4", "MTS1", "MTS2", "PRT2", "PRT3", "VCD8"),
    "MAI2": ("MAI1", "MAI3", "MAI5", "TRF2", "VCD12", "VCD8"),
    "MAI3": ("MAI1", "MAI2", "MAI4", "MAI5"),
    "MAI4": ("GDM1", "MAI1", "MAI3", "MAI5", "PRT3", "VLG1", "VLG2"),
    "MAI5": ("MAI2", "MAI3", "MAI4", "TRF2", "TRF3", "VLG2"),
    "MTS1": ("MAI1", "MTS2", "PRT2"),
    "MTS2": ("MAI1", "MTS1", "MTS3", "VCD8"),
    "MTS3": ("MTS2", "VCD8", "VCD9"),
    "OAZ1": ("OAZ2", "OAZ3", "OAZ4", "OAZ5", "OAZ6", "OAZ7"),
    "OAZ2": ("OAZ1", "OAZ3", "OAZ7", "RAV4", "SJM1", "SMF4"),
    "OAZ3": ("OAZ1", "OAZ2", "OAZ4", "OAZ8", "SJM1", "SMF9"),
    "OAZ4": ("OAZ1", "OAZ3", "OAZ5", "OAZ8", "VCB1", "VCB4"),
    "OAZ5": ("OAZ1", "OAZ4", "OAZ6", "VCB4"),
    "OAZ6": ("OAZ1", "OAZ5", "OAZ7"),
    "OAZ7": ("OAZ1", "OAZ2", "OAZ6", "RAV5"),
    "OAZ8": ("ARC19", "OAZ3", "OAZ4", "SMF9", "VCB1", "VCB2"),
    "PRD1": ("PRD2", "PRD3", "PRD4", "TES1", "TES2"),
    "PRD2": ("PRD1", "PRD3", "PRD5", "PRD6", "TES1"),
    "PRD3": ("PRD1", "PRD2", "PRD4", "PRD6", "PRD7", "TES4"),
    "PRD4": ("PRD1", "PRD3", "TES2", "TES3", "TES4"),
    "PRD5": ("PRD2", "PRD6", "PRD8", "PRD9", "VLG1", "VLG3"),
    "PRD6": ("PRD2", "PRD3", "PRD5", "PRD7", "VLG3"),
    "PRD7": ("PRD3", "PRD6", "TES4", "TES5", "VLG3"),
    "PRD8": ("GDM9", "PRD5", "PRD9"),
    "PRD9": ("GDM2", "GDM4", "GDM5", "GDM6", "GDM7", "GDM9", "PRD5", "PRD8", "VLG1"),
    "PRT1": ("PRT2", "PRT3", "VNG1"),
    "PRT2": ("MAI1", "MTS1", "PRT1", "PRT3", "VNG1", "VNG5"),
    "PRT3": ("GDM1", "GDM3", "MAI1", "MAI4", "PRT1", "PRT2", "VNG1"),
    "PVZ2": ("PVZ3", "PV_VC", "VCD2", "VCD4"),
    "PVZ3": ("PVZ2", "PVZ4", "PVZ5", "VCD4"),
    "PVZ4": ("CAV1", "CAV2", "PVZ3", "PVZ5"),
    "PVZ5": ("PVZ3", "PVZ4", "PVZ6", "VCD4"),
    "PVZ6": ("PVZ5", "VCD10", "VCD4", "VCD5"),
    "PV_VC": ("PVZ2", "VCD2", "VCD3"),
    "RAV1": ("ESP1", "SMF5"),
    "RAV10": ("RAV9",),
    "RAV2": ("RAV3", "SMF1"),
    "RAV3": ("RAV2", "RAV4", "SMF1"),
    "RAV4": ("OAZ2", "RAV3", "SMF1", "SMF4"),
    "RAV5": ("OAZ7", "RAV6", "RAV7"),
    "RAV6": ("RAV5", "RAV7"),
    "RAV7": ("RAV5", "RAV6", "RAV8"),
    "RAV8": ("RAV7", "RAV9"),
    "RAV9": ("RAV10", "RAV8"),
    "SJM1": ("OAZ2", "OAZ3", "SMF4", "SMF9"),
    "SMF1": ("RAV2", "RAV3", "RAV4", "SMF2", "SMF3", "SMF4"),
    "SMF10": ("GDM6", "GDM7", "GDM8", "SMF11", "SMF7", "VNG11", "VNG12"),
    "SMF11": ("ARC20", "ARC21", "GDM8", "SMF10", "SMF12", "SMF7"),
    "SMF12": ("ARC19", "ARC20", "SMF11", "SMF7", "SMF8", "SMF9"),
    "SMF2": ("SMF1", "SMF3", "SMF5"),
    "SMF3": ("SMF1", "SMF2", "SMF4", "SMF5", "SMF6", "SMF7", "SMF8"),
    "SMF4": ("OAZ2", "RAV4", "SJM1", "SMF1", "SMF3", "SMF8", "SMF9"),
    "SMF5": ("ESP1", "RAV1", "SMF2", "SMF3", "SMF6", "VNG10"),
    "SMF6": ("SMF3", "SMF5", "SMF7", "VNG10", "VNG12", "VNG9"),
    "SMF7": ("SMF10", "SMF11", "SMF12", "SMF3", "SMF6", "SMF8", "VNG12"),
    "SMF8": ("SMF12", "SMF3", "SMF4", "SMF7", "SMF9"),
    "SMF9": ("ARC19", "OAZ3", "OAZ8", "SJM1", "SMF12", "SMF4", "SMF8"),
    "STR1": ("AVE5", "STR2", "STR3", "STR4", "TRF1", "TRF3"),
    "STR2": ("AVE4", "AVE5", "STR1", "STR3", "STR5"),
    "STR3": ("STR1", "STR2", "STR4", "STR5", "TES4", "TES8"),
    "STR4": ("STR1", "STR3", "STR6", "TRF3"),
    "STR5": ("AVE3", "AVE4", "STR2", "STR3", "STR7", "TES8"),
    "STR6": ("STR4", "STR8", "TES5", "TRF3"),
    "STR7": ("AVE3", "STR5", "TES8"),
    "STR8": ("STR6", "TES5", "TRF3", "VLG1", "VLG2", "VLG3"),
    "TES1": ("PRD1", "PRD2", "TES6"),
    "TES10": ("GDM9", "TES11", "TES9"),
    "TES11": ("TES10", "TES12"),
    "TES12": ("TES11",),
    "TES2": ("PRD1", "PRD4", "TES3", "TES7", "TES8"),
    "TES3": ("PRD4", "TES2", "TES4", "TES8"),
    "TES4": ("PRD3", "PRD4", "PRD7", "STR3", "TES3", "TES5", "TES8"),
    "TES5": ("PRD7", "STR6", "STR8", "TES4", "VLG3"),
    "TES6": ("TES1", "TES7"),
    "TES7": ("TES2", "TES6"),
    "TES8": ("STR3", "STR5", "STR7", "TES2", "TES3", "TES4"),
    "TES9": ("GDM8", "GDM9", "TES10"),
    "TRF1": ("AVE1", "STR1", "TRF2", "TRF3"),
    "TRF2": ("MAI2", "MAI5", "TRF1", "TRF3", "VCD11", "VCD12"),
    "TRF3": ("MAI5", "STR1", "STR4", "STR6", "STR8", "TRF1", "TRF2", "VLG2"),
    "VCB1": ("OAZ4", "OAZ8", "VCB2", "VCB3", "VCB4"),
    "VCB2": ("ARC14", "ARC15", "ARC19", "OAZ8", "VCB1", "VCB3", "VCB5"),
    "VCB3": ("VCB1", "VCB2", "VCB4", "VCB5", "VCB6", "VCB7"),
    "VCB4": ("OAZ4", "OAZ5", "VCB1", "VCB3", "VCB7"),
    "VCB5": ("ARC13", "ARC14", "ARC6", "VCB2", "VCB3", "VCB6", "VCB8"),
    "VCB6": ("VCB3", "VCB5", "VCB7", "VCB8", "VCB9"),
    "VCB7": ("VCB3", "VCB4", "VCB6", "VCB9"),
    "VCB8": ("ARC13", "VCB5", "VCB6", "VCB9"),
    "VCB9": ("VCB6", "VCB7", "VCB8"),
    "VCD10": ("PVZ6", "VCD11", "VCD5", "VCD6"),
    "VCD11": ("TRF2", "VCD10", "VCD12", "VCD6", "VCD7"),
    "VCD12": ("MAI2", "TRF2", "VCD11", "VCD7", "VCD8"),
    "VCD2": ("PVZ2", "PV_VC", "VCD3", "VCD4", "VCD5", "VCD6"),
    "VCD3": ("PV_VC", "VCD2", "VCD6", "VCD7", "VCD8", "VCD9"),
    "VCD4": ("PVZ2", "PVZ3", "PVZ5", "PVZ6", "VCD2", "VCD5"),
    "VCD5": ("PVZ6", "VCD10", "VCD2", "VCD4", "VCD6"),
    "VCD6": ("VCD10", "VCD11", "VCD2", "VCD3", "VCD5", "VCD7"),
    "VCD7": ("VCD11", "VCD12", "VCD3", "VCD6", "VCD8"),
    "VCD8": ("MAI1", "MAI2", "MTS2", "MTS3", "VCD12", "VCD3", "VCD7", "VCD9"),
    "VCD9": ("MTS3", "VCD3", "VCD8"),
    "VLG1": ("GDM1", "GDM2", "MAI4", "PRD5", "PRD9", "STR8", "VLG2", "VLG3"),
    "VLG2": ("MAI4", "MAI5", "STR8", "TRF3", "VLG1"),
    "VLG3": ("PRD5", "PRD6", "PRD7", "STR8", "TES5", "VLG1"),
    "VNG1": ("GDM3", "PRT1", "PRT2", "PRT3", "VNG2", "VNG3", "VNG4", "VNG5"),
    "VNG10": ("ESP1", "SMF5", "SMF6", "VNG6", "VNG7", "VNG8", "VNG9"),
    "VNG11": ("GDM5", "GDM6", "SMF10", "VNG12", "VNG9"),
    "VNG12": ("SMF10", "SMF6", "SMF7", "VNG11", "VNG9"),
    "VNG2": ("GDM3", "GDM4", "VNG1", "VNG3", "VNG6"),
    "VNG3": ("VNG1", "VNG2", "VNG4", "VNG6", "VNG7", "VNG8"),
    "VNG4": ("VNG1", "VNG3", "VNG5", "VNG8"),
    "VNG5": ("PRT2", "VNG1", "VNG4"),
    "VNG6": ("GDM4", "GDM5", "VNG10", "VNG2", "VNG3", "VNG7", "VNG9"),
    "VNG7": ("VNG10", "VNG3", "VNG6", "VNG8"),
    "VNG8": ("ESP1", "VNG10", "VNG3", "VNG4", "VNG7"),
    "VNG9": ("GDM5", "SMF6", "VNG10", "VNG11", "VNG12", "VNG6"),
}


# ---------------------------------------------------------------------------
# Station -> zone tables
# ---------------------------------------------------------------------------

#: Metro do Porto stations.  Official data -- see module docstring.
_METRO_ZONES: dict[str, str] = {
    "Senhor de Matosinhos": "MTS1",
    "Mercado": "MTS1",
    "Brito Capelo": "MTS1",
    "Matosinhos Sul": "MTS1",
    "Câmara de Matosinhos": "MTS1",
    "Parque de Real": "MTS1",
    "Pedro Hispano": "MTS1",
    "Vasco da Gama": "MTS1",
    "Estádio do Mar": "MTS1",
    "Senhora da Hora": "PRT2",
    "Sete Bicas": "PRT2",
    "Viso": "PRT2",
    "Ramalde": "PRT2",
    "Francos": "PRT1",
    "Casa da Música": "PRT1",
    "Carolina Michaelis": "PRT1",
    "Lapa": "PRT1",
    "Trindade": "PRT1",
    "Bolhão": "PRT1",
    "Campo 24 de Agosto": "PRT1",
    "Heroísmo": "PRT1",
    "Campanhã": "PRT1",
    "Estádio do Dragão": "PRT1",
    "Nasoni": "PRT3",
    "Nau Vitória": "PRT3",
    "Contumil": "PRT3",
    "Levada": "MAI4",
    "Rio Tinto": "MAI4",
    "Campainha": "MAI4",
    "Baguim": "MAI4",
    "Fânzeres": "GDM1",
    "Venda Nova": "GDM1",
    "Carreira": "MAI4",
    "Custió": "MAI1",
    "Araújo": "MAI1",
    "Cândido dos Reis": "MAI1",
    "Pias": "MAI1",
    "Fórum da Maia": "MAI1",
    "Parque da Maia": "MAI1",
    "Mandim": "MAI2",
    "Zona Industrial": "MAI2",
    "Castêlo da Maia": "MAI2",
    "ISMAI": "MAI2",
    "Hospital de São João": "PRT3",
    "IPO": "PRT3",
    "Polo Universitário": "PRT3",
    "Salgueiros": "PRT1",
    "Combatentes": "PRT1",
    "Marquês": "PRT1",
    "Faria Guimarães": "PRT1",
    "Aliados": "PRT1",
    "São Bento": "PRT1",
    "Jardim do Morro": "VNG1",
    "General Torres": "VNG1",
    "Câmara de Gaia": "VNG1",
    "João de Deus": "VNG1",
    "Santo Ovídio": "VNG1",
    "D. João II": "VNG1",
    "Manuel Leão": "VNG1",
    "Vila d'Este": "VNG2",
    "Hospital Santos Silva": "VNG2",
    "Custóias": "MAI1",
    "Crestins": "VCD8",
    "Esposade": "MAI1",
    "Vilar do Pinheiro": "VCD8",
    "Modivas Sul": "VCD8",
    "Modivas Centro": "VCD8",
    "Mindelo": "VCD3",
    "Varziela": "VCD3",
    "Árvore": "VCD3",
    "Azurara": "VCD3",
    "Vila do Conde": "PV_VC",
    "Santa Clara": "PV_VC",
    "Portas Fronhas": "PV_VC",
    "Alto de Pega": "PV_VC",
    "São Brás": "PV_VC",
    "Póvoa de Varzim": "PV_VC",
    "Aeroporto": "VCD8",
    "Pedras Rubras": "VCD8",
    "Verdes": "VCD8",
    "Lidador": "VCD8",
    "Botica": "VCD8",
    "Fonte do Cuco": "MAI1",
    "Via Rápida Viso": "PRT2",
    "Espaço Natureza": "VCD3",
    "VC Fashion Outlet – Modivas": "VCD8",
}

#: CP suburban / regional stations reachable with Andante.
_CP_ZONES: dict[str, str] = {
    # Read off CP's official "Zonamento Andante - Rede CP" map.
    "Porto-Campanhã": "PRT1",
    "Porto-São Bento": "PRT1",
    "Ermesinde": "MAI4",
    "Valongo": "VLG1",
    "Valadares": "VNG4",
    "Granja": "VNG8",
    "Miramar": "VNG8",
    "Trofa": "TRF1",
    "Santo Tirso": "STR1",
    "São Gemil": "MAI1",
    "Leça do Balio": "MAI1",
    "São Romão": "TRF3",
    "Lousado": "AVE5",
    # Derived from point-in-polygon containment in the official zone map; the
    # CP map either disagrees or does not show them legibly.  All flagged in
    # ESTIMATED_ZONES.
    "Espinho": "VNG8",
    "Espinho-Vouga": "ESP1",
    "São Félix da Marinha": "VNG8",
    "Cete": "PRD2",
    "Lordelo": "PRD2",
    "Receção": "PRD5",
    "Paredes": "PRD1",
    "Penafiel": "TES6",
    "Nine": "AVE2",
    "Aveiro": "RAV10",
}

#: MetroBus (BRT) stops -- the real Boavista line, in order.
_METROBUS_ZONES: dict[str, str] = {
    "Casa da Música (MetroBus)": "PRT1",
    "Guerra Junqueiro": "PRT1",
    "Bessa": "PRT2",
    "Pinheiro Manso": "PRT2",
    "Serralves": "PRT2",
    "João de Barros": "PRT2",
    "Império": "PRT2",
}

#: Complete station/stop -> official Andante zone code mapping.
ZONES: dict[str, str] = {**_METRO_ZONES, **_CP_ZONES, **_METROBUS_ZONES}

#: Stations we can name but that lie outside the Andante network, so no Andante
#: zone or price applies to them at all.  Sourced by checking each against the
#: official zone map: none of them falls inside any Andante zone polygon.
OUTSIDE_ANDANTE: frozenset[str] = frozenset({
    "Braga",
    "Guimarães",
    "Marco de Canaveses",
    "Caíde",
    "Viana do Castelo",
    "Vizela",
})

#: Stations whose zone is our best estimate rather than published fact.
#: :func:`calculate_zones` marks any journey touching one of these as
#: ``exact=False`` so the bot can say so out loud.
ESTIMATED_ZONES: frozenset[str] = frozenset({
    # CP: sources conflict or the station coordinates could not be confirmed.
    "Espinho",
    "Espinho-Vouga",
    "São Félix da Marinha",
    "Cete",
    "Lordelo",
    "Receção",
    "Paredes",
    "Penafiel",
    "Nine",
    "Aveiro",
    # MetroBus: only the PRT1+PRT2 extent of the line is published, not the
    # zone of each individual stop.
    "Guerra Junqueiro",
    "Bessa",
    "Pinheiro Manso",
    "Serralves",
    "João de Barros",
    "Império",
})

#: Alternative spellings and legacy names -> canonical key in :data:`ZONES` or
#: :data:`OUTSIDE_ANDANTE`.  Accents and case are handled separately by
#: :func:`_normalise`, so these only cover genuinely different spellings.
STATION_ALIASES: dict[str, str] = {
    # cp.py has historically spelled these without the tilde/cedilla.
    "Porto-Campanha": "Porto-Campanhã",
    "Porto Campanhã": "Porto-Campanhã",
    "Porto Campanha": "Porto-Campanhã",
    "Campanhã CP": "Porto-Campanhã",
    "Porto-S. Bento": "Porto-São Bento",
    "Porto São Bento": "Porto-São Bento",
    "São Bento CP": "Porto-São Bento",
    "Receão": "Receção",
    "Recezinhos": "Receção",
    "Lousãdo": "Lousado",
    "Caide": "Caíde",
    # The old module invented "<name> CP" keys that nothing ever looked up.
    "Contumil CP": "Contumil",
    "Rio Tinto CP": "Rio Tinto",
    "General Torres CP": "General Torres",
    "Lordelo CP": "Lordelo",
    # Metro station renames still in circulation.
    "Via Rápida Viso": "Viso",
    "NorteShopping / Sete Bicas": "Sete Bicas",
    "NorteShopping": "Sete Bicas",
    "Sr. de Matosinhos": "Senhor de Matosinhos",
    "24 Agosto": "Campo 24 de Agosto",
    "24 de Agosto": "Campo 24 de Agosto",
    "Fórum Maia": "Fórum da Maia",
    "Parque Maia": "Parque da Maia",
    "Hospital São João": "Hospital de São João",
    "S. Brás": "São Brás",
    "Porta-Fronhas": "Portas Fronhas",
    "Vila D`Este": "Vila d'Este",
    # MetroBus stop names as they appear elsewhere in the bot.
    "Estádio do Bessa": "Bessa",
    "Praça do Império": "Império",
    "Casa da Música (Metrobus)": "Casa da Música (MetroBus)",
}

#: Municipality code (as used by metro.py / metrobus.py) -> a representative
#: zone, used only as a last-resort fallback for stops we have no entry for.
#: Always approximate.
MUNICIPALITY_FALLBACK_ZONE: dict[str, str] = {
    "PRT": "PRT1",
    "MTS": "MTS1",
    "GDM": "GDM1",
    "VNG": "VNG1",
    "MAI": "MAI1",
    "VLG": "VLG1",
    "VCD": "VCD8",
    "PVZ": "PV_VC",
    "ESP": "ESP1",
    "TRF": "TRF1",
    "STR": "STR1",
}


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    """Case- and accent-insensitive key for station lookups."""
    try:
        from bot.utils.search import normalize_simple
        return normalize_simple(name)
    except Exception:  # pragma: no cover - search helper is always present
        return " ".join(name.strip().lower().split())


def _build_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for name in ZONES:
        index.setdefault(_normalise(name), name)
    for name in OUTSIDE_ANDANTE:
        index.setdefault(_normalise(name), name)
    for alias, target in STATION_ALIASES.items():
        index.setdefault(_normalise(alias), target)
    return index


#: normalised name -> canonical station key.
_NAME_INDEX: dict[str, str] = _build_index()


# ---------------------------------------------------------------------------
# Zone graph
# ---------------------------------------------------------------------------

def zone_distance(origin_zone: str, dest_zone: str) -> int | None:
    """Official number of zones a journey between two zones must cover.

    Breadth-first ring count over :data:`ZONE_ADJACENCY`: 1 for a journey that
    stays inside one zone, 2 for a journey into a bordering zone, and so on.
    Returns ``None`` if either zone is unknown or they are not connected.
    """
    if origin_zone not in ZONE_ADJACENCY or dest_zone not in ZONE_ADJACENCY:
        return None
    if origin_zone == dest_zone:
        return 1

    seen = {origin_zone}
    frontier = [origin_zone]
    rings = 1
    while frontier:
        rings += 1
        nxt = []
        for zone in frontier:
            for neighbour in ZONE_ADJACENCY[zone]:
                if neighbour in seen:
                    continue
                if neighbour == dest_zone:
                    return rings
                seen.add(neighbour)
                nxt.append(neighbour)
        frontier = nxt
    return None


def zone_neighbours(zone: str) -> tuple[str, ...]:
    """Zones sharing a border with ``zone``."""
    return ZONE_ADJACENCY.get(zone, ())


def get_zone_territory(zone: str) -> str:
    """Human name of the municipality / territory a zone belongs to."""
    if zone in ZONE_TERRITORIES:
        return ZONE_TERRITORIES[zone]
    prefix = "".join(ch for ch in zone if not ch.isdigit())
    return ZONE_TERRITORIES.get(prefix, zone)


# ---------------------------------------------------------------------------
# Station resolution
# ---------------------------------------------------------------------------

def resolve_station(station_name: str) -> dict | None:
    """Resolve a user-typed name to a station, its zone and how sure we are.

    Returns ``None`` when the name cannot be resolved at all, otherwise a dict
    with ``name`` (canonical), ``zone`` (official code or ``None``),
    ``covered`` (is it inside the Andante network) and ``exact`` (is the zone
    published fact rather than our estimate).
    """
    if not station_name or not station_name.strip():
        return None

    key = _NAME_INDEX.get(_normalise(station_name))

    if key is None:
        key = _resolve_via_transport_modes(station_name)

    if key is None:
        key = _resolve_via_fuzzy(station_name)

    if key is None:
        return None

    if isinstance(key, tuple):  # (name, zone, exact) from a fallback resolver
        name, zone, exact = key
        return {"name": name, "zone": zone, "covered": zone is not None,
                "exact": exact}

    if key in OUTSIDE_ANDANTE:
        return {"name": key, "zone": None, "covered": False, "exact": True}

    zone = ZONES.get(key)
    if zone is None:
        return None
    return {
        "name": key,
        "zone": zone,
        "covered": True,
        "exact": key not in ESTIMATED_ZONES,
    }


def _resolve_via_transport_modes(station_name: str):
    """Fallback: a stop known to another service but absent from ZONES.

    Uses the stop's municipality code to pick a representative zone.  Always
    approximate, and flagged as such.
    """
    normalised = _normalise(station_name)
    for module_name, attr in (
        ("bot.services.metro", "STATIONS"),
        ("bot.services.metrobus", "STOPS"),
        ("bot.services.cp", "STATIONS"),
    ):
        try:
            module = __import__(module_name, fromlist=[attr])
            stops = getattr(module, attr, {})
        except Exception:  # another module may be mid-edit or need network
            continue
        for name, data in stops.items():
            if _normalise(name) != normalised:
                continue
            # The name may map into ZONES through an alias we already tried;
            # if not, fall back to the municipality.
            municipality = (data or {}).get("zone", "")
            zone = MUNICIPALITY_FALLBACK_ZONE.get(municipality)
            if zone:
                logger.debug("Zone for %r approximated from municipality %s",
                             name, municipality)
                return (name, zone, False)
            return None
    return None


def _resolve_via_fuzzy(station_name: str):
    try:
        from bot.utils.search import fuzzy_search
    except Exception:  # pragma: no cover
        return None
    candidates = list(ZONES.keys()) + sorted(OUTSIDE_ANDANTE)
    matches = fuzzy_search(station_name, candidates, min_score=60,
                           max_results=1)
    if matches:
        return matches[0][0]
    return None


def get_zone_for_station(station_name: str) -> str | None:
    """Official Andante zone code for a station/stop name, or ``None``.

    ``None`` means either "unknown station" or "outside the Andante network";
    use :func:`resolve_station` when you need to tell those apart.
    """
    resolved = resolve_station(station_name)
    return resolved["zone"] if resolved else None


def suggest_stations(query: str, limit: int = 3) -> list[str]:
    """Closest station names to ``query`` -- used to offer typo suggestions.

    Combines the shared token matcher in :mod:`bot.utils.search` with a
    character-level close-match pass, because the token matcher only recognises
    whole tokens and so misses ordinary typos such as "Trindad3".
    """
    if not query or not query.strip():
        return []
    candidates = list(ZONES.keys()) + sorted(OUTSIDE_ANDANTE)
    names: list[str] = []

    try:
        from bot.utils.search import fuzzy_search
        names = [name for name, _score in
                 fuzzy_search(query, candidates, min_score=15,
                              max_results=limit * 3)]
    except Exception:  # pragma: no cover
        names = []

    needle = _normalise(query)
    if needle:
        names += [n for n in candidates if needle in _normalise(n)]

        # Character-level fallback catches single-character typos.
        import difflib
        by_normalised = {_normalise(n): n for n in candidates}
        names += [by_normalised[m] for m in difflib.get_close_matches(
            needle, list(by_normalised), n=limit * 2, cutoff=0.7)]

    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Fare calculation
# ---------------------------------------------------------------------------

def calculate_zones(origin: str, destination: str) -> dict | None:
    """Work out the Andante title needed between two stations.

    Returns ``None`` only when a station name cannot be resolved.  Otherwise a
    dict with:

    ``origin_zone`` / ``dest_zone``
        Real Andante zone codes (``"PRT1"``, ``"VNG1"``, ...), or ``None``
        outside the network.
    ``zones_needed``
        Official ring count, or ``None`` when it cannot be determined.
    ``title``
        The ticket to buy (``"Z2"``, ``"Z4"``, ...), or ``None``.
    ``price`` / ``day_pass_price`` / ``bundle_price``
        Euro amounts, or ``None`` when the operator publishes no price.
    ``exact``
        ``False`` when any part of the answer rests on an estimate.
    ``covered``
        ``False`` when a station is outside the Andante network.
    """
    origin_info = resolve_station(origin)
    dest_info = resolve_station(destination)

    if not origin_info or not dest_info:
        return None

    origin_zone = origin_info["zone"]
    dest_zone = dest_info["zone"]
    covered = origin_info["covered"] and dest_info["covered"]
    exact = origin_info["exact"] and dest_info["exact"]

    zones_needed = (zone_distance(origin_zone, dest_zone)
                    if covered else None)
    title_zones = fares.title_zones(zones_needed)

    return {
        "origin_name": origin_info["name"],
        "dest_name": dest_info["name"],
        "origin_zone": origin_zone,
        "dest_zone": dest_zone,
        "origin_territory": get_zone_territory(origin_zone) if origin_zone else None,
        "dest_territory": get_zone_territory(dest_zone) if dest_zone else None,
        "zones_needed": zones_needed,
        "title": fares.title_for_zones(zones_needed),
        "title_zones": title_zones,
        "price": fares.get_price(zones_needed),
        "day_pass_price": fares.get_day_pass_price(zones_needed),
        "bundle_price": fares.get_bundle_price(zones_needed),
        "max_trip_duration": fares.get_max_trip_duration(zones_needed),
        "covered": covered,
        "exact": exact and zones_needed is not None,
        "price_published": fares.has_published_price(zones_needed),
        "verified_on": fares.LAST_VERIFIED,
        "source_url": fares.SOURCE_URL,
    }


def get_price(num_zones: int | None) -> float | None:
    """Single-ticket price for a journey covering ``num_zones`` zones."""
    return fares.get_price(num_zones)


def get_day_pass_price(num_zones: int | None) -> float | None:
    """Andante 24 price for a journey covering ``num_zones`` zones."""
    return fares.get_day_pass_price(num_zones)


def get_title_for_zones(num_zones: int | None) -> str | None:
    """Ticket name for a journey covering ``num_zones`` zones."""
    return fares.title_for_zones(num_zones)


# ---------------------------------------------------------------------------
# Browsing helpers
# ---------------------------------------------------------------------------

def get_stations_in_zone(zone: str) -> list[str]:
    """All stations/stops in a given Andante zone."""
    if not zone:
        return []
    wanted = zone.strip().upper()
    return sorted(name for name, z in ZONES.items() if z == wanted)


def get_all_zones() -> list[str]:
    """Zones that contain at least one station the bot knows about.

    Ordered by how far they are from Porto's central zone, then by name, so the
    zone-map keyboard reads outwards from the city centre.
    """
    zones = set(ZONES.values())
    return sorted(zones, key=lambda z: (zone_distance("PRT1", z) or 99, z))


def search_station(query: str) -> list[tuple[str, str]]:
    """Search stations across all transport modes.

    Returns a list of ``(station_name, zone_code)`` tuples.  Accent- and
    case-insensitive.
    """
    needle = _normalise(query)
    if not needle:
        return []

    results = [(name, zone) for name, zone in ZONES.items()
               if needle in _normalise(name)]
    results.sort(key=lambda item: (
        not _normalise(item[0]).startswith(needle), item[0]))
    return results[:10]
