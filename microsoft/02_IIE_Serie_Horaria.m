// ===========================================================================
//  IIE — SERIE HORARIA (72 h atrás / 72 h adelante)
//  Alimenta los gráficos de evolución del tablero de Power BI.
//
//  CÓMO USARLO
//    Consulta en blanco -> Editor avanzado -> pegar esto
//    Renombrar la consulta a:  IIE_SerieHoraria
//
//  Relacionar con IIE_Estado por PuntoId (1 a *).
//  La constante Porosidad debe coincidir con la de IIE_Estado.
// ===========================================================================

let
    Porosidad = 0.53,   // debe coincidir con IIE_Estado
    Zona = "America/Argentina/Buenos_Aires",

    Puntos = Table.FromRecords({
        [PuntoId = "anelo_pueblo",  Punto = "Añelo Pueblo",          Lat = -38.353, Lon = -68.783],
        [PuntoId = "acceso_meseta", Punto = "Acceso Meseta",         Lat = -38.300, Lon = -68.850],
        [PuntoId = "tratayen_sur",  Punto = "Tratayén / Sector Sur", Lat = -38.483, Lon = -68.500]
    }),

    // Cultura invariante: en una PC con regional argentina, Text.From(-38.353)
    // devuelve "-38,353" y la API rechaza la coordenada.
    NumTexto = (n as number) as text => Text.From(n, "en-US"),

    TraerSerie = (lat as number, lon as number) as table =>
        let
            Json = Json.Document(Web.Contents(
                "https://api.open-meteo.com",
                [
                    RelativePath = "v1/forecast",
                    Query = [
                        latitude      = NumTexto(lat),
                        longitude     = NumTexto(lon),
                        hourly        = "precipitation,soil_moisture_0_to_7cm,temperature_2m,wind_speed_10m",
                        past_days     = "3",
                        forecast_days = "3",
                        timezone      = Zona
                    ]
                ])),
            H = Json[hourly],

            Horas   = List.Transform(H[time], each DateTime.FromText(_, [Culture = "en-US"])),
            Precip  = List.Transform(H[precipitation], each if _ = null then 0 else _),
            Suelo   = H[soil_moisture_0_to_7cm],
            Temp    = H[temperature_2m],
            Viento  = H[wind_speed_10m],

            AhoraAR = DateTimeZone.RemoveZone(
                          DateTimeZone.SwitchZone(DateTimeZone.UtcNow(), -3)),
            Ahora   = #datetime(Date.Year(AhoraAR), Date.Month(AhoraAR),
                                Date.Day(AhoraAR), Time.Hour(AhoraAR), 0, 0),

            // Acumulado móvil de 24 h: es la variable que se compara contra los
            // umbrales de 3 y 7 mm, no la lluvia horaria suelta.
            Filas = List.Transform({0 .. List.Count(Horas) - 1}, (i) =>
                let
                    desde = List.Max({0, i - 23}),
                    n     = List.Min({24, i + 1}),
                    bruto = List.Sum(List.Range(Precip, desde, n)),
                    acum  = if bruto = null then 0 else bruto,
                    s     = Suelo{i}?,
                    sat   = if s = null then null else List.Min({100, s / Porosidad * 100})
                in
                    [
                        Hora                = Horas{i},
                        PrecipitacionMm     = Precip{i},
                        PrecipAcum24hMm     = Number.Round(acum, 2),
                        HumedadSueloM3M3    = s,
                        SaturacionSueloPct  = if sat = null then null else Number.Round(sat, 1),
                        TemperaturaC        = Temp{i}?,
                        VientoKmh           = Viento{i}?,
                        EsPronostico        = Horas{i} > Ahora
                    ])
        in
            Table.FromRecords(Filas),

    ConSerie  = Table.AddColumn(Puntos, "S", each TraerSerie([Lat], [Lon]), type table),
    SoloSerie = Table.SelectColumns(ConSerie, {"PuntoId", "Punto", "S"}),
    Expandida = Table.ExpandTableColumn(SoloSerie, "S",
        {"Hora", "PrecipitacionMm", "PrecipAcum24hMm", "HumedadSueloM3M3",
         "SaturacionSueloPct", "TemperaturaC", "VientoKmh", "EsPronostico"}),

    Tipada = Table.TransformColumnTypes(Expandida, {
        {"PuntoId", type text}, {"Punto", type text}, {"Hora", type datetime},
        {"PrecipitacionMm", type number}, {"PrecipAcum24hMm", type number},
        {"HumedadSueloM3M3", type number}, {"SaturacionSueloPct", type number},
        {"TemperaturaC", type number}, {"VientoKmh", type number},
        {"EsPronostico", type logical}
    })
in
    Tipada
