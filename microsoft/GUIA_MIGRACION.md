# Migración a un entorno 100 % Microsoft

Documento para la PC empresarial: cómo sostener este sistema **sin Python, sin
GitHub y sin Claude**, usando solo licencias Microsoft.

---

## Lo que hay que entender primero

El sistema hace tres cosas, y solo una de ellas es "código":

| Función | Qué requiere realmente |
|---|---|
| Llamar a Open-Meteo cada 2 h | Un scheduler con acción HTTP |
| Calcular el semáforo | Cuatro comparaciones numéricas |
| Guardar el histórico y mostrarlo | Una tabla y un tablero |

Nada de eso es exclusivo de Python. La matriz del IIE es aritmética de
secundaria: `si lluvia > 7 mm o saturación > 75 % entonces rojo`. Se expresa
igual en Power Query, en Power Automate o en DAX.

---

## Los tres caminos

| | Camino 1 — Power BI solo | Camino 2 — Power Automate + SharePoint | Camino 3 — GitHub Actions |
|---|---|---|---|
| **Licencias** | Power BI | Power BI + Power Automate + SharePoint | Cuenta GitHub |
| **Permisos de IT** | Ninguno | Ninguno (todo es cloud del tenant) | Alta de GitHub |
| **Tiempo de puesta en marcha** | ~15 min | ~2 h | ~5 min |
| **Historial acumulado** | ❌ solo la foto actual | ✅ | ✅ |
| **Alertas SMN** | ❌ | ✅ caja envolvente | ✅ polígono exacto |
| **Notificación a Teams** | Alertas nativas de Power BI | ✅ tarjeta adaptativa | ✅ webhook |
| **Frecuencia** | 8 refrescos/día (Pro) · 48 (Premium) | Cada 2 h o menos | Cada 2 h |
| **Quién lo mantiene** | Cualquiera que sepa Power Query | Cualquiera que sepa Power Automate | Requiere Python |

**Recomendación:** arrancar con el **Camino 1 hoy mismo** (funciona en 15 minutos
y ya da el semáforo y la perspectiva 72 h), y migrar al **Camino 2** cuando se
quiera historial y alertas push. El Camino 3 queda como referencia técnica: el
código Python documenta la lógica exacta y sirve para el backtest de calibración,
aunque no se despliegue en la empresa.

---

# Camino 1 — Power BI solo (arrancar por acá)

### Paso 1 — Crear las consultas

1. Power BI Desktop → **Inicio → Obtener datos → Consulta en blanco**
2. En el panel de la izquierda, clic derecho sobre la consulta → **Editor avanzado**
3. Borrar el contenido y pegar el archivo **`01_IIE_Estado.m`** completo
4. Renombrar la consulta a **`IIE_Estado`**
5. Repetir con **`02_IIE_Serie_Horaria.m`** → renombrar a **`IIE_SerieHoraria`**
6. **Cerrar y aplicar**

### Paso 2 — Configuración obligatoria

**Niveles de privacidad.** Archivo → Opciones y configuración → Opciones →
Archivo actual → Privacidad → **"Omitir siempre la configuración de niveles de
privacidad"**. Sin esto Power BI bloquea la combinación de la tabla de puntos con
la respuesta web y devuelve un error de "formula.firewall".

**Credenciales.** La primera vez pide autenticación para `api.open-meteo.com` →
elegir **Anónimo**, nivel de privacidad **Público**.

### Paso 2 bis — Si algo falla al pegar

Los dos `.m` pasan una verificación estructural automática (balance de
delimitadores, bloques `let`/`in`, comas colgantes y existencia de cada función
en la biblioteca de M). Para volver a correrla después de editarlos:

```bash
python verificar_m.py 01_IIE_Estado.m 02_IIE_Serie_Horaria.m
```

Errores frecuentes al modificarlos a mano:

| Síntoma | Causa |
|---|---|
| `Formula.Firewall: Query references other queries` | Falta el paso 2 de privacidad |
| `The name 'Number.Max' wasn't recognized` | En M son `List.Max` / `List.Min`; `Number.Max` no existe |
| La API devuelve error de coordenada | Se reemplazó `Text.From(n, "en-US")` por `Text.From(n)` y la coma decimal argentina rompió la URL |
| Datos de la hora equivocada | Se tocó el índice; debe ser `72 + hora`, no `largo − 73` |

