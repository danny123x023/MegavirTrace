"""Detective cases: guided investigations of real events and documented changes.

Each case is a real episode (a heatwave, a drought, a fire season, a lockdown) or a change scientists
have reported, tied to specific regions and NASA variables.  The text says only what happened in
the world and where to look.  It never states a measured result: every number a visitor sees is
computed from the stored measurements by the engine when the case is opened (cases/run.py), and
the findings are written from those numbers.

Facts in the stories are widely reported ones (dates, places, consequences); keep them that way.
Bump CASES_REV when a case changes, so stored results are recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CASES_REV = 4


@dataclass(frozen=True)
class Step:
    kind: str  # "month": one month against the same month of every year; "trend"; "compare"
    title: str  # the step's question
    look: str  # what to look at, without the answer
    variable: str
    region: dict  # {"place": id} or {"bbox": [w, s, e, n], "name": {"en": ..., "es": ...}}
    region_b: dict | None = None  # compare only
    year: int | None = None  # month only
    month: int | None = None
    mode: str | None = None  # trend/compare: annual, season, monthly (default: the variable's own)
    season: str | None = None
    start: int | None = None
    end: int | None = None
    highlight: tuple[str, ...] = ()  # series labels to mark, e.g. ("2003 JJA",)
    extreme: str = "high"  # the end of the record the event sits at: "high" or "low"


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    theme: str  # one of the catalog's themes
    kind: str  # "event" (a dated episode) or "change" (a long-term change)
    when: str
    where: str
    story: str  # what happened in the world
    question: str  # the case question
    steps: tuple[Step, ...]
    takeaway: str  # the method lesson (true whatever the numbers say)
    skills: tuple[str, ...] = field(default_factory=tuple)
    key: int = 0  # the step whose finding and chart the case card shows


def P(preset: str) -> dict:
    return {"place": f"preset:{preset}"}


PNW = {
    "bbox": [-124.5, 44, -117, 50],
    "name": {"en": "the Pacific Northwest", "es": "el noroeste del Pacífico"},
}
SINDH = {
    "bbox": [66, 24, 71, 29],
    "name": {"en": "southern Pakistan (Sindh)", "es": "el sur de Pakistán (Sind)"},
}
CAPE = {
    "bbox": [17.8, -34.8, 20.5, -32.5],
    "name": {"en": "the Cape Town region", "es": "la región de Ciudad del Cabo"},
}

CASES: tuple[Case, ...] = (
    # ---- Heat ------------------------------------------------------------------------------
    Case(
        id="europe-heatwave-2003",
        title="Europe's 2003 heatwave: bad luck, or a warming baseline?",
        theme="Heat",
        kind="event",
        when="August 2003",
        where="Western Europe",
        story=(
            "In the first half of August 2003 a heatwave settled over western Europe. It was linked to tens of "
            "thousands of extra deaths, around 15,000 in France alone, many of them older people in homes that "
            "never cooled down at night."
        ),
        question="Was 2003 a freak summer, or the shape of summers to come?",
        steps=(
            Step(
                "month",
                "How unusual was August 2003?",
                "Each point is one August since 1980. A freak month stands alone far above the rest.",
                "daily_high",
                P("western_europe_heat"),
                year=2003,
                month=8,
            ),
            Step(
                "trend",
                "Are summer afternoons getting hotter?",
                "Look at the summer (June to August) average of the daily highs, year by year, and where 2003 now ranks.",
                "daily_high",
                P("western_europe_heat"),
                mode="season",
                season="JJA",
                highlight=("2003 JJA",),
            ),
            Step(
                "trend",
                "And the nights?",
                "Hot nights stop the body from recovering. Do the summer nightly lows move the same way?",
                "nightly_low",
                P("western_europe_heat"),
                mode="season",
                season="JJA",
                highlight=("2003 JJA",),
            ),
        ),
        takeaway=(
            "One extreme month and a long-term trend answer different questions: the first asks how unusual, "
            "the second whether the baseline is moving. When the baseline rises, a summer that was once "
            "extreme becomes ordinary."
        ),
        skills=("unusual months", "seasons", "extreme vs trend"),
    ),
    Case(
        id="russia-heatwave-2010",
        title="Russia's 2010 heatwave and the smoke over Moscow",
        theme="Heat",
        kind="event",
        when="July–August 2010",
        where="Moscow and western Russia",
        story=(
            "In July 2010 Moscow recorded its highest temperature on record. Peat and forest fires around the "
            "city filled it with smoke in early August, and Russia stopped exporting wheat after drought "
            "ruined much of the harvest."
        ),
        question="How extreme was the heat, how far did it reach, and what did the smoke do to the air?",
        steps=(
            Step(
                "month",
                "How hot was July 2010 around Moscow?",
                "Each point is one July since 1980 in the Moscow region.",
                "air_temp",
                P("moscow"),
                year=2010,
                month=7,
            ),
            Step(
                "month",
                "Was all of eastern Europe as extreme?",
                "The same July and the same measure over a region about 270 times larger. Big regions average out local extremes.",
                "air_temp",
                P("eastern_europe"),
                year=2010,
                month=7,
            ),
            Step(
                "month",
                "Did the smoke show up from space?",
                "Aerosols are tiny particles in the air (dust, smoke, pollution) that dim the sunlight. Compare August 2010 with every other August.",
                "aerosols",
                P("moscow"),
                year=2010,
                month=8,
            ),
            Step(
                "trend",
                "Is there a warming trend behind it?",
                "Summer air temperature around Moscow since 1980, with 2010 marked.",
                "air_temp",
                P("moscow"),
                mode="season",
                season="JJA",
                highlight=("2010 JJA",),
            ),
        ),
        takeaway=(
            "Extremes are local: the same heatwave looks less extreme when averaged over a bigger area. "
            "Choosing the region is part of the question."
        ),
        skills=("unusual months", "region size", "air quality"),
    ),
    Case(
        id="pacific-northwest-heat-dome-2021",
        title="The 2021 heat dome over the Pacific Northwest",
        theme="Heat",
        kind="event",
        when="Late June 2021",
        where="Oregon, Washington and British Columbia",
        story=(
            "At the end of June 2021 a 'heat dome' of high pressure sat over the Pacific Northwest, a region known "
            "for mild summers. Lytton in British Columbia reached 49.6 °C on 29 June, a Canadian record, and burned "
            "in a wildfire the next day. Hundreds of people died in the heat."
        ),
        question="Was June 2021 off the charts, and is the region's summer warming?",
        steps=(
            Step(
                "month",
                "How hot were June 2021's afternoons?",
                "Monthly averages of the daily highs: a few days of extreme heat must be strong to move a whole month.",
                "daily_high",
                PNW,
                year=2021,
                month=6,
            ),
            Step(
                "month",
                "Did the nights stay hot too?",
                "The same June, now the daily lows.",
                "nightly_low",
                PNW,
                year=2021,
                month=6,
            ),
            Step(
                "trend",
                "Is summer warming here?",
                "Summer daily highs since 1980, with 2021 marked.",
                "daily_high",
                PNW,
                mode="season",
                season="JJA",
                highlight=("2021 JJA",),
            ),
        ),
        takeaway=(
            "A monthly average hides single days, so a month that stands out was carried by days that were far "
            "beyond normal. Warming shifts the whole distribution, making such months more likely."
        ),
        skills=("unusual months", "days and nights", "trend"),
    ),
    Case(
        id="arctic-amplification",
        title="Is the Arctic warming faster than the rest of the planet?",
        theme="Heat",
        kind="change",
        when="Since 1980",
        where="The Arctic and the whole Earth",
        story=(
            "Scientists have long expected the Arctic to warm faster than the planet as a whole: as snow and sea "
            "ice melt, darker ground and open ocean absorb more sunlight, and the shallow, stable Arctic air keeps "
            "the extra warmth near the surface. The idea is called Arctic amplification."
        ),
        question="Do NASA's thermometer records show the Arctic pulling ahead, and by how much?",
        steps=(
            Step(
                "trend",
                "How fast is the whole Earth warming?",
                "NASA GISTEMP surface temperature change for the whole globe since 1980.",
                "temp_change",
                P("globe"),
                start=1980,
            ),
            Step(
                "trend",
                "And the Arctic?",
                "The same record north of the Arctic Circle (66.5°N).",
                "temp_change",
                P("arctic"),
                start=1980,
            ),
            Step(
                "compare",
                "Is the difference real?",
                "Two trends can differ by chance. This tests the trend of the difference between the two series.",
                "temp_change",
                P("arctic"),
                region_b=P("globe"),
                start=1980,
            ),
        ),
        takeaway=(
            "To say two places change at different speeds, test the difference directly: two separate "
            "'significant' trends do not prove they differ."
        ),
        skills=("comparing regions", "long records"),
        key=2,
    ),
    Case(
        id="earth-energy-imbalance",
        title="Is Earth taking in more energy than it gives back?",
        theme="Heat",
        kind="change",
        when="Since 2000",
        where="The whole Earth",
        story=(
            "Since 2000 NASA's CERES instruments have measured the sunlight Earth absorbs and the heat it sends "
            "back to space. A 2021 NASA and NOAA study found that the gap between the two, the energy the planet "
            "keeps, roughly doubled between 2005 and 2019."
        ),
        question="Is the planet's energy gain growing, and where does the heat show up?",
        steps=(
            Step(
                "trend",
                "Is the energy kept by the planet growing?",
                "Net energy at the top of the atmosphere: incoming sunlight minus what goes back out. For the whole Earth, above zero means the planet gains heat.",
                "energy_budget",
                P("globe"),
            ),
            Step(
                "trend",
                "Is the ocean surface warming?",
                "More than 90% of the extra heat goes into the oceans. Global sea surface temperature from NASA's AIRS satellite instrument.",
                "sea_surface_temp",
                P("globe"),
            ),
            Step(
                "trend",
                "And the air we live in?",
                "Global surface temperature change over the same decades.",
                "temp_change",
                P("globe"),
                start=2000,
            ),
        ),
        takeaway=(
            "Different records can be checked against each other: the energy the planet keeps, the sea surface and "
            "the air. When independent measurements point the same way the picture is more convincing, but trends "
            "alone do not show what caused them."
        ),
        skills=("linking variables", "satellite records"),
    ),
    # ---- Ocean -------------------------------------------------------------------------------
    Case(
        id="arctic-sea-ice-2012",
        title="Arctic sea ice: the record low of September 2012",
        theme="Ocean",
        kind="event",
        when="September 2012",
        where="The Arctic Ocean",
        story=(
            "On 16 September 2012 Arctic sea ice shrank to the smallest extent in the satellite record that began in "
            "1979: about 3.4 million square kilometres of ocean had at least 15% ice cover. A strong August storm "
            "broke up ice that was already thin."
        ),
        question="Was 2012 a one-off, or part of a long decline?",
        steps=(
            Step(
                "month",
                "How low was September 2012?",
                "September is when the ice is at its smallest. Each point is one September since 1979.",
                "sea_ice",
                P("arctic"),
                year=2012,
                month=9,
            ),
            Step(
                "trend",
                "Is autumn ice declining?",
                "Ice concentration from September to November, year by year, with 2012 marked.",
                "sea_ice",
                P("arctic"),
                mode="season",
                season="SON",
                highlight=("2012 SON",),
                extreme="low",
            ),
            Step(
                "trend",
                "Is the Arctic air warming?",
                "Yearly air temperature north of the Arctic Circle since 1980.",
                "air_temp",
                P("arctic"),
            ),
        ),
        takeaway=(
            "A record year combines a long decline with the weather of that year. The trend says where the "
            "baseline is heading; a storm or a warm summer decides which year sets the record."
        ),
        skills=("unusual months", "seasons", "linking variables"),
    ),
    Case(
        id="el-nino-2015",
        title="The 2015–16 El Niño: one ocean, worldwide effects",
        theme="Ocean",
        kind="event",
        when="2015–2016",
        where="The tropical Pacific, Indonesia and the whole Earth",
        story=(
            "In late 2015 the central Pacific warmed into one of the strongest El Niño events on record. Drought in "
            "Indonesia let fires spread through drained peatlands from September, covering South-East Asia in "
            "haze, and 2016 became the warmest year on record at the time."
        ),
        question="Can one warm patch of ocean be traced in records on the other side of the world?",
        steps=(
            Step(
                "month",
                "How warm was the central Pacific?",
                "Sea surface temperature in the Niño 3.4 region, the box used to measure El Niño. Each point is one December.",
                "sea_surface_temp",
                P("nino34"),
                year=2015,
                month=12,
            ),
            Step(
                "month",
                "Did Indonesia burn more than usual?",
                "Carbon released by fires on Sumatra in September, year by year.",
                "fire_carbon",
                P("sumatra"),
                year=2015,
                month=9,
            ),
            Step(
                "trend",
                "Where does 2016 sit in the global record?",
                "Yearly global surface temperature change since 1980, with 2016 marked.",
                "temp_change",
                P("globe"),
                start=1980,
                highlight=("2016",),
            ),
        ),
        takeaway=(
            "Natural swings like El Niño add to the long-term trend for a year or two: a record set in an El Niño "
            "year is the trend plus the swing. Because the trend keeps rising, later years can beat it even without "
            "a strong El Niño."
        ),
        skills=("natural cycles", "unusual months", "trend vs swings"),
    ),
    # ---- Water cycle --------------------------------------------------------------------------
    Case(
        id="pakistan-floods-2022",
        title="Pakistan's 2022 monsoon floods",
        theme="Water cycle",
        kind="event",
        when="June–September 2022",
        where="Southern Pakistan (Sindh)",
        story=(
            "Monsoon rains from June to September 2022 left about a third of Pakistan under water. Some 33 million "
            "people were affected, and the southern province of Sindh was among the worst hit."
        ),
        question="How far beyond normal was the rain, and are downpours getting stronger?",
        steps=(
            Step(
                "month",
                "How much rain fell in August 2022?",
                "Monthly rainfall from NASA's IMERG satellite record. Each point is one August since 2000.",
                "rainfall",
                SINDH,
                year=2022,
                month=8,
            ),
            Step(
                "month",
                "How intense were the downpours?",
                "Downpour intensity: the heaviest hour of rain in each day, averaged over the month, from NASA's MERRA-2 record since 1980.",
                "downpour",
                SINDH,
                year=2022,
                month=8,
            ),
            Step(
                "trend",
                "Are monsoon downpours getting stronger?",
                "Downpour intensity in June to August, year by year, with 2022 marked.",
                "downpour",
                SINDH,
                mode="season",
                season="JJA",
                highlight=("2022 JJA",),
            ),
            Step(
                "trend",
                "And total monsoon rain?",
                "Total June to August rainfall since 2000. Fewer years and big swings make a trend harder to prove.",
                "rainfall",
                SINDH,
                mode="season",
                season="JJA",
                highlight=("2022 JJA",),
            ),
        ),
        takeaway=(
            "Rain can come in heavier bursts even when the season's total has no clear trend: how rain falls "
            "and how much falls are different questions."
        ),
        skills=("unusual months", "seasons", "noisy data"),
    ),
    Case(
        id="cape-town-day-zero",
        title="Cape Town's 'Day Zero' drought",
        theme="Water cycle",
        kind="event",
        when="2015–2018",
        where="The Cape Town region, South Africa",
        story=(
            "After three dry winters from 2015 to 2017, Cape Town's reservoirs fell so low that the city planned "
            "for 'Day Zero', when household taps would be turned off. Strict limits of 50 litres a person a day and "
            "the rains of winter 2018 pushed it back."
        ),
        question="How dry were those years, and is the region drying out?",
        steps=(
            Step(
                "trend",
                "How dry were 2015 to 2017?",
                "Yearly rainfall since 2001, with the drought years marked.",
                "rainfall",
                CAPE,
                mode="annual",
                highlight=("2015", "2016", "2017"),
                extreme="low",
            ),
            Step(
                "trend",
                "Did the winter rains fail?",
                "Cape Town gets most of its rain in winter, June to August.",
                "rainfall",
                CAPE,
                mode="season",
                season="JJA",
                highlight=("2017 JJA",),
                extreme="low",
            ),
            Step(
                "trend",
                "Did the soil dry out too?",
                "Topsoil moisture from NASA's GLDAS land model, year by year.",
                "topsoil_moisture",
                CAPE,
                highlight=("2017",),
                extreme="low",
            ),
        ),
        takeaway=(
            "A severe drought does not need a long-term trend: a run of dry years can empty reservoirs built for "
            "average conditions. Short records with large swings need strong changes before a trend can be proven."
        ),
        skills=("droughts", "seasons", "short records"),
    ),
    Case(
        id="horn-of-africa-drought",
        title="Five failed rainy seasons in the Horn of Africa",
        theme="Water cycle",
        kind="event",
        when="Late 2020 – late 2022",
        where="Ethiopia, Kenya and Somalia",
        story=(
            "From late 2020 to late 2022, five rainy seasons in a row failed across the Horn of Africa, the region's "
            "worst drought in at least 40 years. Millions of livestock died and millions of people faced hunger."
        ),
        question="Do the satellite records show the drought, in the rain, the soil and the plants?",
        steps=(
            Step(
                "trend",
                "How dry were 2021 and 2022?",
                "Yearly rainfall over the Horn of Africa since 2001.",
                "rainfall",
                P("horn_of_africa"),
                mode="annual",
                highlight=("2021", "2022"),
                extreme="low",
            ),
            Step(
                "trend",
                "Is the topsoil drying?",
                "Topsoil moisture from NASA's GLDAS land model since 2000.",
                "topsoil_moisture",
                P("horn_of_africa"),
                highlight=("2021", "2022"),
                extreme="low",
            ),
            Step(
                "trend",
                "Did the land turn brown?",
                "Vegetation greenness (NDVI) from NASA's MODIS satellites.",
                "ndvi",
                P("horn_of_africa"),
                highlight=("2022",),
                extreme="low",
            ),
        ),
        takeaway=(
            "Rain, soil water and plant greenness respond on different time scales. Following one event through "
            "several records shows how a drought spreads from the sky to the ground to the plants."
        ),
        skills=("droughts", "linking variables"),
    ),
    Case(
        id="amazon-drought-2023",
        title="The Amazon's drought of 2023–24",
        theme="Water cycle",
        kind="event",
        when="2023–2024",
        where="The Amazon Basin",
        story=(
            "In October 2023 the Rio Negro at Manaus fell to its lowest level since records began in 1902, stranding "
            "river communities. El Niño was developing in the Pacific. Drought returned in 2024, and fires spread "
            "across the basin."
        ),
        question="How dry was the rainforest, what was the Pacific doing, and did fire follow?",
        steps=(
            Step(
                "month",
                "How dry was October 2023?",
                "Rainfall over the whole Amazon Basin. Each point is one October since 2000.",
                "rainfall",
                P("amazon_basin"),
                year=2023,
                month=10,
            ),
            Step(
                "month",
                "Was El Niño building?",
                "Sea surface temperature in the Niño 3.4 region of the central Pacific in October.",
                "sea_surface_temp",
                P("nino34"),
                year=2023,
                month=10,
            ),
            Step(
                "month",
                "Did fire follow in 2024?",
                "Carbon released by fires in the Amazon Basin in September, the height of the fire season.",
                "fire_carbon",
                P("amazon_basin"),
                year=2024,
                month=9,
            ),
        ),
        takeaway=(
            "Records that line up in time are consistent with a link: El Niño often brings drought to the Amazon, and "
            "dry forest burns more easily the next year. Timing alone does not prove a cause, though: a 2024 "
            "attribution study found that climate change, more than El Niño, drove the 2023 drought."
        ),
        skills=("droughts", "natural cycles", "fire"),
    ),
    # ---- Soil and land water --------------------------------------------------------------------
    Case(
        id="us-corn-belt-drought-2012",
        title="The 2012 US Corn Belt drought",
        theme="Soil and land water",
        kind="event",
        when="Summer 2012",
        where="The US Corn Belt",
        story=(
            "In 2012 the worst US drought since the 1950s hit the Midwest. July 2012 was then the hottest month on "
            "record for the contiguous United States, the corn harvest fell sharply and grain prices hit records."
        ),
        question="How did heat, soil and crops react in July 2012, and is the region drying?",
        steps=(
            Step(
                "month",
                "How hot were July's afternoons?",
                "Monthly average of the daily highs. Each point is one July since 1980.",
                "daily_high",
                P("us_corn_belt"),
                year=2012,
                month=7,
            ),
            Step(
                "month",
                "How dry was the topsoil?",
                "Topsoil moisture (top 10 cm) from NASA's GLDAS land model, each July since 2000.",
                "topsoil_moisture",
                P("us_corn_belt"),
                year=2012,
                month=7,
            ),
            Step(
                "month",
                "Did the crops show it from space?",
                "Vegetation greenness (NDVI) from NASA's MODIS satellites in July, when corn should be greenest.",
                "ndvi",
                P("us_corn_belt"),
                year=2012,
                month=7,
            ),
            Step(
                "trend",
                "Is summer soil drying over the years?",
                "Summer topsoil moisture since 2000, with 2012 marked.",
                "topsoil_moisture",
                P("us_corn_belt"),
                mode="season",
                season="JJA",
                highlight=("2012 JJA",),
                extreme="low",
            ),
        ),
        takeaway=(
            "Heat, dry soil and stressed crops feed each other in a 'flash drought'. One extreme summer is an "
            "event; only many years can show a trend."
        ),
        skills=("unusual months", "linking variables", "extreme vs trend"),
    ),
    Case(
        id="india-groundwater",
        title="Northwest India's disappearing groundwater",
        theme="Soil and land water",
        kind="change",
        when="Since 2002",
        where="Punjab, Haryana and Rajasthan",
        story=(
            "In 2009 NASA scientists used the GRACE satellites, which weigh the water on and under the land, to "
            "show that groundwater beneath northwest India was being pumped for irrigation faster than rain could "
            "refill it."
        ),
        question="Is the water still falling, and is less rain to blame?",
        steps=(
            Step(
                "trend",
                "Is the water under the land still falling?",
                "Water stored on land (soil, rivers and groundwater together) from GRACE; the chart shows months, the test yearly means.",
                "land_water",
                P("northwest_india_aquifer"),
            ),
            Step(
                "trend",
                "Is it raining less?",
                "Yearly rainfall over the same region since 2001.",
                "rainfall",
                P("northwest_india_aquifer"),
            ),
            Step(
                "trend",
                "What would the weather alone do?",
                "Soil water in NASA's GLDAS land model, which follows rain and sunshine but has no wells or irrigation. "
                "The 2009 study used it the same way: what GRACE sees beyond the model points to groundwater.",
                "soil_moisture",
                P("northwest_india_aquifer"),
            ),
            Step(
                "trend",
                "Are the fields greener?",
                "Vegetation greenness (NDVI) seen by MODIS. Fields watered from wells can stay green when the rain fails, so greenness alone cannot show where the water comes from.",
                "ndvi",
                P("northwest_india_aquifer"),
            ),
        ),
        takeaway=(
            "If the water stored on land falls while the rain and the weather-driven model do not, the change is not "
            "coming from the sky; the 2009 study traced it to pumping for irrigation. GRACE weighs all the water "
            "together, so it cannot show the pumping itself, but ruling out a suspect is as useful as finding one."
        ),
        skills=("linking variables", "ruling out causes", "GRACE"),
    ),
    Case(
        id="california-central-valley",
        title="California's Central Valley: drought, pumping and a wet year",
        theme="Soil and land water",
        kind="change",
        when="2002–2026",
        where="The California Central Valley",
        story=(
            "California's Central Valley grows a large share of America's fruit and vegetables. In the droughts of "
            "2012–2016 and 2020–2022 farms pumped more groundwater to replace missing river water, and the ground "
            "sank in places. Storms in the winter of 2022–23 brought floods and refilled reservoirs."
        ),
        question="Is the valley losing water, and how much did one wet winter put back?",
        steps=(
            Step(
                "trend",
                "Is the valley losing water?",
                "Water stored on land, including groundwater, from GRACE, month by month since 2002.",
                "land_water",
                P("california_central_valley"),
            ),
            Step(
                "month",
                "How low was it in spring 2022?",
                "April, after the wet season, compared with every other April.",
                "land_water",
                P("california_central_valley"),
                year=2022,
                month=4,
            ),
            Step(
                "month",
                "What did the wet winter of 2022–23 put back?",
                "The same April one year later.",
                "land_water",
                P("california_central_valley"),
                year=2023,
                month=4,
            ),
        ),
        takeaway=(
            "One wet year can refill the surface, but a long decline in stored water means more is taken out "
            "than comes back over the years."
        ),
        skills=("GRACE", "unusual months", "extreme vs trend"),
    ),
    Case(
        id="lake-chad",
        title="Is Lake Chad still shrinking?",
        theme="Soil and land water",
        kind="change",
        when="Since 2002",
        where="Lake Chad, Africa",
        story=(
            "Lake Chad shrank by about 90% between the 1960s and the 1980s, after years of drought in the Sahel. It "
            "became a widely used symbol of a disappearing lake."
        ),
        question="What do the satellite records since 2000 say about the lake's water today?",
        steps=(
            Step(
                "trend",
                "Is the water around the lake still falling?",
                "Water stored on land (soil, rivers and groundwater together) from GRACE; the chart shows months, the test yearly means.",
                "land_water",
                P("lake_chad"),
            ),
            Step(
                "trend",
                "What is the rain doing?",
                "Yearly rainfall over the lake region since 2001.",
                "rainfall",
                P("lake_chad"),
            ),
            Step(
                "trend",
                "And the plants?",
                "Vegetation greenness (NDVI) from MODIS.",
                "ndvi",
                P("lake_chad"),
            ),
        ),
        takeaway="Check whether a famous story still holds with today's data: the past change and the present trend can differ.",
        skills=("checking a story", "GRACE", "linking variables"),
    ),
    Case(
        id="alps-snow",
        title="Is snow leaving the Alps earlier in spring?",
        theme="Soil and land water",
        kind="change",
        when="Since 2000",
        where="The European Alps",
        story=(
            "Ski resorts in the Alps report shorter seasons, and a 2023 tree-ring study suggested the Alpine snow "
            "season is now shorter than at any time in the past 600 years."
        ),
        question="Is the snow cover changing, and in which season?",
        steps=(
            Step(
                "trend",
                "Is winter snow cover changing?",
                "Snow cover from NASA's MODIS satellites, December to February.",
                "snow_cover",
                P("alps"),
                mode="season",
                season="DJF",
            ),
            Step(
                "trend",
                "And in spring?",
                "The same record for March to May, when snow melts.",
                "snow_cover",
                P("alps"),
                mode="season",
                season="MAM",
            ),
            Step(
                "trend",
                "Are spring days warmer?",
                "Spring daily highs since 1980.",
                "daily_high",
                P("alps"),
                mode="season",
                season="MAM",
            ),
        ),
        takeaway="A change can hide in one season: an average over the whole year, or the wrong season, can miss it.",
        skills=("seasons", "linking variables"),
    ),
    # ---- Fire ---------------------------------------------------------------------------------
    Case(
        id="australia-black-summer",
        title="Australia's Black Summer (2019–20)",
        theme="Fire",
        kind="event",
        when="September 2019 – March 2020",
        where="South-eastern Australia",
        story=(
            "2019 was Australia's hottest and driest year on record. From September 2019 to March 2020 bushfires "
            "burned more than 18 million hectares, most of them in the south-east, and smoke reached South America."
        ),
        question="Dry soil, heat, then fire: can the records show the chain, and is fire trending up?",
        steps=(
            Step(
                "month",
                "How dry was the topsoil in December 2019?",
                "Topsoil moisture from NASA's GLDAS land model. Each point is one December.",
                "topsoil_moisture",
                P("southeast_australia"),
                year=2019,
                month=12,
            ),
            Step(
                "month",
                "How hot were the afternoons?",
                "December daily highs since 1980.",
                "daily_high",
                P("southeast_australia"),
                year=2019,
                month=12,
            ),
            Step(
                "month",
                "How much burned?",
                "Carbon released by fires (NASA MiCASA), each December since 2001.",
                "fire_carbon",
                P("southeast_australia"),
                year=2019,
                month=12,
            ),
            Step(
                "trend",
                "Is fire trending up?",
                "Yearly fire carbon since 2001, with 2019 marked.",
                "fire_carbon",
                P("southeast_australia"),
                highlight=("2019",),
            ),
        ),
        takeaway=(
            "Fire records are dominated by a few huge years, which makes trends hard to prove even when extremes "
            "are rising. 'No clear trend' is not the same as 'nothing is changing'."
        ),
        skills=("unusual months", "linking variables", "noisy data"),
        key=2,
    ),
    Case(
        id="canada-fires-2023",
        title="Canada's 2023 fire season and the smoke over New York",
        theme="Fire",
        kind="event",
        when="Summer 2023",
        where="Boreal Canada and the US Northeast",
        story=(
            "In 2023 Canada had its largest fire season on record, with more than 15 million hectares burned. On 7 "
            "June smoke from fires in Quebec turned the sky over New York orange and gave the city some of the "
            "worst air in the world that day."
        ),
        question="How big was the season, is it part of a trend, and did the smoke really reach the US?",
        steps=(
            Step(
                "month",
                "How much burned in June 2023?",
                "Carbon released by fires across boreal Canada, each June since 2001.",
                "fire_carbon",
                P("boreal_canada"),
                year=2023,
                month=6,
            ),
            Step(
                "trend",
                "Is it part of a trend?",
                "Yearly fire carbon since 2001, with 2023 marked.",
                "fire_carbon",
                P("boreal_canada"),
                highlight=("2023",),
            ),
            Step(
                "month",
                "Did the smoke reach the US Northeast?",
                "Aerosols (tiny particles of dust, smoke and pollution) over the corridor from Washington to Boston, each June since 1980.",
                "aerosols",
                P("us_northeast_corridor"),
                year=2023,
                month=6,
            ),
        ),
        takeaway="Smoke travels: an event in one country can be the most unusual month on record in another.",
        skills=("unusual months", "extreme vs trend", "air quality"),
    ),
    # ---- Air quality ----------------------------------------------------------------------------
    Case(
        id="lockdown-air-2020",
        title="Lockdown 2020: did the air really clear?",
        theme="Air quality",
        kind="event",
        when="February–April 2020",
        where="China, Italy, India and the US",
        story=(
            "When COVID-19 lockdowns began, traffic and factories stopped: much of China from late January 2020, "
            "northern Italy from March, India from 25 March. Nitrogen dioxide, a gas from burning fuel, is "
            "measured every day from space by NASA's OMI instrument."
        ),
        question="Do the satellite records show the lockdowns, and how does a dip compare with a trend?",
        steps=(
            Step(
                "month",
                "North China Plain, February 2020",
                "NO₂ in February, year by year since 2005.",
                "no2",
                P("north_china_plain"),
                year=2020,
                month=2,
            ),
            Step(
                "month",
                "Northern Italy, April 2020",
                "NO₂ over the Po Valley in April.",
                "no2",
                P("po_valley"),
                year=2020,
                month=4,
            ),
            Step(
                "month",
                "Delhi, April 2020",
                "NO₂ over the Delhi region in April.",
                "no2",
                P("delhi"),
                year=2020,
                month=4,
            ),
            Step(
                "trend",
                "The slow change: the US Northeast since 2004",
                "Monthly NO₂ with the seasonal cycle removed. Cleaner engines and power plants act over years, not weeks.",
                "no2",
                P("us_northeast_corridor"),
                mode="monthly",
            ),
        ),
        takeaway=(
            "A sudden dip shows how much pollution comes from what we do day to day; a long trend shows what "
            "lasting changes, like cleaner engines, achieve."
        ),
        skills=("unusual months", "comparing regions", "a dip is not a trend"),
        key=2,
    ),
    # ---- Vegetation -----------------------------------------------------------------------------
    Case(
        id="loess-plateau-greening",
        title="China's Loess Plateau: from dust to green",
        theme="Vegetation",
        kind="change",
        when="Since 2000",
        where="The Loess Plateau, China",
        story=(
            "Since 1999 China's 'Grain for Green' programme has turned steep farmland on the Loess Plateau into "
            "forest and grassland to stop erosion. NASA satellite studies have found China among the countries "
            "greening fastest."
        ),
        question="Is the plateau greener, and could more rain explain it?",
        steps=(
            Step(
                "trend",
                "Is the plateau greener?",
                "Vegetation greenness (NDVI) from NASA's MODIS satellites since 2000.",
                "ndvi",
                P("china_loess_plateau"),
            ),
            Step(
                "trend",
                "Has it rained more?",
                "Yearly rainfall over the plateau from NASA's GPM IMERG since 2001. More rain alone can green a dry land.",
                "rainfall",
                P("china_loess_plateau"),
            ),
            Step(
                "compare",
                "Greener than the Sahel?",
                "The Sahel has re-greened since its 1970s–80s droughts, largely as the rains returned, helped by farmers protecting trees. Compare the two trends directly.",
                "ndvi",
                P("china_loess_plateau"),
                region_b=P("sahel"),
            ),
        ),
        takeaway=(
            "Greening can come from people (planting) or from nature (more rain). Checking the rain in the same place "
            "is a first test, and another greening region shows how unusual the change is; no region is a true "
            "control, so the satellite trend alone cannot prove the cause."
        ),
        skills=("causes", "comparing regions", "linking variables"),
    ),
)

BY_ID = {c.id: c for c in CASES}
