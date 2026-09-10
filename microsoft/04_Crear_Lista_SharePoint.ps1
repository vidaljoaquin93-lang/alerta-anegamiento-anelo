<#
===============================================================================
 Crea las listas de SharePoint que usa el Camino 2 (Power Automate).

 POR QUÉ UN SCRIPT Y NO CLICS
 En SharePoint, el nombre interno de una columna se congela en el momento de
 crearla y NO cambia si después se renombra la columna. Si se crea "Saturación
 %" desde la interfaz, el nombre interno queda como
 "Saturaci_x00f3_n_x0020__x0025_" y todas las expresiones del flujo tienen que
 usar ESE texto. Crear las columnas con nombres ASCII sin espacios evita el
 problema entero.

 REQUISITO
   Install-Module PnP.PowerShell -Scope CurrentUser
 Si la política de la empresa bloquea la instalación del módulo, crear las
 columnas a mano respetando EXACTAMENTE los nombres de la tabla del final:
 sin acentos, sin espacios, sin símbolos.

 USO
   .\04_Crear_Lista_SharePoint.ps1 -SitioUrl "https://<tenant>.sharepoint.com/sites/<sitio>"
===============================================================================
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$SitioUrl,

    [string]$ListaHistorico = "IIE_Historico",
    [string]$ListaAlertas   = "IIE_AlertasSMN"
)

$ErrorActionPreference = "Stop"

Write-Host "Conectando a $SitioUrl ..." -ForegroundColor Cyan
Connect-PnPOnline -Url $SitioUrl -Interactive

# ---------------------------------------------------------------------------
# Lista principal: histórico del IIE
# ---------------------------------------------------------------------------
function New-ListaSiNoExiste {
    param([string]$Nombre, [string]$Descripcion)

    $existente = Get-PnPList -Identity $Nombre -ErrorAction SilentlyContinue
    if ($null -ne $existente) {
        Write-Host "  La lista '$Nombre' ya existe. No se toca." -ForegroundColor Yellow
        return $false
    }
    New-PnPList -Title $Nombre -Template GenericList -OnQuickLaunch | Out-Null
    Set-PnPList -Identity $Nombre -Description $Descripcion
    Write-Host "  Lista '$Nombre' creada." -ForegroundColor Green
    return $true
}

