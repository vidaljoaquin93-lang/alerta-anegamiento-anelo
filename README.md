# Sistema de Alerta Temprana de Anegamiento de Caminos — Añelo, Vaca Muerta

Detección anticipada de intransitabilidad en caminos de greda y ripio de la zona de
Añelo (Neuquén). Corre cada 2 horas en GitHub Actions, con **costo cero de
infraestructura**: sin servidores, sin cloud paga, sin API keys.

```
Open-Meteo ──┐
             ├──► IIE (matriz de riesgo) ──► CSV/JSON en el repo ──► Power BI
SMN CAP ─────┘                          └──► tablero HTML (GitHub Pages)
                                        └──► Teams / Telegram (opcional)
```

---

## Puesta en marcha (5 minutos)

1. **Crear el repositorio** en GitHub (puede ser privado) y subir esta carpeta:

   ```bash
   git init && git add . && git commit -m "Sistema de alerta de anegamiento"
   git branch -M main
   git remote add origin https://github.com/<usuario>/<repo>.git
   git push -u origin main
   ```

2. **Habilitar la escritura del workflow**: *Settings → Actions → General →
   Workflow permissions* → **Read and write permissions** → Save.
   Sin esto el bot no puede commitear los datos.

3. **Primera corrida**: *Actions → "Monitoreo de anegamiento — Añelo" → Run workflow*.
   A partir de ahí corre sola cada 2 horas.

4. *(Opcional)* **Publicar el tablero**: *Settings → Pages → Source: Deploy from a
   branch → main / `/docs`*. Queda en
   `https://<usuario>.github.io/<repo>/` y se actualiza en cada corrida.

> **Nota sobre el cron de GitHub.** Los schedules de GitHub Actions se ejecutan
> con demora variable (típicamente 3-15 min, más en horas pico). Para monitoreo
> vial es irrelevante, pero conviene saberlo: la frecuencia efectiva es
> "cada 2 h ± 15 min", no un reloj exacto.

---

## Secrets y variables (todos opcionales)

El sistema **funciona completo sin configurar nada**. Cada secret agrega una
capacidad; si falta, ese módulo se saltea sin fallar la corrida.

*Settings → Secrets and variables → Actions*

| Nombre | Tipo | Para qué |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | secret | Notificar al canal de Teams del área |
| `TELEGRAM_BOT_TOKEN` | secret | Notificar por Telegram (bot de @BotFather) |
| `TELEGRAM_CHAT_ID` | secret | Chat o grupo destino de Telegram |
| `GOOGLE_SHEETS_CREDENTIALS` | secret | JSON del service account (si se quiere Sheets además del CSV) |
| `GOOGLE_SHEETS_ID` | variable | ID del spreadsheet destino |
| `SMN_API_TOKEN` | secret | Token JWT de la API interna del SMN, si algún día se consigue |
| `IIE_POROSIDAD_TOTAL` | variable | Recalibrar el umbral de humedad de suelo sin tocar código |

Para activar Google Sheets, además hay que descomentar `gspread` y `google-auth`
en `requirements.txt`.

---

## Cómo funciona el índice IIE

### Matriz de riesgo (regla autoritativa — el semáforo)

| Nivel | Condición | Acción operativa |
|---|---|---|
| 🟢 **Verde** | Lluvia < 3 mm **y** saturación de suelo < 60 % | Transitabilidad normal |
| 🟡 **Amarillo** | Lluvia 3-7 mm **o** saturación 60-75 % | Barro en greda: solo 4x4 |
| 🔴 **Rojo** | Lluvia > 7 mm **o** saturación > 75 % **o** alerta SMN naranja/roja | Anegamiento inminente: suspender movimientos no críticos |

**Lluvia de referencia** = `máx(acumulado últimas 24 h, pronóstico próximas 24 h)`.
Criterio conservador: si ya llovió el camino está comprometido; si va a llover hay
que anticipar.

### Índice continuo 0-100

Complemento numérico para tendencia y gauge en Power BI. No reemplaza al semáforo.

```
IIE = 0,55 × subíndice_lluvia + 0,45 × subíndice_suelo
      con piso impuesto por la alerta SMN (amarillo 50 / naranja 75 / rojo 90)
```

### Perspectiva 72 h

