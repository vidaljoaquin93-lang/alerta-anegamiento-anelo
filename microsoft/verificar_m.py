#!/usr/bin/env python3
"""
Verificación estructural de los scripts Power Query M de este proyecto.

NO ejecuta M — el motor de Power Query solo existe dentro de Power BI / Excel
en Windows. Lo que sí hace es detectar la clase de errores que rompen un pegado
en el Editor avanzado y que son molestos de diagnosticar ahí adentro:

  - paréntesis, llaves o corchetes desbalanceados
  - bloques 'let' sin su 'in'
  - comas colgantes antes de un cierre
  - llamadas a funciones que no existen en la biblioteca estándar de M
    (el error clásico: Number.Max / Number.Min, que existen en Excel y en
     Power Automate pero NO en M, donde son List.Max / List.Min)

Uso:  python verificar_m.py 01_IIE_Estado.m 02_IIE_Serie_Horaria.m
"""

import re
import sys

# Funciones de la biblioteca estándar de M usadas por estos scripts.
CONOCIDAS = {
    "Web.Contents", "Json.Document",
    "Table.FromRecords", "Table.AddColumn", "Table.ExpandRecordColumn",
    "Table.ExpandTableColumn", "Table.SelectColumns", "Table.TransformColumnTypes",
    "List.Transform", "List.Sum", "List.Range", "List.Count", "List.Max",
    "List.Min", "List.PositionOf", "List.Select", "List.First", "List.RemoveNulls",
    "Text.Combine", "Text.From", "Number.Round",
    "DateTime.FromText", "DateTimeZone.UtcNow", "DateTimeZone.SwitchZone",
    "DateTimeZone.RemoveZone", "Date.Year", "Date.Month", "Date.Day",
    "Time.Hour", "Duration.TotalHours", "Int64.Type",
}

# Nombres que NO existen en M y que se escriben por costumbre de Excel, DAX
# o Power Automate. Si alguno aparece, el script falla al pegarlo.
INEXISTENTES = {
    "Number.Max", "Number.Min", "Number.ToText", "Text.ToNumber",
    "Number.Abs2", "List.Average2",
}


def limpiar(src: str) -> str:
    """
    Devuelve el código sin strings ni comentarios.

    El orden importa: los strings van PRIMERO. Una URL como
    https://api.open-meteo.com contiene '//', y si se quitaran los comentarios
    antes, se comería el resto de la línea junto con la comilla de cierre y
    todo el conteo posterior quedaría descuadrado.
    """
    sin_strings = re.sub(r'"(?:[^"\n]|"")*"', "@", src)
    return re.sub(r"//[^\n]*", "", sin_strings)


def verificar(ruta: str) -> list:
    with open(ruta, encoding="utf-8") as f:
        src = f.read()
    codigo = limpiar(src)
    errores = []

    # --- Balance de delimitadores, con la línea del primer descuadre ---
    for abre, cierra, nombre in (("(", ")", "paréntesis"),
                                 ("{", "}", "llaves"),
                                 ("[", "]", "corchetes")):
        profundidad = 0
        for nro, linea in enumerate(codigo.split("\n"), 1):
            profundidad += linea.count(abre) - linea.count(cierra)
            if profundidad < 0:
                errores.append(f"{nombre}: cierre de más en la línea {nro}")
                profundidad = 0
        if profundidad > 0:
            errores.append(f"{nombre}: quedan {profundidad} sin cerrar")

    # --- let / in ---
    lets = len(re.findall(r"\blet\b", codigo))
    ins = len(re.findall(r"\bin\b", codigo))
    if lets != ins:
        errores.append(f"'let' aparece {lets} veces e 'in' {ins}: deben coincidir")

    # --- Comas colgantes ---
    for m in re.finditer(r",\s*([)\]}])", codigo):
        nro = codigo[:m.start()].count("\n") + 1
        errores.append(f"coma colgante antes de '{m.group(1)}' en la línea {nro}")

    # --- Funciones ---
    usadas = set(re.findall(r"\b([A-Z][A-Za-z]*\.[A-Za-z][A-Za-z0-9]*)\b", codigo))
    malas = sorted(usadas & INEXISTENTES)
    if malas:
        errores.append(f"funciones que NO existen en M: {malas}")
    nuevas = sorted(usadas - CONOCIDAS - INEXISTENTES)
    if nuevas:
        errores.append(f"funciones no verificadas, revisar a mano: {nuevas}")

    return errores


def main() -> int:
    rutas = sys.argv[1:] or ["01_IIE_Estado.m", "02_IIE_Serie_Horaria.m"]
    fallas = 0
    for ruta in rutas:
        errores = verificar(ruta)
        if errores:
            fallas += 1
            print(f"[FALLA] {ruta}")
            for e in errores:
                print(f"    - {e}")
        else:
            print(f"[OK]    {ruta}")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
