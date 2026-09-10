# wix-google-sheets-sync
Script en Python para automatizar la carga de catálogo en Wix Stores. Lee productos desde Google Sheets, extrae datos de compatibilidad de vehículos (fitment) haciendo scraping en dos sitios web, y sincroniza inventario vía REST API.

## Proyecto de automatización de tareas
La idea de desarrollar este código nació cuando estaba subiendo productos manualmente a Wix, leyendo los datos desde una planilla en Google Sheets y de repente pensé "Esto se puede automatizar". Por cada producto, tenía que copiar el título, el SKU, memorizar precios de costo y venta para después volcarlos en los campos correspondientes de la plataforma; todo esto implicaba cambiar de pestaña de forma alternada, invirtiendo una cantidad de tiempo considerable en tareas repetitivas (además de que luego tengo que hacer la edición de las imágenes, redacción de descripciones y búsqueda del diagrama de partes). 

## Características Principales
- Integración con Google Workspace: Conexión segura a la API de Google Sheets mediante OAuth2 para leer las filas de nuevos listados.
- Web Scraping: Extracción automatizada de compatibilidad de vehículos (fitment) con el producto, consultando dos sitios web.
- Sincronización con Wix: Carga e inserción automática de datos del catálogo a través de REST API.

### Lenguaje
- Python 3

### Librerías / dependencias externas
- requests → para peticiones HTTP
- beautifulsoup4 (bs4) → para parsear el HTML de las páginas de donde se extrae información
- python-dotenv → para cargar las credenciales de Wix desde un archivo .env
- google-auth, google-auth-oauthlib, google-api-python-client → para autenticarse y consultar la API de Google Sheets (OAuth 2.0)

### Librerías nativas de Python (no requieren instalación)
- re → para manipular expresiones regulares 
- time → para pausas entre requests
- os / os.path → para manejo de archivos y variables de entorno

### APIs externas integradas
- Google Sheets API v4 → para la lectura de la planilla de productos
- Wix Stores API (v1/v2) → para la creación de productos y actualización de inventario

### Web scraping
Dos sitios web de terceros, consultados vía scraping para obtener aquellos vehículos compatibles con los productos.

## Documentación de funciones
**Función obtener_servicio_sheets()**: su objetivo es devolver un objeto de servicio ('sheets') para interactuar con la API de Google Sheets.
Si existe token.json en el directorio actual, se cargan las credenciales guardadas en creds.
Si el token cargado no es válido, se intenta renovar (si hay refresh_token disponible).
Si no existe token.json, o el token no se pudo renovar, se fuerza un login completo al usuario.
El token resultante se guarda en token.json y luego se pasa como parámetro a build() para construir y devolver el objeto de servicio.

**Función obtener_datos(spreadsheet_id, fila_inicio, fila_fin)**: lee las filas de la hoja 'New Listings' en el rango indicado.
Ubica cada columna por su nombre de encabezado, no por posición fija, para tolerar cambios de orden en la hoja.
Por cada fila válida, limpia y extrae título, SKU, costo, stock y precio.
Determina si el SKU tiene un formato de 7 u 11 dígitos para buscar el fitment correspondiente.
Muestra los datos en consola y llama a procesar_producto_completo() para crear el producto en Wix.

**Función cargar_filas_procesadas()**: lee el archivo donde se registran los índices de las filas ya procesadas anteriormente, para evitar volver a subirlas en corridas futuras.

**Función obtener_fitment_para_wix(sku_limpio)**: recibe como parámetro el sku extraído de cada producto.
Con este dato, busca los modelos compatibles con el producto en el primer sitio web. Si no lo encuentra allí, prueba en el segundo.
Si encuentra resultados, retorna un listado de los modelos en formato string.
Si no encuentra nada en ninguna de las dos, retorna un string vacío.

**Función armar_info_adicional_fitment(fitment_texto)**: transforma el string del fitment (el texto plano que devuelve obtener_fitment_para_wix) en la estructura de datos que Wix espera para mostrar una "sección de información adicional (Info Section)" en la ficha del producto.
Si hay fitment, devuelve una lista con un diccionario {"title": "Fitment", "description": <texto en HTML>}.
Si no hay fitment (texto vacío), devuelve una lista vacía.

**Función interpretar_stock(valor_stock)**: recibe como parámetro el stock leído del producto y determina si se debe cuantificar el stock con un número exacto, dejarlo en "disponible (in stock)", o marcarlo como "pre order".
Devuelve una tupla: (diccionario con los datos de inventario para Wix, booleano que indica si necesita pre order).
Si es pre order, la función que la llama (procesar_producto_completo) imprime un aviso por consola, ya que el pre order debe activarse manualmente en Wix.

**Función probar_conexion_wix()**: verifica que las credenciales de la API de Wix (API Key y Site ID) funcionen correctamente. 
Para esto, envía una petición HTTP pidiendo los primeros 5 productos de la tienda.
Imprime por consola el status code y la respuesta completa, para que uno mismo confirme si la conexión fue exitosa o si hubo algún error.

**Función limpiar_numero(valor)**: recibe cualquier valor que represente un número que puede venir "sucio" (con texto extra, símbolos de moneda, comas, espacios, etc.) y lo convierte en un número decimal (float) limpio y utilizable.

**Función crear_producto_wix(titulo, sku, costo, precio, fitment)**: envía una petición HTTP del tipo POST al servidor para crear un producto en Wix oculto.
Para eso, envía en el payload todos los datos del producto correspondiente, dentro de la clave "product".
Si el producto se crea correctamente, imprime su ID por consola y lo retorna (para usarlo, por ejemplo, al actualizar el inventario).
Si falla, imprime un mensaje de error con el detalle de la respuesta del servidor y retorna None.

**Función actualizar_inventario_wix(product_id, stock_data)**: actualiza el inventario de un producto que ya existe en Wix.
En Wix Stores, el producto y el inventario son dos "recursos" separados dentro de la API: al crear un producto(con crear_producto_wix), 
Wix le asigna un inventario vacío/por defecto. Esta función usa el product_id ya generado para actualizar ese inventario con los datos.

**Función procesar_producto_completo(titulo, sku, costo, stock, precio, fitment)**: es la función orquestadora.
Llama a las funciones definidas previamente para procesar un producto de punta a punta.
Si creó el producto correctamente, actualiza su inventario con los datos interpretados.
Si no puede crearse el producto, se termina su ejecución. En caso de que el producto indique "Pre order", se imprime un mensaje por pantalla para activar esa opción manualmente en Wix, ya que no es posible hacerlo mediante código.

> Nota: para funcionar, el proyecto requiere un archivo `.env` con las variables `WIX_API_KEY`, `WIX_SITE_ID` y `SPREADSHEET_ID`, y un archivo `credentials.json` de Google Cloud (OAuth) en la misma carpeta.

## Conclusión
A partir del desarrollo de esta automatización, comencé a analizar de manera más rigurosa si determinadas tareas o procesos pueden ser automatizados, por lo que realmente amplió mi perspectiva sobre la identificación de patrones que pueden traducirse a un script permitiendo así reducir el tiempo que se necesita en tareas repetitivas. Además, no deja de resultarme impactante como la Inteligencia Artificial sirve como un recurso muy valioso durante el proceso de aprendizaje. Definitivamente, esta experiencia reforzó mi interés por la automatización y quiero seguir aprendiendo.
