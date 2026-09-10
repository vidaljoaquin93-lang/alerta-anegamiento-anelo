// ===========================================================================
//  IIE — ESTADO ACTUAL POR PUNTO CRÍTICO
//  Sistema de Alerta Temprana de Anegamiento — Añelo, Vaca Muerta
//
//  Consulta Power Query (lenguaje M). No requiere Python, GitHub ni permisos
//  de IT: solo Power BI Desktop y la API de Open-Meteo (ya validada por IT).
//
//  CÓMO USARLO
//    1. Power BI Desktop -> Inicio -> Obtener datos -> Consulta en blanco
//    2. Panel izquierdo -> clic derecho en la consulta -> Editor avanzado
//    3. Borrar todo y pegar ESTE archivo completo
//    4. Renombrar la consulta a:  IIE_Estado
//    5. Cerrar y aplicar
//
//  ANTES DE EMPEZAR — dos ajustes obligatorios
//    a) Archivo -> Opciones -> Archivo actual -> Privacidad ->
//       "Omitir siempre la configuración de niveles de privacidad".
//       Sin esto Power BI corta la consulta con un error de Formula.Firewall.
//    b) Al pedir credenciales para api.open-meteo.com: Anónimo / Público.
//
//  DEVUELVE una fila por punto crítico con el semáforo ya calculado.
// ===========================================================================