### Paso 3 — Modelo

Relación **`IIE_Estado[PuntoId]` 1 → \* `IIE_SerieHoraria[PuntoId]`**.

### Paso 4 — Publicar y programar

Publicar al área de trabajo → en el dataset, **Actualización programada**.
Como el origen es Web anónimo, **no hace falta gateway**. Con Pro se pueden
programar 8 refrescos diarios (cada 3 h cubre el ciclo); con capacidad Premium /
Fabric, 48 (cada 30 min).

### Paso 5 — Alerta nativa

Anclar a un dashboard la tarjeta con `Nivel Corredor` → **Configurar alerta** →
notifica por mail y app móvil cuando cambia. Es la alerta push del Camino 1.

### Qué NO da el Camino 1

- **No acumula historial**: cada refresh reemplaza los datos. Se ve el estado
  actual y el pronóstico 72 h, pero no "cuántos días estuvimos en rojo en agosto".
- **No incluye alertas del SMN**: el feed CAP es XML con polígonos y el test de
  contención geográfica es incómodo en Power Query. Va en el Camino 2.

Para la reunión eso alcanza: lo que se mira todos los días es el semáforo y la
anticipación, no la serie histórica.

---

# Camino 2 — Power Automate + Lista de SharePoint

Es el reemplazo exacto del script Python. Todo corre en el tenant.

## 2.1 — Crear las listas de SharePoint

Ejecutar `04_Crear_Lista_SharePoint.ps1` (requiere `Install-Module PnP.PowerShell
-Scope CurrentUser`):

```powershell
.\04_Crear_Lista_SharePoint.ps1 -SitioUrl "https://<tenant>.sharepoint.com/sites/<sitio>"
```

Si la política de la empresa bloquea la instalación del módulo, crear las
columnas a mano con **exactamente** estos nombres:

| Columna | Tipo |
|---|---|
| `Title` (la que viene por defecto, renombrada) | Texto — guarda el `PuntoId` |
| `Punto` | Texto |
| `Timestamp` | Fecha y hora |
| `Nivel` | Elección: verde / amarillo / rojo |
| `NivelOrden` | Número (0 decimales) |
| `IIE` | Número (1 decimal) |
| `PrecipReferenciaMm` | Número (2 decimales) |
| `PrecipAcum24hMm` | Número (2 decimales) |
| `PrecipPron24hMm` | Número (2 decimales) |
| `PrecipPron72hMm` | Número (2 decimales) |
| `HumedadSueloM3M3` | Número (3 decimales) |
| `SaturacionSueloPct` | Número (1 decimal) |
| `AlertaSmnColor` | Texto |
| `NivelPronosticado72h` | Texto |
| `PicoPrecip24hMm` | Número (1 decimal) |
| `Disparadores` | Varias líneas de texto |

> **Sin acentos ni espacios, y no es una preferencia estética.** El nombre
> interno de una columna de SharePoint se congela al crearla y no cambia si
> después se la renombra. Una columna creada como "Saturación %" queda
> internamente como `Saturaci_x00f3_n_x0020__x0025_`, y ese es el texto que hay
> que escribir en cada expresión del flujo. Con nombres ASCII, el nombre interno
> es igual al visible.

> **Índice en `Timestamp`.** A 3 puntos cada 2 h, la lista pasa los 5.000
> elementos en unos 4 meses y ahí SharePoint empieza a rechazar las consultas
> ordenadas por fecha. El script ya crea el índice; si se hace a mano:
> Configuración de la lista → Columnas indizadas → Crear índice sobre `Timestamp`.

## 2.2 — Crear el flujo

**Power Automate → Crear → Flujo de nube programado.**
Repetir cada **2 horas**. Zona horaria: **(UTC-03:00) Ciudad de Buenos Aires**.

Las acciones van en este orden. **Los nombres importan**: las expresiones
posteriores referencian a las anteriores por nombre, así que si se renombra una
acción hay que actualizar sus referencias.

### Acciones 1 a 6 — Inicializar variable