function Add-Columna {
    param(
        [string]$Lista,
        [string]$Nombre,
        [string]$Tipo,        # Text, Number, DateTime, Note, Choice
        [int]$Decimales = -1,
        [string[]]$Opciones = @()
    )

    $ya = Get-PnPField -List $Lista -Identity $Nombre -ErrorAction SilentlyContinue
    if ($null -ne $ya) {
        Write-Host "    - $Nombre (ya existía)" -ForegroundColor DarkGray
        return
    }

    if ($Tipo -eq "Choice") {
        Add-PnPField -List $Lista -DisplayName $Nombre -InternalName $Nombre `
                     -Type Choice -Choices $Opciones -AddToDefaultView | Out-Null
    }
    else {
        Add-PnPField -List $Lista -DisplayName $Nombre -InternalName $Nombre `
                     -Type $Tipo -AddToDefaultView | Out-Null
    }

    if ($Decimales -ge 0) {
        Set-PnPField -List $Lista -Identity $Nombre `
                     -Values @{ DisplayFormat = $Decimales }
    }
    Write-Host "    - $Nombre ($Tipo)" -ForegroundColor Gray
}

Write-Host "`n[1/2] Lista de histórico" -ForegroundColor Cyan
New-ListaSiNoExiste -Nombre $ListaHistorico `
    -Descripcion "Serie del Indice de Intransitabilidad (IIE) - Anelo. La escribe el flujo de Power Automate cada 2 h." | Out-Null

# La columna Title que viene por defecto se reutiliza como PuntoId.
Set-PnPField -List $ListaHistorico -Identity "Title" -Values @{ Title = "PuntoId" }

Add-Columna -Lista $ListaHistorico -Nombre "Punto"                -Tipo Text
Add-Columna -Lista $ListaHistorico -Nombre "Timestamp"            -Tipo DateTime
Add-Columna -Lista $ListaHistorico -Nombre "Nivel"                -Tipo Choice -Opciones @("verde","amarillo","rojo")
Add-Columna -Lista $ListaHistorico -Nombre "NivelOrden"           -Tipo Number -Decimales 0
Add-Columna -Lista $ListaHistorico -Nombre "IIE"                  -Tipo Number -Decimales 1
Add-Columna -Lista $ListaHistorico -Nombre "PrecipReferenciaMm"   -Tipo Number -Decimales 2
Add-Columna -Lista $ListaHistorico -Nombre "PrecipAcum24hMm"      -Tipo Number -Decimales 2
Add-Columna -Lista $ListaHistorico -Nombre "PrecipPron24hMm"      -Tipo Number -Decimales 2
Add-Columna -Lista $ListaHistorico -Nombre "PrecipPron72hMm"      -Tipo Number -Decimales 2
Add-Columna -Lista $ListaHistorico -Nombre "HumedadSueloM3M3"     -Tipo Number -Decimales 3
Add-Columna -Lista $ListaHistorico -Nombre "SaturacionSueloPct"   -Tipo Number -Decimales 1
Add-Columna -Lista $ListaHistorico -Nombre "AlertaSmnColor"       -Tipo Text
Add-Columna -Lista $ListaHistorico -Nombre "NivelPronosticado72h" -Tipo Text
Add-Columna -Lista $ListaHistorico -Nombre "PicoPrecip24hMm"      -Tipo Number -Decimales 1
Add-Columna -Lista $ListaHistorico -Nombre "Disparadores"         -Tipo Note

# Índice sobre Timestamp: sin esto, cuando la lista pase los 5.000 elementos
# (unos 4 meses a 3 puntos cada 2 h) las consultas ordenadas por fecha empiezan
# a fallar por el límite de vista de SharePoint.
Write-Host "  Creando indice en Timestamp ..." -ForegroundColor Gray
Add-PnPFieldToContentType -Field "Timestamp" -ContentType "Item" -ErrorAction SilentlyContinue | Out-Null
Set-PnPField -List $ListaHistorico -Identity "Timestamp" -Values @{ Indexed = $true }

# ---------------------------------------------------------------------------
# Lista secundaria: alertas del SMN
# ---------------------------------------------------------------------------
Write-Host "`n[2/2] Lista de alertas SMN" -ForegroundColor Cyan
New-ListaSiNoExiste -Nombre $ListaAlertas `
    -Descripcion "Avisos CAP del Servicio Meteorologico Nacional vigentes sobre los puntos criticos." | Out-Null

Set-PnPField -List $ListaAlertas -Identity "Title" -Values @{ Title = "Identificador" }

Add-Columna -Lista $ListaAlertas -Nombre "PuntoId"      -Tipo Text
Add-Columna -Lista $ListaAlertas -Nombre "Evento"       -Tipo Text
Add-Columna -Lista $ListaAlertas -Nombre "SeveridadCap" -Tipo Text
Add-Columna -Lista $ListaAlertas -Nombre "ColorSmn"     -Tipo Text
Add-Columna -Lista $ListaAlertas -Nombre "Inicio"       -Tipo DateTime
Add-Columna -Lista $ListaAlertas -Nombre "Expira"       -Tipo DateTime
Add-Columna -Lista $ListaAlertas -Nombre "Descripcion"  -Tipo Note
Add-Columna -Lista $ListaAlertas -Nombre "Url"          -Tipo Text

Write-Host "`nListo." -ForegroundColor Green
Write-Host "Nombres internos = nombres visibles (sin acentos ni espacios)."
Write-Host "Usalos tal cual en las acciones 'Crear elemento' del flujo."

Disconnect-PnPOnline
