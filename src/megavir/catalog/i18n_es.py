"""Spanish text for the variable catalog (FR19).

Names, plain definitions, "why it can trend", caveats and the direction phrases used in the
Spanish verdicts ("En resumen: en <lugar> la tendencia es <frase>").
"""

ES: dict[str, dict] = {
    "air_temp": {
        "name": "Temperatura del aire (2 m)",
        "definition": "La temperatura del aire a 2 metros del suelo, promediada entre el día y la noche.",
        "why_it_can_trend": "Los gases de efecto invernadero retienen más calor; el uso del suelo, el riego y las ciudades también cambian la temperatura local.",
        "caveat": "MERRA-2 es un reanálisis: un modelo del tiempo ajustado a observaciones, no una medición directa.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "daily_high": {
        "name": "Temperatura máxima diaria",
        "definition": "La temperatura más alta de cada día a 2 m, promediada en el mes.",
        "why_it_can_trend": "El calentamiento, los suelos más secos y la menor nubosidad elevan las máximas de la tarde.",
        "caveat": "Es un promedio mensual de las máximas diarias, no de extremos de un solo día.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "nightly_low": {
        "name": "Temperatura mínima nocturna",
        "definition": "La temperatura más baja de cada día a 2 m (normalmente al amanecer), promediada en el mes.",
        "why_it_can_trend": "Las noches suelen calentarse más rápido que los días: más vapor de agua y nubes retienen el calor tras la puesta del sol.",
        "caveat": "Es un promedio mensual de las mínimas diarias, no de extremos de una sola noche.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "ground_temp": {
        "name": "Temperatura de la superficie del suelo",
        "definition": "La temperatura de la propia superficie terrestre (su «piel»), vista desde el espacio por infrarrojos, promediando día y noche.",
        "why_it_can_trend": "El aire más cálido, el suelo más seco, la pérdida de vegetación y el asfalto nuevo calientan la superficie.",
        "caveat": "Solo se puede observar sin nubes, así que los meses muy nublados tienen menos datos; malla de 1°.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "temp_change": {
        "name": "Cambio de la temperatura en superficie",
        "definition": "Cuánto más cálida o fría está la superficie respecto al promedio de 1951–1980, según estaciones meteorológicas y barcos.",
        "why_it_can_trend": "Es el registro más usado para seguir el calentamiento global desde 1880.",
        "caveat": "Los valores son diferencias respecto a una referencia, no temperaturas; malla de 2°, con pocas estaciones al principio.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "rainfall": {
        "name": "Precipitación",
        "definition": "Toda la lluvia y la nieve (como agua) que cae en un mes, combinando muchos satélites y pluviómetros.",
        "why_it_can_trend": "Una atmósfera más cálida contiene más agua, y las trayectorias de las tormentas y los monzones pueden desplazarse.",
        "caveat": "La lluvia varía mucho de un año a otro, así que las tendencias necesitan registros largos para destacar.",
        "rising_words": ("a más lluvia", "a menos lluvia"),
    },
    "downpour": {
        "name": "Intensidad de los aguaceros",
        "definition": "La hora de lluvia más intensa de cada día, promediada en el mes.",
        "why_it_can_trend": "El aire más cálido puede descargar más agua de una vez, así que los aguaceros más fuertes pueden intensificarse.",
        "caveat": "Es una estimación de reanálisis de la lluvia por hora; los chaparrones locales se suavizan en celdas de unos 50 km.",
        "rising_words": ("a aguaceros más fuertes", "a aguaceros más débiles"),
    },
    "evapotranspiration": {
        "name": "Evapotranspiración",
        "definition": "El agua que vuelve al aire por evaporación del suelo y del agua y por la transpiración de las plantas.",
        "why_it_can_trend": "El calor, las temporadas de crecimiento más largas, el riego y los suelos más secos cambian cuánta agua regresa al aire.",
        "caveat": "Es una estimación de un modelo de superficie terrestre alimentado con observaciones, no una medición directa.",
        "rising_words": ("a devolver más agua al aire", "a devolver menos agua al aire"),
    },
    "topsoil_moisture": {
        "name": "Humedad del suelo superficial (0–10 cm)",
        "definition": "El agua contenida en los 10 cm superiores del suelo, en milímetros de agua.",
        "why_it_can_trend": "Menos lluvia, más calor o más riego secan o humedecen la capa superficial del suelo.",
        "caveat": "Es una estimación de modelo; responde rápido a tormentas sueltas.",
        "rising_words": ("a un suelo superficial más húmedo", "a un suelo superficial más seco"),
    },
    "soil_moisture": {
        "name": "Humedad del suelo (0–100 cm)",
        "definition": "El agua contenida en el primer metro de suelo, donde están la mayoría de las raíces, en milímetros de agua.",
        "why_it_can_trend": "Las rachas largas secas o húmedas y los cambios en la evaporación se acumulan lentamente en el suelo profundo.",
        "caveat": "Es una estimación de modelo; las capas profundas cambian despacio, así que los años se parecen mucho entre sí.",
        "rising_words": ("a un subsuelo más húmedo", "a un subsuelo más seco"),
    },
    "land_water": {
        "name": "Agua almacenada en tierra",
        "definition": "Toda el agua sobre y bajo la tierra (nieve, suelo, agua subterránea, lagos, hielo), medida por cambios diminutos de la gravedad.",
        "why_it_can_trend": "El bombeo de agua subterránea, el deshielo de los glaciares y las sequías o periodos húmedos largos cambian el agua almacenada.",
        "caveat": "Muy gruesa (rasgos de unos 300 km) y expresada como cambio respecto a una referencia; hay una laguna entre misiones en 2017–2018, por eso se analiza mes a mes.",
        "rising_words": ("a ganar agua", "a perder agua"),
    },
    "no2": {
        "name": "Dióxido de nitrógeno (NO₂)",
        "definition": "La cantidad de dióxido de nitrógeno, un contaminante del tráfico y la industria, en la columna de aire sobre el suelo.",
        "why_it_can_trend": "Los motores y centrales más limpios lo reducen; la nueva industria y el tráfico lo aumentan.",
        "caveat": "Solo se ve en días sin nubes; describe toda la columna de aire, no el aire a la altura de la calle.",
        "rising_words": ("a más contaminación por NO₂", "a menos contaminación por NO₂"),
    },
    "fire_carbon": {
        "name": "Emisiones de carbono por incendios",
        "definition": "El carbono liberado al aire al arder la vegetación, estimado a partir del área quemada vista por satélite.",
        "why_it_can_trend": "El calor, la sequía, la deforestación y la gestión del fuego cambian cuánto arde.",
        "caveat": "Los años de incendios son muy desiguales, así que las tendencias cuestan de detectar; es una estimación de modelo.",
        "rising_words": ("a más emisiones por incendios", "a menos emisiones por incendios"),
    },
    "ndvi": {
        "name": "Verdor de la vegetación (NDVI)",
        "definition": "Qué tan verde y frondosa se ve la tierra desde el espacio, de −1 a 1 (un bosque denso ronda 0,8).",
        "why_it_can_trend": "Más CO₂, temporadas más largas y el riego reverdecen la tierra; la sequía, el fuego y la tala la vuelven parda.",
        "caveat": "Más verde no siempre es más sano: los cultivos y las plantas invasoras también lo elevan.",
        "rising_words": ("al reverdecimiento", "al pardeamiento"),
    },
    "sea_level": {
        "name": "Nivel del mar",
        "definition": "La altura de la superficie del mar medida por radar desde satélites, como cambio respecto a un nivel de referencia.",
        "why_it_can_trend": "El hielo que se funde y el agua que se calienta (y se expande) elevan el mar; las corrientes lo desplazan regionalmente.",
        "caveat": "Solo mar abierto: las celdas costeras son menos fiables, y no incluye el hundimiento o la elevación del terreno.",
        "rising_words": ("a la subida del mar", "a la bajada del mar"),
    },
    "sea_surface_temp": {
        "name": "Temperatura de la superficie del mar",
        "definition": "La temperatura de la fina capa superior del mar, vista desde el espacio por infrarrojos. El "
        "mar helado queda fuera: una celda con hielo marino ese mes no tiene valor.",
        "why_it_can_trend": "Los océanos absorben la mayor parte del calor extra de los gases de efecto invernadero.",
        "caveat": "El infrarrojo necesita cielos al menos en parte despejados (la sonda de microondas ayuda a ver a "
        "través de algunas nubes), así que las zonas muy nubosas tienen menos valores; cerca del borde del hielo el "
        "área de agua abierta cambia de un año a otro; malla de 1°.",
        "rising_words": ("a mares más cálidos", "a mares más fríos"),
    },
    "land_surface_temp": {
        "name": "Temperatura de la superficie terrestre (MODIS)",
        "definition": "Qué tan caliente está el propio suelo, visto desde el espacio por infrarrojos, promediando día y noche, con mucho detalle.",
        "why_it_can_trend": "El aire más cálido, los suelos más secos, la pérdida de vegetación y las ciudades que crecen calientan la superficie.",
        "caveat": "Solo cuentan las vistas sin nubes, así que los meses nublados tienen menos observaciones.",
        "rising_words": ("al calentamiento", "al enfriamiento"),
    },
    "snow_cover": {
        "name": "Cobertura de nieve",
        "definition": "La parte del suelo cubierta de nieve en un mes, vista desde el espacio.",
        "why_it_can_trend": "Inviernos y primaveras más cálidos acortan la temporada de nieve; más precipitación invernal puede añadir nieve.",
        "caveat": "Las nubes y la noche polar ocultan el suelo; una celda sin nieve en todo el año no tiene tendencia posible.",
        "rising_words": ("a más nieve", "a menos nieve"),
    },
    "aerosols": {
        "name": "Aerosoles (bruma, polvo y humo)",
        "definition": "Cuánto oscurecen la luz del sol las partículas diminutas del aire (polvo, humo, sal marina, contaminación), como espesor óptico.",
        "why_it_can_trend": "Las leyes de aire limpio lo reducen; la nueva industria, los incendios y las tormentas de polvo lo aumentan.",
        "caveat": "Es una estimación de reanálisis guiada por observaciones de satélite; 0 es aire perfectamente limpio.",
        "rising_words": ("a un aire más turbio", "a un aire más limpio"),
    },
    "energy_budget": {
        "name": "Balance de energía de la Tierra (neto en la cima de la atmósfera)",
        "definition": "La luz solar absorbida menos el calor devuelto al espacio, por metro cuadrado: por encima de cero, el lugar gana energía.",
        "why_it_can_trend": "Los gases de efecto invernadero retienen el calor saliente; los cambios en nubes, hielo y bruma cambian cuánta luz se absorbe.",
        "caveat": "Los valores regionales incluyen el calor que entra y sale con vientos y corrientes; malla de 1°.",
        "rising_words": ("a absorber más energía", "a absorber menos energía"),
    },
    "sea_ice": {
        "name": "Concentración de hielo marino",
        "definition": "La parte de la superficie del mar cubierta de hielo, medida por sensores de microondas en satélites desde 1978.",
        "why_it_can_trend": "El aire y el agua más cálidos funden el hielo marino y acortan la temporada helada.",
        "caveat": "Los charcos de deshielo en verano parecen agua abierta; un pequeño círculo en el Polo Norte nunca se observa (aparece como sin datos).",
        "rising_words": ("a ganar hielo marino", "a perder hielo marino"),
    },
    "co2": {
        "name": "Dióxido de carbono (XCO₂)",
        "definition": "La cantidad media de dióxido de carbono en toda la columna de aire, en partes por millón.",
        "why_it_can_trend": "Quemar combustibles fósiles añade CO₂ en todas partes; las diferencias regionales vienen de las plantas, los incendios y los vientos.",
        "caveat": "Es una asimilación de modelo de las mediciones de OCO-2; sube casi en todas partes, así que las diferencias locales son pequeñas.",
        "rising_words": ("a más CO₂", "a menos CO₂"),
    },
    # ---- added 2026-11-15 ------------------------------------------------------------------
    "rainfall_long": {
        "name": "Precipitación de registro largo",
        "definition": "Toda la lluvia y la nieve (como agua) que cae en un mes, combinando satélites y pluviómetros, desde 1983.",
        "why_it_can_trend": "Una atmósfera más cálida contiene más agua, y las tormentas y los monzones pueden desplazarse. Este registro es unos 17 años más largo que el principal, así que los cambios lentos se detectan mejor.",
        "caveat": "Es más grueso (0,5°) que el registro principal y se actualiza con unos meses de retraso; la lluvia varía mucho de un año a otro.",
        "rising_words": ("a más lluvia", "a menos lluvia"),
    },
    "water_vapour": {
        "name": "Vapor de agua en el aire",
        "definition": "Todo el vapor de agua de la columna de aire sobre un lugar, en milímetros de agua si cayera todo como lluvia.",
        "why_it_can_trend": "El aire más cálido contiene alrededor de un 7 % más de vapor de agua por cada °C, así que un clima más cálido humedece el aire, y ese vapor extra alimenta aguaceros más fuertes.",
        "caveat": "Es una estimación de reanálisis guiada por mediciones de satélites y globos sonda.",
        "rising_words": ("a más vapor de agua", "a menos vapor de agua"),
    },
    "snow_water": {
        "name": "Agua en la nieve (manto de nieve)",
        "definition": "Cuánta agua guarda la nieve del suelo, en milímetros de agua derretida.",
        "why_it_can_trend": "Los inviernos más cálidos derriten antes la nieve y convierten la nieve en lluvia; más precipitación invernal puede formar un manto más grueso.",
        "caveat": "Es una estimación de un modelo de superficie con el tiempo observado; los mantos de hielo y los glaciares no se modelan como nieve, y un lugar sin nieve no tiene tendencia que medir.",
        "rising_words": ("a más agua en la nieve", "a menos agua en la nieve"),
    },
    "cloud_cover": {
        "name": "Nubosidad",
        "definition": "La parte del cielo cubierta por nubes en un mes, de día y de noche.",
        "why_it_can_trend": "El calentamiento cambia dónde se forman las nubes; el aire más limpio o más sucio y el desplazamiento de las tormentas también las cambian.",
        "caveat": "Es una estimación de reanálisis: las nubes son de lo más difícil para los modelos meteorológicos, así que las tendencias pequeñas deben tomarse con cautela.",
        "rising_words": ("a más nubes", "a menos nubes"),
    },
    "sunshine": {
        "name": "Luz solar que llega al suelo",
        "definition": "Cuánta luz del sol llega al suelo, promediando día y noche, en vatios por metro cuadrado.",
        "why_it_can_trend": "Menos nubes o un aire más limpio dejan pasar más luz (abrillantamiento); más bruma o más nubes la reducen (oscurecimiento).",
        "caveat": "Es una estimación de reanálisis que depende de sus nubes y aerosoles, no una medición directa en el suelo.",
        "rising_words": ("a más sol", "a menos sol"),
    },
    "wind_speed": {
        "name": "Velocidad del viento cerca del suelo",
        "definition": "La velocidad media del viento cerca del suelo en un mes.",
        "why_it_can_trend": "Los cambios en las trayectorias de las tormentas, el contraste entre tierra y mar y la diferencia de temperatura entre los polos y los trópicos pueden reforzar o debilitar los vientos.",
        "caveat": "Es una estimación de reanálisis; los cambios a lo largo de los años en las observaciones que usa pueden dejar pequeñas tendencias artificiales.",
        "rising_words": ("a más viento", "a menos viento"),
    },
    "ozone": {
        "name": "Capa de ozono (ozono total)",
        "definition": "Cuánto ozono hay en toda la columna de aire sobre un lugar, en unidades Dobson; casi todo está en lo alto, en la capa de ozono que frena los rayos UV dañinos.",
        "why_it_can_trend": "Los químicos que destruyen el ozono (CFC) adelgazaron la capa, sobre todo sobre la Antártida en primavera; desde su prohibición en 1987 se recupera lentamente.",
        "caveat": "Es un reanálisis que asimila mediciones de ozono por satélite. El agujero de ozono antártico aparece de septiembre a noviembre, así que conviene mirar esa estación allí.",
        "rising_words": ("a una capa de ozono más gruesa", "a una capa de ozono más delgada"),
    },
    "sea_salinity": {
        "name": "Salinidad del mar en superficie",
        "definition": "Lo salada que está la capa superior del océano, en unidades prácticas de salinidad (unos gramos de sal por kilo de agua de mar).",
        "why_it_can_trend": "La evaporación sala el agua de mar; la lluvia, los ríos y el hielo que se derrite la endulzan. Un ciclo del agua más intenso hace más saladas las zonas saladas y más dulces las dulces.",
        "caveat": "Se mide desde el espacio solo desde 2015, así que los registros son cortos; es menos fiable cerca de las costas, del hielo marino y en aguas frías.",
        "rising_words": ("a un mar más salado", "a un mar más dulce"),
    },
    "chlorophyll": {
        "name": "Clorofila del océano (fitoplancton)",
        "definition": "El pigmento verde de las diminutas plantas (fitoplancton) que flotan cerca de la superficie del océano, en miligramos por metro cúbico: una medida de la vida marina.",
        "why_it_can_trend": "El agua superficial más cálida se mezcla menos y sube menos nutrientes, lo que puede significar menos fitoplancton; los ríos, el afloramiento y el hielo que se derrite pueden alimentar más.",
        "caveat": "Las nubes, los reflejos del sol y la noche polar dejan huecos; los valores varían cien veces entre el océano abierto y las costas, y el satélite Aqua está envejeciendo.",
        "rising_words": ("a más fitoplancton", "a menos fitoplancton"),
    },
}