| # | Nombre de la acción | Tipo | Valor |
|---|---|---|---|
| 1 | `Porosidad` | Flotante | `0.53` |
| 2 | `PrecipAmarillo` | Flotante | `3` |
| 3 | `PrecipRojo` | Flotante | `7` |
| 4 | `SatAmarillo` | Flotante | `60` |
| 5 | `SatRojo` | Flotante | `75` |
| 6 | `PeorNivel` | Entero | `0` |

> Tener los umbrales como variables y no incrustados en las expresiones es lo
> que permite recalibrar el sistema sin leer el flujo entero.

### Acción 7 — Inicializar variable `Puntos` (tipo Matriz)

```json
[
  {"id":"anelo_pueblo","nombre":"Añelo Pueblo","lat":-38.353,"lon":-68.783},
  {"id":"acceso_meseta","nombre":"Acceso Meseta","lat":-38.300,"lon":-68.850},
  {"id":"tratayen_sur","nombre":"Tratayén / Sector Sur","lat":-38.483,"lon":-68.500}
]
```

### Acción 8 — `Aplicar a cada uno` sobre `variables('Puntos')`

Todo lo que sigue va **dentro** de este bucle.

**8.1 — HTTP** (método GET). URI:

```
https://api.open-meteo.com/v1/forecast
```

Con estas consultas (campo *Consultas*, un par por fila):

| Clave | Valor |
|---|---|
| `latitude` | `@{items('Aplicar_a_cada_uno')['lat']}` |
| `longitude` | `@{items('Aplicar_a_cada_uno')['lon']}` |
| `hourly` | `precipitation,soil_moisture_0_to_7cm,temperature_2m,wind_speed_10m` |
| `past_days` | `3` |
| `forecast_days` | `3` |
| `timezone` | `America/Argentina/Buenos_Aires` |

**8.2 — Analizar JSON.** Contenido: `body('HTTP')`.
Esquema: pegar el contenido de **`03_Esquema_ParseJSON.json`** (ya validado
contra una respuesta real de la API).

**8.3 — Componer**, nombre `idxAhora`:

```
add(72, int(formatDateTime(convertFromUtc(utcNow(),'Argentina Standard Time'),'HH')))
```

> **Este es el punto donde es fácil equivocarse.** La serie que devuelve la API
> tiene 144 horas y arranca a las 00:00 del primer día pasado. Como `past_days`
> es 3, el índice de hoy a las 00:00 es 3 × 24 = 72, y la hora actual está en
> 72 + hora. Verificado contra la API: a las 06:00 ART el índice correcto es 78.
> La fórmula "largo − 73" que parece razonable devuelve 71, que es *ayer a las
> 23:00* — 7 horas de desfasaje y el semáforo mira la lluvia equivocada.

**8.4 — Componer**, nombre `acum24` (lluvia caída en las últimas 24 h):

```
sum(take(skip(body('Analizar_JSON')?['hourly']?['precipitation'], sub(outputs('idxAhora'), 23)), 24))
```

**8.5 — Componer**, nombre `pron24`:

```
sum(take(skip(body('Analizar_JSON')?['hourly']?['precipitation'], add(outputs('idxAhora'), 1)), 24))
```

**8.6 — Componer**, nombre `pron72`:

```
sum(take(skip(body('Analizar_JSON')?['hourly']?['precipitation'], add(outputs('idxAhora'), 1)), 72))
```

**8.7 — Componer**, nombre `precipRef`:

```
max(outputs('acum24'), outputs('pron24'))
```

**8.8 — Componer**, nombre `satPct`:

```
min(100, mul(div(float(coalesce(body('Analizar_JSON')?['hourly']?['soil_moisture_0_to_7cm'][outputs('idxAhora')], 0)), variables('Porosidad')), 100))
```

> El `coalesce` no es decorativo: Open-Meteo devuelve `null` en la humedad de
> suelo cuando falta el dato de la grilla, y `float(null)` corta el flujo con
> un error en tiempo de ejecución. Con `coalesce` el punto queda en verde por
> falta de dato en vez de tumbar la corrida de los otros dos.

**8.9 — Componer**, nombre `nivel`:

```
if(
  or(greater(outputs('precipRef'), variables('PrecipRojo')),
     greater(outputs('satPct'), variables('SatRojo'))),
  'rojo',
  if(
    or(greaterOrEquals(outputs('precipRef'), variables('PrecipAmarillo')),
       greaterOrEquals(outputs('satPct'), variables('SatAmarillo'))),
    'amarillo',
    'verde'
  )
)
```

**8.10 — Componer**, nombre `nivelOrden`:

```
if(equals(outputs('nivel'),'rojo'), 2, if(equals(outputs('nivel'),'amarillo'), 1, 0))
```

**8.11 — Componer**, nombre `iie`:

```
add(
  mul(0.55, min(100, mul(div(outputs('precipRef'), 12), 100))),
  mul(0.45, max(0, min(100, mul(div(sub(outputs('satPct'), 40), 45), 100))))
)
```

**8.12 — Establecer variable** `PeorNivel`:

```
max(variables('PeorNivel'), outputs('nivelOrden'))
```

**8.13 — Crear elemento** en `IIE_Historico`:

| Campo | Valor |
|---|---|
| `Title` | `@{items('Aplicar_a_cada_uno')['id']}` |
| `Punto` | `@{items('Aplicar_a_cada_uno')['nombre']}` |
| `Timestamp` | `@{convertFromUtc(utcNow(),'Argentina Standard Time')}` |
| `Nivel` | `@{outputs('nivel')}` |
| `NivelOrden` | `@{outputs('nivelOrden')}` |
| `IIE` | `@{outputs('iie')}` |
| `PrecipReferenciaMm` | `@{outputs('precipRef')}` |
| `PrecipAcum24hMm` | `@{outputs('acum24')}` |
| `PrecipPron24hMm` | `@{outputs('pron24')}` |
| `PrecipPron72hMm` | `@{outputs('pron72')}` |
| `HumedadSueloM3M3` | `@{body('Analizar_JSON')?['hourly']?['soil_moisture_0_to_7cm'][outputs('idxAhora')]}` |
| `SaturacionSueloPct` | `@{outputs('satPct')}` |

> **Concurrencia.** En la configuración del bucle *Aplicar a cada uno*, dejar el
> control de concurrencia **desactivado** (secuencial). Con 3 puntos no hay nada
> que ganar en paralelo, y `PeorNivel` se calcula mal si dos iteraciones lo
> escriben a la vez.

## 2.3 — Notificación a Teams (solo si cambia el nivel)

Después del bucle:

**9 — Obtener elementos** de `IIE_Historico`. Ordenar por `Created desc`,
**Superior**: 6 (3 puntos × 2 corridas). Así se tiene la corrida actual y la
anterior.

**10 — Componer**, nombre `nivelAnterior`: el máximo `NivelOrden` de los
elementos 4 a 6 de esa consulta (la corrida previa).

**11 — Condición**: notificar solo si

```
and(
  greater(variables('PeorNivel'), 0),
  not(equals(variables('PeorNivel'), outputs('nivelAnterior')))
)
```