Además del estado actual, el sistema recorre el pronóstico hora por hora y reporta
**el peor nivel que se alcanzaría y cuándo**. Es la parte propiamente "temprana":
avisa con 24-72 h de anticipación, no cuando el camino ya se cortó.

---

## ⚠️ El parámetro que hay que calibrar: la humedad de suelo

Open-Meteo devuelve `soil_moisture_0_to_7cm` en **m³/m³** (contenido volumétrico),
no en porcentaje. La matriz está expresada en % de saturación, así que se normaliza
contra la porosidad total del suelo:

```
saturación_% = (soil_moisture / POROSIDAD_TOTAL) × 100
```

Con el valor calibrado **0,53 m³/m³**:

| Umbral de la matriz | Equivale a |
|---|---|
| 60 % de saturación | 0,318 m³/m³ |
| 75 % de saturación | 0,398 m³/m³ |

**Este es el único parámetro subjetivo del modelo, y define la frecuencia de
alertas.** El backtest sobre 3 años de datos observados (ERA5) da esta tabla de
decisión para Añelo Pueblo:

| Porosidad | Umbral rojo | % horas amarillo | % horas rojo | Días rojo/año |
|---:|---:|---:|---:|---:|
| 0,42 | 0,315 | 7,9 % | 8,7 % | 32 |
| 0,45 (valor teórico de greda) | 0,338 | 6,8 % | 7,4 % | 27 |
| 0,48 | 0,360 | 5,9 % | 6,5 % | 24 |
| 0,50 | 0,375 | 5,8 % | 5,4 % | 20 |
| **0,53** (adoptado) | **0,398** | **5,9 %** | **4,4 %** | **16** |
| 0,56 | 0,420 | 5,8 % | 3,4 % | 12 |

**Valor adoptado: 0,53.** El valor teórico de porosidad para greda de meseta
(0,42-0,48) sobrealertaba: producía 27-32 días al año en rojo, y en el backtest
generaba un episodio rojo continuo de 44 días en el invierno de 2026. Un semáforo
que está en rojo un mes seguido deja de ser mirado.

**Para recalibrar:** preguntarle a vialidad / operaciones cuántos días al año los
caminos están efectivamente cortados por barro y elegir la fila que coincida. Se
cambia sin tocar código, con la variable `IIE_POROSIDAD_TOTAL`.

Para regenerar la tabla:

```bash
python backtest.py --punto anelo_pueblo --calibracion
```

---

## Fuentes de datos

| Fuente | Endpoint | Auth | Uso |
|---|---|---|---|
| Open-Meteo | `api.open-meteo.com/v1/forecast` | No | Precipitación, humedad de suelo, temperatura, viento |
| Open-Meteo Archive | `archive-api.open-meteo.com/v1/archive` | No | Backtest sobre reanálisis ERA5 |
| SMN — feed CAP | `ssl.smn.gob.ar/CAP/AR.php` | **No** | Alertas oficiales con polígono geográfico |
| SMN — API interna | `ws1.smn.gob.ar/v1/weather/alerts` | Sí (JWT) | Fuente secundaria opcional |

> **Por qué CAP y no la API interna.** El endpoint `ws1.smn.gob.ar/v1/weather/alerts`
> que figuraba en la especificación original hoy responde **401 Unauthorized** sin un
> token JWT, y el token no es público. El feed **CAP** (Common Alerting Protocol,
> estándar OASIS/OMM) es la publicación oficial del SMN, es abierto, y además es
> *mejor* para este caso: cada aviso trae el **polígono exacto** de la zona afectada,
> así que se testea si las coordenadas de Añelo caen adentro en vez de hacer un match
> difuso por nombre de provincia. Si en el futuro se consigue el JWT, se carga como
> `SMN_API_TOKEN` y se suma como fuente secundaria.

Los avisos por **viento o zonda** se registran pero **no** elevan el semáforo: no
producen anegamiento. Solo cuentan lluvia, tormenta y nevada.

---

## Salidas

