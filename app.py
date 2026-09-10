import os.path
import re
import requests
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

load_dotenv()

# Credenciales cargadas desde el archivo .env
WIX_API_KEY = os.getenv("WIX_API_KEY")
WIX_SITE_ID = os.getenv("WIX_SITE_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# URLs para scraping cargadas desde el archivo .env
URL_RO = os.getenv("URL_RO")
URL_B = os.getenv("URL_B")

# Headers para las peticiones a la API de Wix
HEADERS_WIX = {"Authorization": WIX_API_KEY, "wix-site-id": WIX_SITE_ID, "Content-Type": "application/json"}

# Archivo local donde se registran las filas ya subidas para no reprocesarlas
ARCHIVO_PROCESADOS = "filas_ya_subidas.txt"

# Límites de longitud que exige la API de Wix
MAX_LARGO_TITULO = 80
MAX_LARGO_SKU = 40

# Función obtener_servicio_sheets(): su objetivo es devolver un objeto de servicio ('sheets') para interactuar con la API de Google Sheets.
def obtener_servicio_sheets():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # El refresh_token dejó de ser válido 
                creds = None  # fuerza a caer al login completo

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)

# Función obtener_datos(spreadsheet_id, fila_inicio, fila_fin): lee las filas de la hoja 'New Listings' en el rango indicado. 
# Muestra los datos en consola y llama a procesar_producto_completo() para crear el producto en Wix.
def obtener_datos(spreadsheet_id, fila_inicio, fila_fin):
    service = obtener_servicio_sheets()
    sheet = service.spreadsheets()

    rango_encabezados = "'New Listings'!A1:L1"

    try:
        result_encabezados = sheet.values().get(spreadsheetId=spreadsheet_id, range=rango_encabezados).execute()
    except HttpError as e:
        print(f"Error al leer encabezados de Google Sheets: {e}")
        return

    encabezados = result_encabezados.get('values', [[]])[0]

    # Mapeamos nombre de columna -> índice, buscando cada nombre en encabezados
    try:
        idx_titulo = encabezados.index("Item")      
        idx_sku    = encabezados.index("SKU")
        idx_costo  = encabezados.index("COST")
        idx_stock  = encabezados.index("QTY")
        idx_precio = encabezados.index("Price")
    except ValueError as e:
        print(f"Error: la estructura de la hoja 'New Listings' cambió ({e}).")
        print(f"Encabezados actuales: {encabezados}")
        return

    rango_datos = f"'New Listings'!A{fila_inicio}:L{fila_fin}"

    try:
        result_datos = sheet.values().get(spreadsheetId=spreadsheet_id, range=rango_datos).execute()
    except HttpError as e:
        print(f"Error al leer datos de Google Sheets: {e}")
        return

    filas = result_datos.get('values', [])

    filas_procesadas = cargar_filas_procesadas()

    print("\n================ PROCESANDO PRODUCTOS ================\n")

    for idx, fila in enumerate(filas, start=fila_inicio):
        if not fila:
            continue

        if str(idx) in filas_procesadas:
            print(f"Fila {idx} ya fue subida anteriormente, se saltea.")
            continue

        try:
            print(f"--- FILA {idx} ---")

            titulo = fila[idx_titulo] if len(fila) > idx_titulo and fila[idx_titulo] else "Sin Descripción"
            sku    = fila[idx_sku]    if len(fila) > idx_sku    and fila[idx_sku]    else f"SIN-SKU-{idx}"
            costo  = fila[idx_costo]  if len(fila) > idx_costo  and fila[idx_costo]  else "0"
            stock  = fila[idx_stock]  if len(fila) > idx_stock  and fila[idx_stock]  else "1"
            precio = fila[idx_precio] if len(fila) > idx_precio and fila[idx_precio] else "1"

            titulo_limpio = titulo.strip()

            if len(titulo_limpio) > MAX_LARGO_TITULO:
                print(f"⚠️ Título recortado (tenía {len(titulo_limpio)} caracteres)")
                titulo_limpio = titulo_limpio[:MAX_LARGO_TITULO].rstrip()

            sku_extraido  = sku.strip() 

            if len(sku_extraido) > MAX_LARGO_SKU:
                print(f"⚠️ SKU recortado (tenía {len(sku_extraido)} caracteres): {sku_extraido}")
                sku_extraido = sku_extraido[:MAX_LARGO_SKU].rstrip()

            sku_sin_separadores = re.sub(r'[\s\-/]', '', sku_extraido)

            if sku_sin_separadores.isdigit() and len(sku_sin_separadores) in (7, 11):
                fitment = obtener_fitment_para_wix(sku_sin_separadores)
            else:
                fitment = ""
                print(f"SKU '{sku_extraido}' no tiene 7 ni 11 números puros; no se buscará fitment.")

            print(f"ITEM (TÍTULO): {titulo_limpio}")
            print(f"SKU:           {sku_extraido}")
            print(f"QTY (STOCK):   {stock}")
            print(f"COST:          {costo}")
            print(f"PRICE:         {precio}")
            print(f"FITMENT:       {fitment}")

            exito = procesar_producto_completo(titulo_limpio, sku_extraido, costo, stock, precio, fitment)

            if exito:
                with open(ARCHIVO_PROCESADOS, "a", encoding="utf-8") as f:
                    f.write(str(idx) + "\n")

        except Exception as e:
            print(f"❌ Error inesperado procesando fila {idx}: {e}")
            continue

        print("-" * 50 + "\n")