let
    // ---------------------------------------------------------------- //
    // PARÁMETROS — es lo único que se toca para recalibrar
    // ---------------------------------------------------------------- //

    // Porosidad total del suelo (m³/m³). Convierte los m³/m³ que devuelve
    // Open-Meteo a % de saturación. Calibrado contra 3 años de ERA5:
    //   0,45 -> ~27 días/año en rojo   |   0,53 -> ~16 días/año en rojo
    Porosidad = 0.53,

    // Umbrales de la matriz de riesgo
    PrecipAmarillo = 3,      // mm
    PrecipRojo     = 7,      // mm
    SatAmarillo    = 60,     // % de saturación
    SatRojo        = 75,     // % de saturación

    Zona = "America/Argentina/Buenos_Aires",

    // ---------------------------------------------------------------- //
    // PUNTOS CRÍTICOS
    // ---------------------------------------------------------------- //
    Puntos = Table.FromRecords({
        [PuntoId = "anelo_pueblo", Punto = "Añelo Pueblo",
         Descripcion = "Base operativa",                     Lat = -38.353, Lon = -68.783],
        [PuntoId = "acceso_meseta", Punto = "Acceso Meseta",
         Descripcion = "Ruta Prov. 17 / Bajada del Chañar",  Lat = -38.300, Lon = -68.850],
        [PuntoId = "tratayen_sur", Punto = "Tratayén / Sector Sur",
         Descripcion = "Acceso sur a yacimiento",            Lat = -38.483, Lon = -68.500]
    }),

    // ---------------------------------------------------------------- //
    // LLAMADA A OPEN-METEO
    // ---------------------------------------------------------------- //
    // IMPORTANTE: Text.From con cultura "en-US" es obligatorio. En una PC con
    // configuración regional argentina, Text.From(-38.353) devuelve "-38,353"
    // con coma decimal y la API rechaza la coordenada.
    NumTexto = (n as number) as text => Text.From(n, "en-US"),

    TraerClima = (lat as number, lon as number) as record =>
        let
            Cruda = Web.Contents(
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
                ]
            )
        in
            Json.Document(Cruda),

    // ---------------------------------------------------------------- //
    // CÁLCULO POR PUNTO
    // ---------------------------------------------------------------- //
    Calcular = (lat as number, lon as number) as record =>
        let
            Datos   = TraerClima(lat, lon),
            Horaria = Datos[hourly],

            // Cultura invariante también al parsear las marcas de tiempo ISO.
            Horas   = List.Transform(Horaria[time],
                          each DateTime.FromText(_, [Culture = "en-US"])),
            Precip  = List.Transform(Horaria[precipitation],
                          each if _ = null then 0 else _),
            Suelo   = Horaria[soil_moisture_0_to_7cm],
            Temp    = Horaria[temperature_2m],
            Viento  = Horaria[wind_speed_10m],

            // Hora local Argentina (UTC-3), truncada a la hora en punto
            AhoraAR = DateTimeZone.RemoveZone(
                          DateTimeZone.SwitchZone(DateTimeZone.UtcNow(), -3)),
            Ahora   = #datetime(Date.Year(AhoraAR), Date.Month(AhoraAR),
                                Date.Day(AhoraAR), Time.Hour(AhoraAR), 0, 0),

            // Índice de la hora actual dentro de la serie.
            // Fallback posicional: la serie arranca a las 00:00 del primer día
            // pasado, así que el índice de hoy 00:00 es past_days * 24 = 72, y
            // la hora actual está en 72 + hora. Verificado contra la API.
            IdxActual = List.PositionOf(Horas, Ahora),
            IdxFallback = 72 + Time.Hour(AhoraAR),
            Idx = if IdxActual = -1 then IdxFallback else IdxActual,

            // --- Ventanas de precipitación ---
            // Suma segura: si la ventana queda vacía devuelve 0, nunca null.
            Suma = (lista as list, desde as number, cuantos as number) as number =>
                let
                    n = List.Max({0, List.Min({cuantos, List.Count(lista) - desde})}),
                    s = if n <= 0 then 0 else List.Sum(List.Range(lista, desde, n))
                in
                    if s = null then 0 else s,

            // Acumulado de las últimas 24 h (observado)
            Acum24 = Suma(Precip, List.Max({0, Idx - 23}), 24),
            // Pronóstico de las próximas 24 h y 72 h
            Pron24 = Suma(Precip, Idx + 1, 24),
            Pron72 = Suma(Precip, Idx + 1, 72),

            // Lluvia de referencia: criterio conservador
            PrecipRef = List.Max({Acum24, Pron24}),

            // --- Humedad de suelo ---
            SueloActual = Suelo{Idx}?,
            SatPct = if SueloActual = null then null
                     else List.Min({100, SueloActual / Porosidad * 100}),

            // --- Matriz de riesgo (semáforo) ---
            NivelPrecip =
                if PrecipRef > PrecipRojo then 2
                else if PrecipRef >= PrecipAmarillo then 1
                else 0,
            NivelSuelo =
                if SatPct = null then 0
                else if SatPct > SatRojo then 2
                else if SatPct >= SatAmarillo then 1
                else 0,
            NivelNum = List.Max({NivelPrecip, NivelSuelo}),
            Nivel = if NivelNum = 2 then "rojo"
                    else if NivelNum = 1 then "amarillo"
                    else "verde",

            // --- Índice continuo 0-100 ---
            SubPrecip = List.Min({100, PrecipRef / 12 * 100}),
            SubSuelo  = if SatPct = null then 0
                        else List.Max({0, List.Min({100, (SatPct - 40) / 45 * 100})}),
            IIE = if SatPct = null
                  then Number.Round(SubPrecip, 1)
                  else Number.Round(0.55 * SubPrecip + 0.45 * SubSuelo, 1),

            // --- Perspectiva 72 h: el peor nivel que se alcanzaría y cuándo ---
            // Recorre el pronóstico hora por hora con acumulado móvil de 24 h.
            Futuro = List.Transform({Idx + 1 .. List.Count(Precip) - 1}, (i) =>
                let
                    AcumMovil = Suma(Precip, List.Max({0, i - 23}), 24),
                    S  = Suelo{i}?,
                    Sp = if S = null then null else List.Min({100, S / Porosidad * 100}),
                    Np = if AcumMovil > PrecipRojo then 2
                         else if AcumMovil >= PrecipAmarillo then 1 else 0,
                    Ns = if Sp = null then 0
                         else if Sp > SatRojo then 2
                         else if Sp >= SatAmarillo then 1 else 0
                in
                    [Hora = Horas{i}, Acum = AcumMovil, NivelN = List.Max({Np, Ns})]),

            PeorFuturo = if List.Count(Futuro) = 0 then 0
                         else List.Max(List.Transform(Futuro, each _[NivelN])),
            // Solo tiene sentido reportar un pico si el pronóstico deteriora.
            PrimeraCritica = if PeorFuturo = 0 then null
                             else List.First(
                                      List.Select(Futuro, each _[NivelN] = PeorFuturo),
                                      null),
            NivelPron = if PeorFuturo = 2 then "rojo"
                        else if PeorFuturo = 1 then "amarillo" else "verde",
            HoraPico = if PrimeraCritica = null then null else PrimeraCritica[Hora],
            PicoMm   = if PrimeraCritica = null then 0
                       else Number.Round(PrimeraCritica[Acum], 1),
            HorasAviso = if HoraPico = null then null
                         else Duration.TotalHours(HoraPico - Ahora),

            // --- Disparadores en texto (para la tarjeta del tablero) ---
            TxtPrecip =
                if PrecipRef > PrecipRojo
                    then "Precipitación " & Text.From(Number.Round(PrecipRef, 1)) & " mm (> 7 mm)"
                else if PrecipRef >= PrecipAmarillo
                    then "Precipitación " & Text.From(Number.Round(PrecipRef, 1)) & " mm (3-7 mm)"
                else null,
            TxtSuelo =
                if SatPct = null then null
                else if SatPct > SatRojo
                    then "Saturación de suelo " & Text.From(Number.Round(SatPct, 0)) & " % (> 75 %)"
                else if SatPct >= SatAmarillo
                    then "Saturación de suelo " & Text.From(Number.Round(SatPct, 0)) & " % (60-75 %)"
                else null,
            Disparadores = Text.Combine(List.RemoveNulls({TxtPrecip, TxtSuelo}), " | "),

            Accion =
                if Nivel = "rojo" then "Anegamiento inminente / cortes de picadas. Suspender movimientos no críticos."
                else if Nivel = "amarillo" then "Barro en greda. Circular solo con 4x4. Evitar equipos pesados sin escolta."
                else "Transitabilidad normal. Sin restricciones."
        in
            [
                Actualizado          = Ahora,
                Nivel                = Nivel,
                NivelOrden           = NivelNum,
                IIE                  = IIE,
                PrecipReferenciaMm   = Number.Round(PrecipRef, 2),
                PrecipAcum24hMm      = Number.Round(Acum24, 2),
                PrecipPron24hMm      = Number.Round(Pron24, 2),
                PrecipPron72hMm      = Number.Round(Pron72, 2),
                HumedadSueloM3M3     = SueloActual,
                SaturacionSueloPct   = if SatPct = null then null else Number.Round(SatPct, 1),
                TemperaturaC         = Temp{Idx}?,
                VientoKmh            = Viento{Idx}?,
                NivelPronosticado72h = NivelPron,
                HoraPico72h          = HoraPico,
                PicoPrecip24hMm      = PicoMm,
                HorasHastaPico       = HorasAviso,
                Disparadores         = if Disparadores = ""
                                       then "Sin disparadores. Condiciones normales."
                                       else Disparadores,
                AccionRecomendada    = Accion,
                PorosidadUsada       = Porosidad
            ],

    // ---------------------------------------------------------------- //
    // APLICAR A CADA PUNTO Y EXPANDIR
    // ---------------------------------------------------------------- //
    ConResultado = Table.AddColumn(Puntos, "R",
                       each Calcular([Lat], [Lon]), type record),

    Expandida = Table.ExpandRecordColumn(ConResultado, "R",
        {"Actualizado", "Nivel", "NivelOrden", "IIE", "PrecipReferenciaMm",
         "PrecipAcum24hMm", "PrecipPron24hMm", "PrecipPron72hMm",
         "HumedadSueloM3M3", "SaturacionSueloPct", "TemperaturaC", "VientoKmh",
         "NivelPronosticado72h", "HoraPico72h", "PicoPrecip24hMm",
         "HorasHastaPico", "Disparadores", "AccionRecomendada", "PorosidadUsada"}),

    Tipada = Table.TransformColumnTypes(Expandida, {
        {"PuntoId", type text}, {"Punto", type text}, {"Descripcion", type text},
        {"Lat", type number}, {"Lon", type number},
        {"Actualizado", type datetime}, {"Nivel", type text},
        {"NivelOrden", Int64.Type}, {"IIE", type number},
        {"PrecipReferenciaMm", type number}, {"PrecipAcum24hMm", type number},
        {"PrecipPron24hMm", type number}, {"PrecipPron72hMm", type number},
        {"HumedadSueloM3M3", type number}, {"SaturacionSueloPct", type number},
        {"TemperaturaC", type number}, {"VientoKmh", type number},
        {"NivelPronosticado72h", type text}, {"HoraPico72h", type datetime},
        {"PicoPrecip24hMm", type number}, {"HorasHastaPico", type number},
        {"Disparadores", type text}, {"AccionRecomendada", type text},
        {"PorosidadUsada", type number}
    })
in
    Tipada