| Archivo | Contenido | Consumidor |
|---|---|---|
| `data/historico.csv` | Una fila por punto y por corrida. Serie temporal completa | **Power BI** (tabla de hechos) |
| `data/estado_actual.json` | Última foto del corredor, con disparadores y perspectiva 72 h | Tablero, notificaciones, API de facto |
| `data/pronostico_horario.csv` | Serie horaria 72 h atrás / 72 h adelante por punto | Power BI (gráfico de evolución) |
| `data/alertas_smn.csv` | Avisos CAP vigentes que tocan los puntos críticos | Power BI (detalle de alertas) |
| `docs/index.html` | Tablero autocontenido | GitHub Pages / celular en yacimiento |

## Portabilidad a un entorno solo-Microsoft

El sistema no depende de Python para operar: la matriz del IIE son cuatro
comparaciones numéricas y se expresa igual en Power Query o Power Automate.
La carpeta [`microsoft/`](microsoft/) tiene los dos caminos que no requieren
GitHub ni instalar nada:

| Archivo | Qué es |
|---|---|
| `01_IIE_Estado.m` | Consulta Power Query: semáforo, IIE y perspectiva 72 h. Se pega en el Editor avanzado de Power BI y funciona sola |
| `02_IIE_Serie_Horaria.m` | Serie horaria 72 h atrás / adelante para los gráficos |
| `03_Esquema_ParseJSON.json` | Esquema para la acción *Analizar JSON* de Power Automate |
| `04_Crear_Lista_SharePoint.ps1` | Crea las listas de SharePoint con los nombres internos correctos |
| `verificar_m.py` | Verificación estructural de los `.m` |
| `GUIA_MIGRACION.md` | Los tres caminos comparados y el flujo de Power Automate paso a paso |

En producción, Python solo hace falta para el backtest de calibración, que se
corre una vez por año.

La conexión desde Power BI está documentada en [`powerbi/GUIA_POWERBI.md`](powerbi/GUIA_POWERBI.md),
con las medidas DAX ya escritas.

---

## Uso local

```bash
pip install -r requirements.txt

python main.py              # corrida completa
python main.py --dry-run    # calcula y muestra, sin escribir ni notificar
python -m unittest discover -s tests -v

python backtest.py --calibracion              # validación histórica 3 años
python backtest.py --desde 2025-08-01 --hasta 2025-09-15 --csv evento.csv
```

---

## Decisiones de diseño

- **CSV en el repo en vez de base de datos.** Git ya es una base de datos versionada
  con historial, backup y control de acceso. Power BI lee la URL raw sin gateway ni
  credenciales. Costo cero real, no "capa gratuita hasta que crezca".
- **Ninguna excepción tumba la corrida.** Cada llamada HTTP tiene 3 reintentos con
  backoff; si un punto falla se registra y se sigue con los demás; si el SMN no
  responde, el semáforo se calcula igual con Open-Meteo. Solo aborta si ningún punto
  pudo evaluarse.
- **Concurrencia limitada a 4 conexiones** contra el SMN: con 8 el origen devuelve 522.
- **Tablero sin dependencias externas.** SVG generado a mano, datos embebidos, sin
  CDN: funciona en el celular con señal mala y abierto desde el disco.
- **Notificación solo ante cambio de nivel** (`IIE_NOTIFICAR_SOLO_CAMBIOS`), para que
  el canal no se vuelva ruido que la gente silencia.
- **Buffer de 0,02° (~2 km)** al testear contención en polígonos CAP: un camino a 2 km
  del límite de un aviso está igual de afectado, y evita el caso indefinido del punto
  justo sobre el borde de la grilla.

---

## Estructura

```
├── main.py                     Orquestador
├── backtest.py                 Validación histórica y calibración
├── requirements.txt
├── src/
│   ├── config.py               Todos los parámetros calibrables
│   ├── http_client.py          Reintentos y backoff
│   ├── openmeteo.py            Ingesta climática
│   ├── smn.py                  Feed CAP + point-in-polygon
│   ├── iie.py                  Matriz de riesgo e índice
│   ├── storage.py              CSV/JSON + Google Sheets opcional
│   ├── notifier.py             Teams / Telegram
│   └── dashboard.py            Tablero HTML
├── tests/test_iie.py           29 tests de la matriz y la geometría
├── .github/workflows/monitoreo.yml
├── data/                       Salidas (las escribe el bot)
├── docs/index.html             Tablero
└── powerbi/GUIA_POWERBI.md
```