# Función cargar_filas_procesadas(): lee el archivo donde se registran los índices de las filas ya procesadas anteriormente, 
# para evitar volver a subirlas en corridas futuras.
def cargar_filas_procesadas():
    if not os.path.exists(ARCHIVO_PROCESADOS):
        return set()
    with open(ARCHIVO_PROCESADOS, "r", encoding="utf-8") as f:
        return set(linea.strip() for linea in f if linea.strip())

# Función obtener_fitment_para_wix(sku_limpio): recibe como parámetro el sku extraído de cada producto 
# y busca los modelos compatibles con el producto en el sitio web RO. Si no lo encuentra allí, prueba en B.
def obtener_fitment_para_wix(sku_limpio):
    headers_generico = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # ---------- 1) 1er intento: RO ----------
    try:
        url_ro = f"{URL_RO}?q={sku_limpio}"
        response = requests.get(url_ro, headers=headers_generico, timeout=10)

        if response.status_code not in (403, 429):
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            resultados_div = soup.find('div', class_='partSearchResults')

            if resultados_div and "was found on the following vehicles" in resultados_div.get_text():
                vehiculos = [a.get_text(strip=True) for a in resultados_div.find_all('a')]

                if vehiculos:
                    return "Fits the following vehicles:\n" + "\n".join(vehiculos)

    except requests.RequestException:
        pass

    time.sleep(0.5)

    # ---------- 2) 2do intento: B ----------
    try:
        params = {"showus": "on", "showeur": "on", "part": sku_limpio}
        response = requests.get(URL_B, params=params, headers=headers_generico, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        for br in soup.find_all("br"):
            br.replace_with("\n")

        texto_completo = soup.get_text()

        if "was not found" not in texto_completo:
            lineas = texto_completo.splitlines()
            lineas_fitment = []
            capturando = False
            primer_grupo = True

            for linea in lineas:
                linea_str = linea.strip()

                if "was found on the following vehicles:" in linea_str:
                    capturando = True
                    continue

                if capturando:
                    if "Details for all" in linea_str or "Search another part" in linea_str:
                        break

                    if linea_str and ": Details on " in linea_str:
                        if not primer_grupo:
                            lineas_fitment.append("")
                        primer_grupo = False
                        lineas_fitment.append(linea_str)

                    elif linea_str and re.match(r'^[A-Z0-9]+\s+', linea_str):
                        lineas_fitment.append(linea_str)

            if lineas_fitment:
                return "Fits the following vehicles:\n" + "\n".join(lineas_fitment)

    except requests.RequestException:
        pass

    # ---------- 3) Si no está en ninguna de las dos ----------
    return ""

# Función armar_info_adicional_fitment(fitment_texto): transforma el string del fitment (el texto plano que devuelve obtener_fitment_para_wix) 
# en la estructura de datos que Wix espera para mostrar una "sección de información adicional (Info Section)" en la ficha del producto.
def armar_info_adicional_fitment(fitment_texto):
    """Convierte el texto de fitment en el formato de sección que espera Wix."""
    if not fitment_texto:
        return []

    descripcion_html = fitment_texto.replace("\n", "<br>")
    return [
        {
            "title": "Fitment",
            "description": descripcion_html
        }
    ]

# Función interpretar_stock(valor_stock): recibe como parámetro el stock leído del producto 
# y determina si se debe cuantificar el stock con un número exacto, dejarlo en "disponible (in stock)", o marcarlo como "pre order".
def interpretar_stock(valor_stock):
    texto = str(valor_stock).strip().lower()

    if "pre order" in texto or "preorder" in texto:
        return (
            {"trackQuantity": False, "inStock": True},
            True  # necesita preorder
        )

    if texto in ("stock", "in stock", "disponible"):
        return (
            {"trackQuantity": False, "inStock": True},
            False
        )

    try:
        cantidad = int(re.sub(r'\D', '', texto))
    except ValueError:
        cantidad = 0

    return (
        {"trackQuantity": True, "quantity": cantidad, "inStock": cantidad > 0},
        False
    )

# Función probar_conexion_wix(): verifica que las credenciales de la API de Wix (API Key y Site ID) funcionen correctamente. 
def probar_conexion_wix():
    url = "https://www.wixapis.com/stores/v1/products/query"
    payload = {
        "query": {
            "paging": {"limit": 5}
        }
    }

    response = requests.post(url, json=payload, headers=HEADERS_WIX, timeout=15)

    print("STATUS CODE:", response.status_code)
    print("RESPUESTA:", response.text)

# Función limpiar_numero(valor): recibe cualquier valor que represente un número que puede venir "sucio" 
# y lo convierte en un número decimal (float) limpio y utilizable.
def limpiar_numero(valor):
    texto = str(valor).strip()
    texto = re.sub(r'[^\d.]', '', texto)
    try:
        return float(texto)
    except ValueError:
        return 0.0

# Función crear_producto_wix(titulo, sku, costo, precio, fitment): envía una petición HTTP del tipo POST al servidor para crear un producto en Wix oculto.
def crear_producto_wix(titulo, sku, costo, precio, fitment):
    payload = {
        "product": {
            "name": titulo,
            "sku": sku,
            "productType": "physical",
            "visible": False,
            "priceData": {"price": limpiar_numero(precio)},
            "costAndProfitData": {"itemCost": limpiar_numero(costo)},
            "additionalInfoSections": armar_info_adicional_fitment(fitment)
        }
    }

    url = "https://www.wixapis.com/stores/v1/products"

    try:
        response = requests.post(url, json=payload, headers=HEADERS_WIX, timeout=15)
        response.raise_for_status()
        data = response.json()
        product_id = data.get("product", {}).get("id")
        print(f"✅ Producto creado (oculto): {titulo} | ID: {product_id}")
        return product_id

    except requests.RequestException as e:
        print(f"❌ Error al crear producto '{titulo}': {e}")
        if e.response is not None:
            print("Detalle:", e.response.text)
        return None

# Función actualizar_inventario_wix(product_id, stock_data): actualiza el inventario de un producto que ya existe en Wix.
def actualizar_inventario_wix(product_id, stock_data, titulo=""):

    url = f"https://www.wixapis.com/stores/v2/inventoryItems/product/{product_id}"

    payload = {
        "inventoryItem": {
            "trackQuantity": stock_data["trackQuantity"],
            "variants": [
                {
                    "variantId": "00000000-0000-0000-0000-000000000000",
                    "inStock": stock_data["inStock"],
                    "quantity": stock_data.get("quantity", 0)
                }
            ]
        }
    }

    try:
        response = requests.patch(url, json=payload, headers=HEADERS_WIX, timeout=15)
        response.raise_for_status()
        print("✅ Inventario actualizado")
        return response.json()
    except requests.RequestException as e:
        print(f"Error al actualizar inventario de '{titulo}' (ID: {product_id}): {e}")
        if e.response is not None:
            print("Detalle:", e.response.text)
        return None

# Llama función procesar_producto_completo(titulo, sku, costo, stock, precio, fitment):
def procesar_producto_completo(titulo, sku, costo, stock, precio, fitment):
    stock_data, necesita_preorder = interpretar_stock(stock)

    product_id = crear_producto_wix(titulo, sku, costo, precio, fitment)
    if not product_id:
        return False

    actualizar_inventario_wix(product_id, stock_data, titulo)

    if necesita_preorder:
        print(f"⚠️ ATENCIÓN: '{titulo}' necesita 'Pedido anticipado' — activalo manualmente en Wix.")

    return True

if __name__ == "__main__":
    obtener_datos(SPREADSHEET_ID, 888, 888)