**12 — Si es verdadero → Publicar tarjeta adaptativa en un canal de Teams:**

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "size": "Large",
      "weight": "Bolder",
      "text": "Anegamiento Añelo: @{if(equals(variables('PeorNivel'),2),'ROJO','AMARILLO')}",
      "color": "@{if(equals(variables('PeorNivel'),2),'Attention','Warning')}"
    },
    {
      "type": "TextBlock",
      "wrap": true,
      "text": "@{if(equals(variables('PeorNivel'),2),'Anegamiento inminente / cortes de picadas. Suspender movimientos no criticos.','Barro en greda. Circular solo con 4x4. Evitar equipos pesados sin escolta.')}"
    },
    {
      "type": "TextBlock",
      "spacing": "Small",
      "isSubtle": true,
      "size": "Small",
      "text": "Actualizado @{convertFromUtc(utcNow(),'Argentina Standard Time','dd/MM HH:mm')} ART"
    }
  ]
}
```

> **Notificar solo ante cambio de nivel no es un detalle estético.** Un canal
> que avisa cada 2 h se silencia en una semana, y a partir de ahí el sistema
> deja de existir para la gente que tiene que usarlo.

## 2.4 — Conectar Power BI

**Obtener datos → Listas de SharePoint Online** → URL del sitio → seleccionar
`IIE_Historico`. Las medidas DAX de `powerbi/GUIA_POWERBI.md` funcionan igual
sobre la lista que sobre el CSV; solo cambian los nombres de columna.

Se pueden mantener las dos consultas de Power Query del Camino 1 en el mismo
archivo: `IIE_Estado` y `IIE_SerieHoraria` dan la foto actual y el pronóstico en
vivo, y la lista de SharePoint aporta el histórico. Se complementan.

## 2.5 — Alertas del SMN (bloque opcional del mismo flujo)

Verificado contra el feed real esta mañana: 67 avisos vigentes en el país, los
67 con polígono, 34 relevantes para anegamiento (lluvias, tormentas, nevadas).

### 2.5.1 — Traer el índice y quedarse con los avisos relevantes

**HTTP** GET a `https://ssl.smn.gob.ar/CAP/AR.php`. Devuelve HTML con los links
a los XML.

**Componer**, nombre `linksCrudos`:

```
split(body('HTTP_indice_CAP'), 'https://ssl.smn.gob.ar/feeds/CAP/xml_generados/')
```

**Filtrar matriz** sobre `linksCrudos`, condición:

```
or(contains(item(), 'Lluvia'), contains(item(), 'Tormenta'), contains(item(), 'Nevada'))
```

> **Filtrar por nombre de archivo antes de descargar** baja de 81 a ~34
> descargas. No es solo velocidad: el origen del SMN devuelve **HTTP 522** cuando
> se lo satura — en las corridas de prueba fallaron 2-4 archivos de 81 en cada
> intento. Menos descargas, menos fallas, y los avisos por viento o zonda no
> cortan caminos igual.

**Seleccionar** (Select), para reconstruir la URL completa de cada uno:

```
concat('https://ssl.smn.gob.ar/feeds/CAP/xml_generados/', first(split(item(), '"')))
```

### 2.5.2 — Leer cada aviso

**Aplicar a cada uno** sobre la salida del Select, con **concurrencia limitada a
4** (más que eso dispara los 522):

**a) HTTP** GET a `item()`.

**b) Componer** los campos con `xpath()`. Las expresiones están **probadas
contra un XML real del SMN de hoy**:

| Nombre | Expresión |
|---|---|
| `severidad` | `xpath(xml(body('HTTP_aviso')), "string(//*[local-name()='info']/*[local-name()='severity'])")` |
| `evento` | `xpath(xml(body('HTTP_aviso')), "string(//*[local-name()='info']/*[local-name()='event'])")` |
| `expira` | `xpath(xml(body('HTTP_aviso')), "string(//*[local-name()='info']/*[local-name()='expires'])")` |
| `estado` | `xpath(xml(body('HTTP_aviso')), "string(//*[local-name()='alert']/*[local-name()='status'])")` |
| `poligono` | `xpath(xml(body('HTTP_aviso')), "string(//*[local-name()='area']/*[local-name()='polygon'])")` |

> **El `local-name()` es obligatorio.** El XML del SMN declara el namespace por
> defecto `urn:oasis:names:tc:emergency:cap:1.2`, y la función `xpath()` de
> Power Automate no permite declarar prefijos para un namespace por defecto. Un
> XPath directo como `//info/severity` devuelve vacío sin dar error, que es la
> peor forma de fallar: el flujo corre verde y nunca detecta una alerta.

**c) Componer** `colorSmn` — traducción de la severidad CAP a la nomenclatura
de colores del SMN:

```
if(equals(outputs('severidad'),'Extreme'), 'rojo',
   if(equals(outputs('severidad'),'Severe'), 'naranja', 'amarillo'))
```

### 2.5.3 — Saber si el aviso cubre Añelo

**Seleccionar** `LatsPoligono`. Desde: `split(outputs('poligono'), ' ')`, mapa:

```
float(first(split(item(), ',')))
```

**Seleccionar** `LonsPoligono`, mismo origen, mapa:

```
float(last(split(item(), ',')))
```