THEMES_ES = {
    "Heat": "Calor",
    "Water cycle": "Ciclo del agua",
    "Soil and land water": "Suelo y agua en tierra",
    "Air quality": "Calidad del aire",
    "Sky and air": "Cielo y aire",
    "Fire": "Incendios",
    "Vegetation": "Vegetación",
    "Ocean": "Océano",
}


# Articles for the Spanish headline ("La temperatura ... ha estado subiendo"); plural subjects take "han".
_ARTICLE = {
    "Temperatura": ("La", False),
    "Cambio": ("El", False),
    "Precipitación": ("La", False),
    "Intensidad": ("La", False),
    "Evapotranspiración": ("La", False),
    "Humedad": ("La", False),
    "Agua": ("El", False),
    "Dióxido": ("El", False),
    "Emisiones": ("Las", True),
    "Verdor": ("El", False),
    "Nivel": ("El", False),
    "Cobertura": ("La", False),
    "Aerosoles": ("Los", True),
    "Balance": ("El", False),
    "Concentración": ("La", False),
    "Vapor": ("El", False),
    "Nubosidad": ("La", False),
    "Luz": ("La", False),
    "Velocidad": ("La", False),
    "Capa": ("La", False),
    "Salinidad": ("La", False),
    "Clorofila": ("La", False),
}
for _v in ES.values():
    _first = _v["name"].split()[0]
    _art, _pl = _ARTICLE.get(_first, ("", False))
    _v["subject"] = f"{_art} {_v['name'][:1].lower()}{_v['name'][1:]}".strip() if _art else _v["name"]
    _v["plural"] = _pl
