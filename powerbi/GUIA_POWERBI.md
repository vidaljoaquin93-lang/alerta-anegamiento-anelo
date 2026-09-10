# Conexión a Power BI

El repositorio publica los datos como CSV/JSON planos. Power BI se conecta con el
conector **Web** — sin gateway, sin credenciales de base, sin costo.

---

## 1. Obtener las URLs raw

Con el repo ya subido, las URLs son:

```
https://raw.githubusercontent.com/<usuario>/<repo>/main/data/historico.csv
https://raw.githubusercontent.com/<usuario>/<repo>/main/data/pronostico_horario.csv
https://raw.githubusercontent.com/<usuario>/<repo>/main/data/alertas_smn.csv
https://raw.githubusercontent.com/<usuario>/<repo>/main/data/estado_actual.json
```

**Si el repositorio es privado**, la URL raw exige un token. Dos caminos:

- **Recomendado:** repo público con datos meteorológicos (no hay información
  sensible de la operación: son coordenadas y lluvia).
- **Repo privado:** generar un *fine-grained personal access token* con permiso
  `Contents: Read` sobre ese repo, y en Power BI usar
  *Web → Avanzadas → encabezado* `Authorization` = `Bearer <token>`.
  Ese token vence: anotar la fecha de expiración.

---

## 2. Cargar las tablas

**Obtener datos → Web → URL básica** y pegar cada URL.

En el editor de Power Query, para `historico.csv`:

1. Origen de archivo: **65001: Unicode (UTF-8)** — indispensable para las tildes
   de "Añelo" y "Tratayén".
2. Delimitador: coma.
3. Tipos de datos:

| Columna | Tipo |
|---|---|
| `timestamp_local` | Fecha/hora |
| `fecha` | Fecha |
| `punto_id`, `punto_nombre`, `nivel`, `accion_recomendada`, `disparadores` | Texto |
| `lat`, `lon` | Número decimal |
| `iie`, `precip_*`, `humedad_suelo_m3m3`, `saturacion_suelo_pct`, `subindice_*`, `temperatura_c`, `viento_kmh` | Número decimal |
| `alerta_smn_cantidad` | Número entero |

> **Configuración regional.** Si el archivo carga con las comas decimales mal
> interpretadas, en *Cambiar tipo → Con configuración regional* elegir
> **Inglés (Estados Unidos)**: el CSV usa punto decimal.

Repetir para `pronostico_horario.csv` y `alertas_smn.csv`.

---

## 3. Modelo de datos

```
        Calendario (tabla de fechas)
              │ 1
              │ *
        Historico ──────* 1── Puntos (tabla de dimensión)
                                    │ 1
                                    │ *
                            Pronostico_horario
                                    │
                            Alertas_SMN
```

Crear la dimensión **Puntos** con *Nueva tabla*:

```dax
Puntos =
DISTINCT (
    SELECTCOLUMNS (
        Historico,
        "punto_id",     Historico[punto_id],
        "punto_nombre", Historico[punto_nombre],
        "lat",          Historico[lat],
        "lon",          Historico[lon]
    )
)
```

Y la tabla de fechas:

```dax
Calendario =
ADDCOLUMNS (
    CALENDAR ( MIN ( Historico[fecha] ), MAX ( Historico[fecha] ) ),
    "Año",       YEAR ( [Date] ),
    "Mes",       FORMAT ( [Date], "MMM yyyy" ),
    "MesNro",    MONTH ( [Date] ),
    "DiaSemana", FORMAT ( [Date], "ddd" )
)
```

Relaciones: `Puntos[punto_id]` 1→* `Historico[punto_id]` y 1→* `Pronostico_horario[punto_id]`;
`Calendario[Date]` 1→* `Historico[fecha]`.
Marcar `Calendario` como tabla de fechas.

---

## 4. Medidas DAX

### Estado actual

```dax
Ultima Actualizacion = MAX ( Historico[timestamp_local] )

Nivel Actual =
VAR UltimoTS = CALCULATE ( MAX ( Historico[timestamp_local] ), ALL ( Historico ) )
RETURN
    CALCULATE (
        SELECTEDVALUE ( Historico[nivel] ),
        Historico[timestamp_local] = UltimoTS
    )

IIE Actual =
VAR UltimoTS = CALCULATE ( MAX ( Historico[timestamp_local] ), ALL ( Historico ) )
RETURN
    CALCULATE ( MAX ( Historico[iie] ), Historico[timestamp_local] = UltimoTS )

Nivel Corredor =                    -- el peor punto define el corredor
VAR UltimoTS = CALCULATE ( MAX ( Historico[timestamp_local] ), ALL ( Historico ) )
VAR Peor =
    CALCULATE (
        MAXX (
            Historico,
            SWITCH ( Historico[nivel], "verde", 0, "amarillo", 1, "rojo", 2, 0 )
        ),
        Historico[timestamp_local] = UltimoTS,
        ALL ( Puntos )
    )
RETURN SWITCH ( Peor, 0, "VERDE", 1, "AMARILLO", 2, "ROJO" )
```