**Condición** — el punto cae dentro de la caja envolvente del polígono, con
0,02° (~2 km) de margen:

```
and(
  greaterOrEquals(items('Aplicar_a_cada_punto')['lat'], sub(min(body('LatsPoligono')), 0.02)),
  lessOrEquals(items('Aplicar_a_cada_punto')['lat'], add(max(body('LatsPoligono')), 0.02)),
  greaterOrEquals(items('Aplicar_a_cada_punto')['lon'], sub(min(body('LonsPoligono')), 0.02)),
  lessOrEquals(items('Aplicar_a_cada_punto')['lon'], add(max(body('LonsPoligono')), 0.02))
)
```

### 2.5.4 — Elevar el semáforo

Si la condición da verdadero y `colorSmn` es `naranja` o `rojo`, forzar el nivel
del punto a **rojo**:

```
if(contains(createArray('naranja','rojo'), outputs('colorSmn')), 2, variables('PeorNivel'))
```

Si es `amarillo`, eleva un punto que estaba en verde, pero no toca uno que ya
está en amarillo o rojo:

```
max(variables('PeorNivel'), 1)
```

### La diferencia honesta con la versión Python

El script Python hace **ray casting** sobre el polígono: determina si el punto
está realmente adentro. Power Automate usa la **caja envolvente**, porque
recorrer 96 vértices con expresiones es impracticable.

Lo medí sobre los 34 avisos relevantes de hoy: **la mediana del área real del
polígono es el 52 % de su caja envolvente** (p25 41 %, p75 61 %, el peor caso
16 %). O sea que la caja cubre alrededor del doble del área real, y
aproximadamente la mitad de los avisos que marque para un punto dado serían
falsos positivos.

Del lado de la seguridad vial ese es el error que conviene cometer: avisar de
más es molesto, no avisar es un camión empantanado. Pero hay que decirlo en la
reunión, no dejarlo escondido, porque afecta la credibilidad del semáforo si el
área lo descubre sola.

**Si más adelante molesta el ruido**, hay dos salidas sin volver a Python:

1. Achicar el problema: en vez de la caja de todo el polígono, filtrar primero
   los vértices a menos de 1° de Añelo y armar la caja solo con esos. Se acerca
   bastante al polígono real y sigue siendo aritmética de expresiones.
2. Mover solo este bloque a una consulta de Power Query dentro de Power BI,
   donde sí se puede escribir el ray casting exacto — está implementado en
   `src/smn.py`, función `punto_en_poligono`, y se traduce casi línea por línea
   con `List.Accumulate`.

## Riesgos a declarar en la reunión

| Riesgo | Mitigación |
|---|---|
| El conector HTTP de Power Automate es premium | Verificar licencia antes de diseñar. Si no está: Camino 1 |
| Open-Meteo es un servicio gratuito de terceros sin SLA | Es un sistema de apoyo a la decisión, no de seguridad crítica. El criterio del operador manda |
| El feed CAP del SMN devuelve 522 bajo carga | Medido: fallan 2-4 archivos de 81 por corrida. Se mitiga filtrando por evento antes de descargar (81 → 34) y limitando la concurrencia a 4. Si falla igual, el semáforo se calcula solo con Open-Meteo |
| En Power Automate la contención usa caja envolvente, no el polígono | Sobrestima: la mediana del área real es el 52 % de la caja. Avisa de más, nunca de menos |
| La porosidad 0,53 es una calibración estadística, no una medición de suelo | Validar contra el registro real de cortes de vialidad y reajustar |
| ERA5 / Open-Meteo tienen resolución de ~9 km | Suficiente para decidir a nivel corredor, no para un tramo puntual de 200 m |

---

## Qué queda dependiendo de Python

Solo el **backtest de calibración** (`backtest.py`). No corre en producción: se
usa una vez por año, o cuando vialidad reporte que el semáforo sobrealerta o
subalerta, para recalcular la tabla de porosidad. Si no hay Python disponible, el
mismo análisis se puede rehacer descargando el CSV de la API de archivo de
Open-Meteo y armando la tabla en Excel con `CONTAR.SI`.

La operación diaria no necesita Python en ningún momento.
