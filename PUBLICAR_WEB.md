# Publicar el tablero como página web normal

El objetivo: una URL común y corriente que cualquiera de la empresa abra desde
el navegador, sin instalar nada, sin licencia y sin permisos especiales.

El tablero ya está preparado para eso. Es un único archivo HTML **sin ninguna
dependencia externa** — verificado: cero scripts, hojas de estilo o imágenes
traídas de afuera. Los datos van embebidos en la propia página. Funciona con
señal mala en el yacimiento y hasta abierto desde un pendrive.

---

## Opción A — GitHub Pages (recomendada)

Ya está todo hecho: el workflow regenera `docs/index.html` en cada corrida y lo
commitea. Solo falta encender Pages.

1. Repositorio → **Settings → Pages**
2. **Source:** Deploy from a branch
3. **Branch:** `main`, carpeta **`/docs`** → Save
4. Esperar 1-2 minutos

La URL queda:

```
https://<usuario>.github.io/<repo>/
```

Se actualiza sola cada 2 horas, cuando el workflow commitea el HTML nuevo.
Quien la abre no necesita cuenta de GitHub ni saber qué es GitHub.

### ⚠️ Lo que hay que decidir antes: la página es pública

GitHub Pages en plan gratuito **sirve el sitio públicamente**, aunque el
repositorio sea privado. Cualquiera con la URL lo ve, y no hay contraseña.

Qué queda expuesto:

| Dato | Sensibilidad |
|---|---|
| Coordenadas de Añelo, Acceso Meseta y Tratayén | Son localidades y rutas públicas |
| Lluvia y humedad de suelo | Dato meteorológico público (Open-Meteo, SMN) |
| Semáforo de transitabilidad | **Revela postura operativa**: que hoy el corredor está restringido |
| Nombre del área y la operación | Aparece "Añelo — Vaca Muerta" en el encabezado |

Los datos meteorológicos son públicos. Lo que no es público es la **lectura
operativa**: una página que dice "corredor en rojo, suspender movimientos" le
cuenta a cualquiera cómo está funcionando la logística de arenas ese día.

**Antes de encender Pages, preguntar.** Es una decisión de la empresa, no
técnica. La página lleva `<meta name="robots" content="noindex, nofollow">`, que
evita que aparezca en Google, pero eso **no la protege**: quien tenga el link
entra.

Si la respuesta es que no puede ser pública, ir a la Opción B.

---

## Opción B — Cloudflare Pages con acceso restringido

Gratis, y con login corporativo. Requiere que IT habilite el dominio.

1. Cuenta en Cloudflare → **Workers & Pages → Create → Pages**
2. Conectar el repositorio de GitHub, o subir la carpeta `docs/` a mano
3. **Cloudflare Access** (Zero Trust) → crear una aplicación sobre ese dominio →
   política: permitir solo correos `@ypf.com`

Queda una URL normal que pide autenticación con el mail de la empresa. El plan
gratuito de Zero Trust cubre hasta 50 usuarios.

Es la mejor combinación de "página web normal" + "no la ve cualquiera". La
contra: es un tercero más que IT tiene que aprobar.

---

## Opción C — SharePoint (100 % interno)

Si la política es que nada salga del tenant:

1. Subir `docs/index.html` a una biblioteca de documentos del sitio del área
2. Página del sitio → web part **Insertar** → apuntar al archivo

**Advertencia realista:** SharePoint bloquea scripts personalizados en las
páginas modernas por defecto. Los gráficos del tablero son SVG generados con
JavaScript, así que **es probable que no se rendericen**. Habilitar scripts
personalizados requiere intervención del administrador del tenant y muchas
organizaciones no lo permiten por política de seguridad.

Si SharePoint es el único camino posible, lo razonable no es pelear con el HTML
sino **usar el informe de Power BI publicado en el área de trabajo** — que es
nativo, respeta los permisos del tenant y no necesita ningún permiso especial.
El tablero HTML queda entonces como vista rápida para el celular en yacimiento.

---

## Cuánto castiga esto a la API

Nada. La página es **estática**: el HTML ya trae los datos adentro cuando se
genera. Abrirla mil veces no genera una sola llamada a Open-Meteo.

Quien consulta la API es el workflow, una vez cada 2 horas:

| | Llamadas por corrida | Por día |
|---|---|---|
| Open-Meteo | 3 (una por punto) | 36 |
| Índice CAP del SMN | 1 | 12 |
| XML de avisos del SMN | ~34 (filtrados por evento) | ~410 |

Open-Meteo permite 10.000 llamadas diarias en su nivel gratuito sin API key:
36 es el 0,4 % del límite. Hay margen para bajar a corridas cada 30 minutos si
alguna vez hace falta, sin acercarse al techo.

El SMN es el más frágil de los dos: devuelve **HTTP 522** cuando se lo satura.
Por eso la descarga está limitada a 4 conexiones simultáneas y filtrada por tipo
de evento antes de bajar los archivos.

**La página se recarga sola cada 30 minutos** (`<meta http-equiv="refresh">`).
Como es estática, eso no toca ninguna API: solo vuelve a pedir el HTML a GitHub.

---

## El cartel de dato viejo

Si el workflow se rompe — se cae GitHub Actions, cambia la API, alguien revoca
un permiso — la página seguiría mostrando el último dato bueno, y nadie se
enteraría. Un tablero que miente en silencio es peor que no tener tablero.

Por eso el encabezado muestra la antigüedad real del dato, y **pasadas 3 horas**
aparece una franja roja arriba de todo:

> **Atención:** estos datos tienen más de 3 horas. La actualización automática
> puede haberse interrumpido — verificar antes de tomar una decisión operativa
> con esta información.

Está probado en ambos estados: con dato fresco el cartel está oculto y el
encabezado dice "hace N min"; simulando 5 horas de atraso, aparece la franja y
el encabezado pasa a "DATO DESACTUALIZADO · hace 5 h" en rojo.