### Semáforo (color condicional)

En *Formato → Color de fondo → Formato condicional → Estilo: Valor de campo*,
usar:

```dax
Color Nivel =
SWITCH (
    [Nivel Actual],
    "rojo",     "#D03B3B",
    "amarillo", "#FAB219",
    "verde",    "#0CA30C",
    "#898781"
)
```

Y para el texto del semáforo, que nunca dependa solo del color:

```dax
Etiqueta Nivel =
SWITCH ( [Nivel Actual], "rojo", "■ ROJO", "amarillo", "▲ AMARILLO", "verde", "● VERDE", "s/d" )
```

### Operación

```dax
Accion Recomendada =
SWITCH (
    [Nivel Corredor],
    "ROJO",     "Anegamiento inminente / cortes de picadas. Suspender movimientos no críticos.",
    "AMARILLO", "Barro en greda. Circular solo con 4x4. Evitar equipos pesados sin escolta.",
    "Transitabilidad normal. Sin restricciones."
)

Horas en Rojo (periodo) =
CALCULATE ( COUNTROWS ( Historico ), Historico[nivel] = "rojo" ) * 2   -- corrida cada 2 h

Dias con Restriccion =
CALCULATE (
    DISTINCTCOUNT ( Historico[fecha] ),
    Historico[nivel] IN { "amarillo", "rojo" }
)

% Disponibilidad del Corredor =
VAR Total = COUNTROWS ( Historico )
VAR Verde = CALCULATE ( COUNTROWS ( Historico ), Historico[nivel] = "verde" )
RETURN DIVIDE ( Verde, Total )

Lluvia Acumulada Periodo =
SUMX (
    VALUES ( Historico[fecha] ),
    CALCULATE ( MAX ( Historico[precip_acum_24h_mm] ) )
)

Alertas SMN Vigentes = COUNTROWS ( Alertas_SMN )
```

### Tendencia

```dax
IIE Promedio = AVERAGE ( Historico[iie] )

IIE vs Ayer =
VAR Hoy    = [IIE Promedio]
VAR Ayer   = CALCULATE ( [IIE Promedio], DATEADD ( Calendario[Date], -1, DAY ) )
RETURN Hoy - Ayer

Saturacion Suelo Actual =
VAR UltimoTS = CALCULATE ( MAX ( Historico[timestamp_local] ), ALL ( Historico ) )
RETURN CALCULATE ( MAX ( Historico[saturacion_suelo_pct] ), Historico[timestamp_local] = UltimoTS )
```

---

## 5. Diseño de página sugerido

**Fila superior — estado (tarjetas):**
`Nivel Corredor` · `Ultima Actualizacion` · `Alertas SMN Vigentes` · `% Disponibilidad del Corredor`

**Fila media:**
- **Mapa** (`lat`/`lon` de Puntos, tamaño = `IIE Actual`, color = `Color Nivel`).
- **Tarjetas por punto**: una matriz con `punto_nombre`, `Etiqueta Nivel`,
  `IIE Actual`, `Saturacion Suelo Actual`.

**Fila inferior:**
- **Gráfico de líneas** desde `Pronostico_horario`: eje X `hora`, valor
  `precipitacion_mm`, leyenda `punto_nombre`. Agregar líneas constantes en 3 y 7.
- **Segundo gráfico de líneas** para `saturacion_suelo_pct`, con líneas constantes
  en 60 y 75.

> **Un eje por gráfico.** No poner lluvia (mm) y saturación (%) en el mismo visual
> con dos ejes Y: son escalas distintas y el cruce visual engaña. Dos gráficos
> apilados compartiendo el eje de tiempo se leen bien y no mienten.

**Tabla de detalle:** `Alertas_SMN` con `evento`, `color_smn`, `inicio`, `expira`,
`descripcion`.

---

## 6. Actualización programada

*Configuración del dataset → Actualización programada.*

Como el origen es Web anónimo (repo público), **no hace falta gateway**. En
*Credenciales del origen de datos* elegir **Anónimo** y nivel de privacidad
**Público**.

Power BI Pro permite 8 actualizaciones diarias: programar cada 3 horas cubre
holgadamente el ciclo de 2 h del script.

> Si el repo es privado y se usa el token en el encabezado, Power BI Service
> **sí** puede requerir gateway según la política del tenant. Es otro motivo para
> preferir el repo público.

---

## 7. Alertas nativas de Power BI

Sobre la tarjeta `Nivel Corredor`, anclada a un dashboard:
*Configurar alerta → cuando el valor sea "ROJO"*.

Complementa —no reemplaza— a la notificación de Teams/Telegram del script, que es
inmediata; la de Power BI depende del ciclo de refresh del dataset.
