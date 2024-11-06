import pandas as pd
import zipfile
import os
import re
import json
from datetime import datetime
import psycopg2
from psycopg2 import Error
import logging
import subprocess
from funcionesExternas import *
import mysql.connector
from mysql.connector import Error

# Variables globales
workng_dir = None
sandbx = None
reportes = None
db_config = None
columnas_esperadas = {}
reportes_selec = []
dms_name = None
clients_path = None

def configurar_logging(cliente_numero, clients_path):
    # Crear la carpeta de logs si no existe
    logs_dir = os.path.join(clients_path, cliente_numero, 'Logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Crear el nombre del archivo de log basado en la fecha actual
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(logs_dir, f'log_{fecha_actual}.txt')
    
    # Crear un manejador de archivo 
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    
    # Crear un manejador de consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Configurar el formato del logging
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Obtener el logger raíz
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Limpiar cualquier manejador previo para evitar duplicados
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Añadir los manejadores al logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def cargar_reportes(cliente_numero, path_client):
    ruta_config = os.path.join(path_client, cliente_numero,  cliente_numero + '.json')

    with open(ruta_config, 'r') as file:
        config_data = json.load(file)
    
    global reportes
    reportes = []
    for registro in config_data['registros']:
        dms_data = registro.get('dms', {})
        for reportes_lista in dms_data.values():
            reportes.extend(reportes_lista)
    
    reportes = [''.join(filter(str.isalpha, reporte)) for reporte in reportes]
    
    return reportes

def obtener_columnas_esperadas(dms_name, reporte_name, clients_path):
    dms_path = os.path.join(clients_path, 'dms', f'{dms_name}.json')
    
    if not os.path.exists(dms_path):
        logging.error(f"No se encontró el archivo {dms_path} para el DMS {dms_name}.")
        return None

    with open(dms_path, 'r') as file:
        dms_data = json.load(file)
    
    # Obtener columnas y columnas_export
    columnas = dms_data.get('columnas_esperadas', {}).get(reporte_name, {}).get('columnas', [])
    columnas_export = dms_data.get('columnas_esperadas', {}).get(reporte_name, {}).get('columnas_export', [])

    if not columnas:
        logging.warning(f"No se encontraron columnas esperadas para el reporte {reporte_name} en el DMS {dms_name}.")
    
    return columnas, columnas_export

def encontrar_zip(carpeta):
    for archivo in os.listdir(carpeta):
        if archivo.endswith('.zip'):
            return os.path.join(carpeta, archivo)
    raise FileNotFoundError("No se encontró ningún archivo ZIP en la carpeta de trabajo.")

# Función para inferir el tipo de dato de una columna
def inferir_tipo_dato(nombre_columna, dms_name, reporte_name, clients_path):
    """
    Esta función devuelve el tipo de dato almacenado en la llave 'tipo' del JSON del DMS para la columna especificada.
    Si el tipo de dato es 'varchar', también incluye la longitud especificada en la llave 'length'.
    """
    # Obtener el data_type del DMS para la columna
    dms_path = os.path.join(clients_path, 'dms', f'{dms_name}.json')
    
    if not os.path.exists(dms_path):
        logging.error(f"No se encontró el archivo {dms_path} para el DMS {dms_name}.")
        return 'VARCHAR(255)'  # Devolver un tipo por defecto en caso de error

    with open(dms_path, 'r') as file:
        dms_data = json.load(file)
    
    # Obtener el diccionario de tipos de datos
    data_types = dms_data.get('columnas_esperadas', {}).get(reporte_name, {}).get('data_types', {})

    nombre_columna_limpio = re.sub(r'\s*\(.*?\)', '', nombre_columna).strip()
    columna_info = None

    # Verificar si la columna existe tal cual en el JSON
    if nombre_columna in data_types:
        columna_info = data_types[nombre_columna]
    else:
        # Buscar columnas que contengan el nombre limpio
        for key in data_types:
            if key.startswith(nombre_columna_limpio):
                columna_info = data_types[key]
                break

    # Si no se encuentra la columna, devolver un tipo de dato por defecto
    if not columna_info:
        logging.warning(f"No se encontró información de tipo de dato para la columna: {nombre_columna}")
        return 'VARCHAR(255)'

    # Obtener el tipo de dato
    tipo_dato = columna_info.get('tipo', 'VARCHAR(255)')
    
    # Si el tipo de dato es 'varchar', incluir la longitud
    if tipo_dato == 'varchar':
        longitud = columna_info.get('length', 255)
        tipo_dato = f'{tipo_dato}({longitud})'
    
    elif tipo_dato == 'decimal':
        longitud = columna_info.get('length')
        precision_escala = longitud.replace(' ', '')
        tipo_dato = f'{tipo_dato}({precision_escala})'

    return tipo_dato


# Extraer información del archivo ZIP
def extraer_info_zip(nombre_zip):
    nombre_sin_ext = os.path.splitext(os.path.basename(nombre_zip))[0]
    cliente = nombre_sin_ext[:4]
    sucursal = nombre_sin_ext[4:6]
    fecha_zip = nombre_sin_ext[6:]
    fecha_actual = datetime.now().strftime('%d/%m/%Y')
    with open(os.path.join(sandbx, 'Client.txt'), 'w', encoding='utf-8') as f:
        f.write(cliente)
    with open(os.path.join(sandbx, 'Branch.txt'), 'w', encoding='utf-8') as f:
        f.write(sucursal)
    with open(os.path.join(sandbx, 'Fecha.txt'), 'w', encoding='utf-8') as f:
        f.write(fecha_actual)
    return cliente, sucursal, fecha_actual

def procesar_archivo_zip():
    global workng_dir, sandbx, db_config, columnas_esperadas, reportes_selec, dms_name, clients_path

    config = get_odoo_config()

    if config:
        db_config = {
            'host': config.get('my_module.host'),
            'usuario': config.get('my_module.user'),
            'contrasena': config.get('my_module.password'),
            'base_de_datos': config.get('my_module.bd_name')
        }

        clients_path = config.get('my_module.clients_folder_path')
        workng_dir = config.get('my_module.working_folder_path')
        sandbx = config.get('my_module.sandbox_folder_path')

        if not all([db_config['host'], db_config['usuario'], db_config['contrasena'], db_config['base_de_datos'], workng_dir, sandbx]):
            raise ValueError("Algunas variables de configuración faltan o están incompletas.")

        print(f"DB Config: {db_config}")
        print(f"Working Directory: {workng_dir}")
        print(f"Sandbox Directory: {sandbx}")
        print(f'Clients_path: {clients_path}')

    else:
        logging.error("No se pudo obtener la configuración de Odoo.")

    limpiar_carpeta(sandbx)
    
    for file_name in os.listdir(workng_dir):
        if file_name.endswith('.zip'):
            nombre_zip = file_name
            break
            
    else:
        logging.error("No se encontraron archivos .zip en el directorio.")
        return
    
    cliente_numero = nombre_zip[0:4].lstrip('0')
    
    #Cargan los logs
    configurar_logging(cliente_numero, clients_path)
    logging.info("<--------------- Inicia el proceso --------------->")
    
    cargar_reportes(cliente_numero, clients_path)
    
    ruta_config = os.path.join(clients_path, cliente_numero,  cliente_numero + '.json')
    with open(ruta_config, 'r') as file:
        config_data = json.load(file)

    for registro in config_data['registros']:
        dms_data = registro.get('dms', {})
        for dms_name, reportes_lista in dms_data.items():
            for reporte_name in reportes_lista:
                columnas = obtener_columnas_esperadas(dms_name, reporte_name, clients_path)
                columnas_esperadas[reporte_name] = columnas


    reportes_selec = list(columnas_esperadas.keys())
    
    if not workng_dir or not sandbx or not reportes or not db_config:
        logging.error("Configuración incompleta en 'config.json'.")
        exit()

    # Obtener la información
    try:
        workng = encontrar_zip(workng_dir)
        cliente, sucursal, fecha_actual = extraer_info_zip(workng)
        cliente = cliente.lstrip('0')
    except FileNotFoundError as e:
        logging.error(e)
        exit()

    # Verificar existencia y permisos del archivo ZIP
    if not os.path.isfile(workng):
        logging.error(f"El archivo ZIP no existe en la ruta especificada: {workng}")
        exit()
    elif not os.access(workng, os.R_OK):
        logging.error(f"Permiso denegado para leer el archivo ZIP: {workng}")
        exit()

    # Crear la carpeta Sandbx si no existe
    if not os.path.isdir(sandbx):
        try:
            os.makedirs(sandbx, exist_ok=True)
            logging.info(f"Carpeta creada: {sandbx}")
        except PermissionError:
            logging.error(f"Permiso denegado para crear la carpeta: {sandbx}")
            exit()
        except Exception as e:
            logging.error(f"Se produjo un error al crear la carpeta: {e}")
            exit()

    # Intentar descomprimir el archivo ZIP
    try:
        with zipfile.ZipFile(workng, 'r') as zip_ref:
            zip_ref.extractall(sandbx)
            logging.info(f"Archivo descomprimido en {sandbx}")
    except FileNotFoundError:
        logging.error(f"El archivo ZIP no se encontró en la ruta especificada: {workng}")
    except PermissionError:
        logging.error(f"Permiso denegado para acceder al archivo ZIP o a la carpeta de destino.")
    except Exception as e:
        logging.error(f"Se produjo un error al descomprimir el archivo: {e}")

    
    # Renombrar los archivos extraídos
    for archivo in os.listdir(sandbx):
        
        for reporte in reportes:
            if archivo.startswith(reporte):
                nuevo_nombre_base = filtrar_letras(archivo)
                nuevo_nombre = f"{reporte}{sucursal}.txt"
                ruta_antigua = os.path.join(sandbx, archivo)
                ruta_nueva = os.path.join(sandbx, nuevo_nombre)
                os.rename(ruta_antigua, ruta_nueva)
                logging.info(f"Archivo renombrado de {archivo} a {nuevo_nombre}")

    try:
        # Conectar a la base de datos
        conexion = conectar_db(db_config.get('host', ''), db_config.get('usuario', ''), db_config.get('contrasena', ''), db_config.get('base_de_datos', ''))

        # Obtener la versión del servidor PostgreSQL
        if conexion:
            version_servidor = obtener_version_servidor(conexion)
        else:
            version_servidor = "Desconocida"

        # Iterar sobre cada reporte y realizar las operaciones de creación de tabla e inserción
        for reporte in reportes:

            for item in reportes_selec:
                if reporte in item and reporte == ''.join([i for i in item if not i.isdigit()]):
                    reporte = item
                    break
            #Tomamos el nombre del dms
            dms_name = obtener_dms_por_reporte(reporte, config_data)

            nombre_tabla = f"{filtrar_letras(reporte)}{sucursal}"
            ruta_archivo = os.path.join(sandbx, f'{filtrar_letras(reporte)}{sucursal}.txt')

            # Verificar existencia del archivo TXT
            if not os.path.isfile(ruta_archivo):
                logging.warning(f"El archivo TXT no se encontró en la ruta especificada: {ruta_archivo}. Omitiendo este reporte.")
                continue

            # Intentar leer el archivo con diferentes codificaciones
            codificaciones = ['utf-8', 'ISO-8859-1', 'latin1', 'Windows-1252']

            raw_data = None
            for codificacion in codificaciones:
                try:
                    with open(ruta_archivo, 'r', encoding=codificacion) as f:
                        raw_data = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if raw_data is None:
                logging.error(f"No se pudo leer el archivo TXT {ruta_archivo} con ninguna de las codificaciones probadas.")
                continue

            # Se limpia el reporte de la basura
            raw_data_clean = limpiar_encabezado(raw_data)

            # Procesar el contenido del archivo TXT
            data = [row.split('|') for row in raw_data_clean.strip().split('\n')]

            # Usar encabezados esperados del archivo de configuración
            encabezados_esperados = columnas_esperadas.get(reporte, [])
            headers = encabezados_esperados
            rows = data
            #print(f'rows : ......... {rows}')
            
            # Comparar las columnas actuales con las esperadas
            columnas = [col.lower() for col in data[0]]  # Convertir todas las columnas actuales a minúsculas

            #print(f'Columnas esperadas .... {columnas_esperadas}')
            # Convertir columnas esperadas a minúsculas
            # Acceder a la lista de columnas esperadas (primera parte de la tupla)
            columnas_esperadas_reporte = set([col.lower() for col in columnas_esperadas.get(reporte, ([], []))[0]])
            #print(f'Col reporte: {columnas_esperadas_reporte}')

            # Verificar si al menos una columna coincide
            if columnas_esperadas_reporte.intersection(columnas):
                rows = data[1:] 
                logging.info(f"Al menos una columna de {nombre_tabla} coincide con las columnas esperadas en la configuración.")
            else:
                logging.info(f"El documento {nombre_tabla} no trae columnas.")
        
            headers, columnas_export = columnas_esperadas[reporte]
            print(f'Columnas: {columnas}')
            print(f'Columnas export: {columnas_export}')

            print(f'Headers: {headers}')
            headers = renombrar_columnas(headers)

            # Ajustar el número de columnas en las filas
            max_columns = len(headers)
            adjusted_rows = []
            for row in rows:
                if len(row) < max_columns:
                    row.extend([''] * (max_columns - len(row)))
                elif len(row) > max_columns:
                    row = row[:max_columns] 
                adjusted_rows.append(row)

            # Paso 1: Filtrar los campos que contienen '(computed)'
            campos_computed = [campo for campo in headers if '(computed)' in campo]
            print(f'Campos Computed: {campos_computed}')
            encabezados2 = [campo for campo in headers if '(computed)' not in campo]

            # Paso 2: Verificar y ajustar el número de columnas en adjusted_rows
            adjusted_rows = [row[:len(encabezados2)] for row in adjusted_rows]

            # Paso 3: Crear el DataFrame sin los campos calculados
            df = pd.DataFrame(adjusted_rows, columns=encabezados2)
            
            # Identificar y eliminar columnas marcadas con asteriscos
            columns_to_hide = [col for col in df.columns if col.startswith('*') and col.endswith('*')]
            df.drop(columns=columns_to_hide, inplace=True) 
    
            # Paso de la muerte : Infiere tipos de datos 
            #df = asignar_tipos_de_datos(df, dms_name, reporte) #Si tenemos problemas futuros para formulas descomentar el paso de la muerte

            # Paso 4: Aplicar las fórmulas para las columnas calculadas (computed)
            for campo_calculado in campos_computed:
                print(f'Campo_calculador: {campo_calculado}, dms_name: {dms_name}, Reporte: {reporte}, Clients_path: {clients_path}')
                formula = obtener_formula(dms_name, reporte, campo_calculado, clients_path)
                print(f'Formula: {formula}')
                
                filtro = obtener_filtro(dms_name,reporte,clients_path)
                print(f'Filtriño en el reporte..... {filtro}')

                if formula:
                    # Reemplaza "branch" por "sucursal"
                    if "branch" in formula:
                        formula = formula.replace("branch", "sucursal")
                        logging.info("Se reemplazó 'branch' por 'sucursal' en la fórmula.")

                    # Reemplaza "return" por "result =" en la fórmula para que funcione con exec
                    formula_ajustada = formula.replace("return", "result =")

                    try:
                        # Crear una copia de los nombres de las columnas originales
                        columnas_originales = df.columns.tolist()
                        columnas_sin_simbolo = [col.replace('$', '') for col in columnas_originales]

                        # Reemplazar temporalmente las columnas con símbolo $ quitando el $
                        formula_sin_simbolo = formula_ajustada.replace('$', '')

                        # Ajustar la fórmula solo para columnas que coincidan exactamente con los nombres de las columnas sin símbolo $
                        for col_original, col_sin_simbolo in zip(columnas_originales, columnas_sin_simbolo):
                            formula_sin_simbolo = re.sub(rf'\b{col_sin_simbolo}\b', f"df['{col_original}']", formula_sin_simbolo)

                        # Si la fórmula contiene '(computed)', eliminarlo y ajustar la fórmula
                        formula_final = formula_sin_simbolo.replace(' (computed)', '')
                        nuevo_nombre = campo_calculado.replace(' (computed)', '')
                        print(f'Formula Final ... {formula_final}')
                        print(f'Campo calcula2: {nuevo_nombre}')

                        # Comprobamos si la fórmula es FormulaUtilidad y la aplicamos
                        if 'FormulaUtilidad' in formula_final:
                            if 'Venta$' in df.columns:
                                df['Venta$'] = pd.to_numeric(df['Venta$'], errors='coerce').fillna(0)
                            if 'Costo$' in df.columns:
                                df['Costo$'] = pd.to_numeric(df['Costo$'], errors='coerce').fillna(0)
                            
                            # Aplicar la fórmula fila por fila usando FormulaUtilidad
                            df[nuevo_nombre] = df.apply(lambda row: FormulaUtilidad(row['Venta$'], row['Costo$']), axis=1)
                            logging.info(f"Fórmula FormulaUtilidad aplicada a la columna '{nuevo_nombre}'.")

                        # Comprobamos si la fórmula es FormulaMargen y la aplicamos
                        elif 'FormulaMargen' in formula_final:
                            if 'Venta$' in df.columns:
                                df['Venta$'] = pd.to_numeric(df['Venta$'], errors='coerce').fillna(0)
                            if 'Costo$' in df.columns:
                                df['Costo$'] = pd.to_numeric(df['Costo$'], errors='coerce').fillna(0)
                            
                            # Aplicar la fórmula fila por fila usando FormulaMargen
                            df[nuevo_nombre] = df.apply(lambda row: FormulaMargen(row['Venta$'], row['Costo$']), axis=1)
                            logging.info(f"Fórmula FormulaMargen aplicada a la columna '{nuevo_nombre}'.")

                        # Verificar si la fórmula es Ctod y aplicarla
                        elif 'Ctod' in formula_final:
                            match = re.search(r'Ctod\("([^"]+)"\)', formula_final)
                            if match:
                                orden = match.group(1).strip()
                                fecha_actual = datetime.now().strftime('%d/%m/%Y')
                                df[nuevo_nombre] = Ctod(fecha_actual, orden)
                                logging.info(f"Fórmula Ctod aplicada en la columna '{nuevo_nombre}' con formato '{orden}' usando la fecha actual.")
                                continue
                            else:
                                logging.warning(f"No se pudieron extraer los parámetros de la fórmula Ctod en la columna {nuevo_nombre}.")

                        # Evaluar cualquier fórmula escrita en Python
                        else:
                            def evaluar_formula_python(row):
                                local_vars = row.to_dict()  
                                local_vars['result'] = None 

                                # Añadir la variable `sucursal` directamente al contexto local
                                local_vars['sucursal'] = sucursal

                                try:
                                    exec(formula_final, {}, local_vars)  
                                    return local_vars['result'] 
                                except Exception as e:
                                    logging.error(f"Error al evaluar la fórmula Python para {campo_calculado}: {e}")
                                    return None

                            # Aplica la fórmula a cada fila del DataFrame
                            df[nuevo_nombre] = df.apply(evaluar_formula_python, axis=1)
                            logging.info(f"Fórmula Python aplicada a la columna '{nuevo_nombre}'.")

                        # Renombrar la columna quitando '(computed)' si es necesario
                        df.rename(columns={campo_calculado: nuevo_nombre}, inplace=True)
                        logging.info(f"El encabezado de la columna '{campo_calculado}' fue cambiado a '{nuevo_nombre}'.")

                    except Exception as e:
                        logging.error(f"Error al aplicar la fórmula en la columna calculada '{campo_calculado}': {e}")

            # Paso Mata viejitas: Aplica el filtro y elimina las filas que se encuntren en el JSON
            df = aplica_filtros(df, dms_name, reporte_name, clients_path) # El Filtro solo tiene logica para eliminar registros con valores vacios de momento
            
            # Paso 5: Aplicar las fórmulas a todas las columnas que tengan fórmulas en encabezados2
            aplicar_formulas(df, dms_name, reporte)

            # Paso 6: Reordenar las columnas para respetar la posición original de las columnas exportadas        
            if columnas_export:
                nuevos_encabezados_export = [campo.replace('(computed)', '').strip() for campo in columnas_export]  # Tomar columnas_export
            else:
                nuevos_encabezados_export = [campo.replace('(computed)', '').strip() for campo in encabezados2]  # Fallback a encabezados2

            columnas_actuales = list(df.columns)  # Columnas actuales después de eliminar o modificar
            print(f'Columnas Actuales: {columnas_actuales}')
            # Mapear el orden original al DataFrame actual, ajustando solo si las columnas están presentes
            orden_final_export = [col for col in nuevos_encabezados_export if col in columnas_actuales]
            print(f'Orden_final_export: {orden_final_export}')

            try:
                df = df[orden_final_export]
            except KeyError as e:
                logging.error(f"Una o más columnas especificadas en columnas_export no están presentes en el DataFrame: {e}")

            # Obtener los nuevos encabezados después de aplicar las fórmulas y reordenar
            nuevos_encabezados = df.columns.to_list()
            print(f'Nuevos Encabezados : {nuevos_encabezados}')
            
            # Paso 7: Comprobamos si es un SERVTA
            if re.sub(r'\d+', '', reporte) == 'SERVTA': 
                # Generar el DataFrame SERVTC
                generar_servtc(df, sucursal, nuevos_encabezados, sandbx)
                        
            # Añadir columnas Client, Branch, Date
            df.insert(0, 'Client', cliente)
            df.insert(1, 'Branch', sucursal)
            #df.insert(2, 'Date', fecha_actual)

            # Limpiar datos (si es necesario)
            #df = df.replace({np.nan: ''})
            # Rellenar valores nulos con cadenas vacías

            # Crear la consulta SQL para crear la tabla
            create_table_query = f"CREATE TABLE {nombre_tabla} (\n"
            create_table_query += "    Client varchar(5) DEFAULT NULL,\n"
            create_table_query += "    Branch varchar(5) DEFAULT NULL,\n"
            #create_table_query += "    Date varchar(20),\n"
            
            for a in nuevos_encabezados:
                tipo_dato = inferir_tipo_dato(a, dms_name, reporte, clients_path)
                create_table_query += f"    {a} {tipo_dato} DEFAULT NULL,\n"
            create_table_query = create_table_query.rstrip(',\n') + "\n)"

            # Añadir ENGINE y CHARSET a la consulta SQL
            create_table_query += "\nENGINE=InnoDB CHARSET=utf8mb4;\n"

            # Crear la consulta SQL para eliminar la tabla si existe
            drop_query = f"DROP TABLE IF EXISTS {nombre_tabla};"
        
            #####################################################
            #               PEDAZO AJUSTAR                      #
            #####################################################

            # Obtener las columnas de tipo datetime
            datetime_columns = df.select_dtypes(include=['datetime64']).columns

            # Convertir los encabezados a una lista
            encabezados_datetime = datetime_columns.tolist()

            # Mostrar la lista de encabezados de las columnas datetime
            query_alter = generar_query_alter_table(reporte, encabezados_datetime, sucursal)

            # Convertir columnas de fecha a formato 'YYYY-MM-DD' antes de la inserción
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    # Convertir a formato 'YYYY-MM-DD' y reemplazar NaT con None (que será convertido a NULL en SQL)
                    df[col] = df[col].dt.strftime('%Y-%m-%d').replace({pd.NaT: None, 'None': None, None: None})
                elif pd.api.types.is_numeric_dtype(df[col]):
                    # Para las columnas numéricas, reemplazar NaN o None con 0
                    df[col] = df[col].replace({np.nan: 0, None: 0, 'None': 0})
                else:
                    # Para las demás columnas, reemplazar NaN y None con una cadena vacía
                    df[col] = df[col].replace({np.nan: '', None: '', 'None': ''})

            # Al generar la consulta SQL, asegurarse de que los valores None se sustituyan por NULL en la cadena SQL
            insert_query = f"INSERT INTO {nombre_tabla} ({', '.join(df.columns)}) VALUES "
            insert_query = insert_query.replace("None", "NULL")
            values_list = df.apply(lambda x: tuple('NULL' if v is None else v for v in x), axis=1).tolist()
            values_query = ', '.join([str(v).replace("'NULL'", "NULL") for v in values_list])  # Reemplazar 'NULL' con NULL sin comillas
            insert_query += values_query + ";"

            # Guardar las consultas SQL en un archivo .sql.dump
            consultas = [
                f"-- Table structure for table {nombre_tabla}",
                drop_query,
                create_table_query,
                f"-- Dumping data for table {nombre_tabla}",
                insert_query
            ]
            archivo_sql = os.path.join(sandbx, f"{nombre_tabla}.sql.dump")
            guardar_sql_dump(archivo_sql, consultas, version_servidor)
            
            if conexion:
                # Verificar si alguna columna excede la longitud permitida antes de insertar
                longitudes_maximas = obtener_column_lengths(archivo_sql)
                print(F'Ejecuta drop Query')
                ejecutar_consulta(conexion, drop_query)
                print("Ejecuta Create Query")
                ejecutar_consulta(conexion, create_table_query)
                # Ejecutamos la consulta una vez la tabla ya creada 
                # if encabezados_datetime:
                #     ejecutar_query_alter_table(db_config, query_alter)
                print("Ejecuta Insert Query")
                ejecutar_consulta_insert(conexion, insert_query, df=df, max_lengths=longitudes_maximas, nombre_tabla=nombre_tabla, version_servidor=version_servidor, archivo_sql=archivo_sql, drop_query=drop_query,create_table_query=create_table_query)

    finally:
        if conexion:
            conexion.close()
            logging.info("<--------------- Conexion a la base de datos cerrada. --------------->")
    
# Función para conectar a la base de datos PostgreSQL
def conectar_db(host, usuario, contrasena, base_de_datos):
    print(f'host: {host}, User: {usuario}, Pass: {contrasena}, BD: {base_de_datos}')
    try:
        conexion = mysql.connector.connect(
            host=host,
            user=usuario,
            password=contrasena,
            database=base_de_datos
        )
        if conexion.is_connected():
            logging.info("Conexión a la base de datos MySQL establecida.")
        return conexion
    except Error as e:
        logging.error(f"Error al conectar a la base de datos MySQL: {e}")
        return None

def ejecutar_consulta(conexion, consulta):
    try:
        cursor = conexion.cursor()
        cursor.execute(consulta)
        if cursor.with_rows:
            cursor.fetchall()

        conexion.commit()
        logging.info("🟢 Consulta ejecutada con éxito.")
    except Error as e:
        logging.error(f"🔴 Error al ejecutar la consulta: {e}")
        logging.error(f"Consulta que falló: {consulta}")
        conexion.rollback() 
    finally:
        cursor.close()

def ejecutar_consulta_insert(conexion, consulta, df=None, max_lengths=None, nombre_tabla=None, archivo_sql=None, version_servidor=None, drop_query=None, create_table_query=None):
    """
    Ejecuta una consulta SQL y maneja los errores relacionados con la longitud máxima de las columnas. 
    Si la consulta falla debido a un valor que excede la longitud máxima permitida en una columna, 
    ajusta los valores en el DataFrame y vuelve a intentar la inserción.
    Si el nuevo intento de inserción tiene éxito, se guarda el nuevo INSERT en el archivo .sql.dump.

    :param conexion: Objeto de conexión a la base de datos.
    :param consulta: Cadena de texto que contiene la consulta SQL a ejecutar.
    :param df: DataFrame que contiene los datos a insertar. (Opcional)
    :param max_lengths: Diccionario con las columnas como claves y sus longitudes máximas permitidas como valores. (Opcional)
    :param nombre_tabla: Nombre de la tabla en la base de datos donde se realizará la inserción. (Opcional)
    :param archivo_sql: Ruta del archivo .sql.dump donde se guardarán las consultas. (Opcional)
    :param version_servidor: Versión del servidor PostgreSQL. Necesario para la cabecera del archivo .sql.dump. (Opcional)
    :return: None
    """
    if df is not None and df.empty:
        logging.warning("El DataFrame está vacío, no se realizará ninguna operación.")
        return  
    
    try:
        cursor = conexion.cursor()
        cursor.execute(consulta)
        conexion.commit()
        logging.info("🟢 Consulta ejecutada con éxito.")
    except Error as e:
        logging.error(f"🔴 Error al ejecutar la consulta: {e}")
        #logging.error(f"Consulta que falló: {consulta}") Descomentar si se quiere ver la consulta del error 
        # Realiza un rollback para liberar la transacción
        conexion.rollback()

        # Proceder a ajustar el dataframe y reintentar la inserción
        if df is not None and max_lengths is not None:
            logging.info("Ajustando el dataframe y reintentando la inserción...")

            try:
                # Truncar los valores que exceden la longitud máxima permitida
                for col, max_len in max_lengths.items():
                    if col in df.columns and max_len is not None:
                        df[col] = df[col].apply(lambda x: x[:max_len] if isinstance(x, str) else x)
                
                # Verificar si después del ajuste el DataFrame sigue teniendo datos
                if df.empty:
                    logging.warning("El DataFrame está vacío después del ajuste, no se realizará ninguna operación.")
                    return  
                
                # Generar una nueva consulta INSERT con los datos ajustados
                columns = ', '.join(df.columns)
                print(f'Columns: {columns}')
                values = ', '.join(str(tuple(row)) for row in df.values)
                #print(f'Values: {values}')
                new_insert_query = f"INSERT INTO {nombre_tabla} ({columns}) VALUES {values};"
                #print(new_insert_query)
                cursor.execute(new_insert_query)
                conexion.commit()
                logging.info("Inserción reintentada con éxito después del ajuste.")
                
                # Si se proporciona un archivo SQL, guardar solo el nuevo insert en el archivo
                if archivo_sql and version_servidor:
                    consultas = [
                        f"-- Table structure for table {nombre_tabla}",
                        drop_query,
                        create_table_query,
                        f"-- Dumping data for table {nombre_tabla} después de ajustar los datos",
                        new_insert_query
                    ]
                    guardar_sql_dump(archivo_sql, consultas, version_servidor)
            except KeyError as ke:
                logging.error(f"Error de columna en el DataFrame: {ke}")
            except Exception as e2:
                logging.error(f"Error al ejecutar la consulta después del ajuste: {e2}")
                conexion.rollback() 
        else:
            logging.error("El dataframe o las longitudes máximas son None, no se puede proceder con el ajuste.")
            conexion.rollback() 

def generar_query_verificacion_longitudes(columnas, valores, longitudes_maximas):
    """
    Genera una consulta SQL para verificar si algún valor excede la longitud máxima permitida en una columna.

    :param columnas: Lista de nombres de las columnas de la tabla.
    :param valores: Lista de valores que se intentan insertar.
    :param longitudes_maximas: Diccionario con las columnas y sus longitudes máximas permitidas.
    :return: Consulta SQL como cadena de texto.
    """
    query = []
    
    for columna, valor in zip(columnas, valores):
        longitud_max = longitudes_maximas.get(columna)
        if longitud_max and valor: 
            condicion = f"SELECT '{columna}' AS column_name, {longitud_max} AS character_maximum_length, LENGTH('{valor}') AS actual_length WHERE LENGTH('{valor}') > {longitud_max}"
            query.append(condicion)
    
    query_sql = " UNION ALL ".join(query)
    
    return query_sql

def extraer_longitudes_maximas(archivo_sql):
    """
    Esta función extrae las longitudes máximas para las columnas que tienen un tamaño definido
    (como VARCHAR, CHAR, etc.) en el archivo SQL dump, e ignora tipos como DATE y DOUBLE PRECISION.
    
    :param archivo_sql: Ruta del archivo SQL dump.
    :return: Diccionario con las columnas como claves y las longitudes máximas como valores.
    """
    longitudes_maximas = {}
    try:
        with open(archivo_sql, 'r', encoding='utf-8') as file:
            contenido = file.read()
            
        # Expresión regular para capturar columnas con longitudes definidas
        matches = re.findall(r'(\w+)\s+(VARCHAR|varchar)\((\d+)\)', contenido, re.IGNORECASE)
        # Crear un diccionario con las longitudes máximas solo para VARCHAR y CHAR
        for match in matches:
            columna, tipo, longitud = match
            longitudes_maximas[columna] = int(longitud)

    except FileNotFoundError:
        logging.error(f"No se encontró el archivo SQL: {archivo_sql}")
    except Exception as e:
        logging.error(f"Error al extraer longitudes máximas del archivo SQL: {e}")

    return longitudes_maximas

def obtener_column_lengths(archivo_sql):
    """
    Extrae las longitudes de las columnas que están dentro de los paréntesis en un archivo SQL de creación de tablas,
    excluyendo las columnas de tipo double precision y DATE.

    :param archivo_sql: Ruta al archivo SQL que contiene la declaración de creación de la tabla.
    :return: Un diccionario con los nombres de las columnas como claves y sus longitudes máximas como valores.
    """
    column_lengths = {}
    inside_parentheses = False
    with open(archivo_sql, 'r', encoding='utf-8') as file:
        for line in file:
            # Detectar el inicio de las definiciones de columnas (dentro de paréntesis)
            if '(' in line:
                inside_parentheses = True
            elif ')' in line:
                inside_parentheses = False

            if inside_parentheses:
                # Buscar líneas que definan columnas, manejando diferentes formatos de definición
                match = re.search(r'(\w+\$?)\s+(varchar\((\d+)\)|\w+\s*\(?\d*\)?)', line, re.IGNORECASE)
                if match:
                    column_name = match.group(1)
                    column_type = match.group(2)
                    
                    # Filtrar palabras clave que no son columnas y tipos double precision y DATE
                    if column_name.upper() not in ["CREATE", "INSERT"] and \
                       "decimal" not in column_type.lower() and \
                       "date" not in column_type.lower():
                        # Verificar si el tipo de columna incluye una longitud específica
                        length_match = match.group(3)
                        if length_match:
                            column_lengths[column_name] = int(length_match)
                        else:
                            column_lengths[column_name] = None  # Para otros tipos de datos sin longitud fija
    
    return column_lengths

# Función para limpiar el contenido de una carpeta
def limpiar_carpeta(carpeta):
    for archivo in os.listdir(carpeta):
        ruta_archivo = os.path.join(carpeta, archivo)
        try:
            if os.path.isfile(ruta_archivo):
                os.remove(ruta_archivo)
            elif os.path.isdir(ruta_archivo):
                os.rmdir(ruta_archivo)
        except Exception as e:
            logging.error(f"No se pudo eliminar {ruta_archivo}: {e}")

# Función para limpiar encabezados basura de los reportes
def limpiar_encabezado(reporte):
    lines = reporte.strip().splitlines()
    for i, line in enumerate(lines):
        if '|' in line:
            return '\n'.join(lines[i:])
    return ''

# Función para filtrar solo letras de un nombre de archivo
def filtrar_letras(nombre):
    return re.sub(r'[^a-zA-Z]', '', nombre)

# Función para guardar consultas SQL en un archivo
def guardar_sql_dump(nombre_archivo, consultas, version_servidor):
    encabezado = (
        "-- PostgreSQL dump\n"
        "--\n"
        f"-- Host: localhost    Database: {db_config.get('base_de_datos', 'Desconocida')}\n"
        "-- ------------------------------------------------------\n"
        f"-- Server version {version_servidor}\n\n"
    )
    try:
        with open(nombre_archivo, 'w', encoding='utf-8') as f:
            f.write(encabezado)
            for consulta in consultas:
                f.write(consulta + '\n')
        logging.info(f"Archivo SQL dump generado: {nombre_archivo}")
    except Exception as e:
        logging.error(f"Se produjo un error al guardar el archivo SQL dump: {e}")

# Función para obtener la versión del servidor PostgreSQL
def obtener_version_servidor(conexion):
    try:
        cursor = conexion.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        logging.info(f"Versión del servidor PostgreSQL: {version}")
        return version
    except Error as e:
        logging.error(f"Error al obtener la versión del servidor: {e}")
        return "Desconocida"

# Función para renombrar columnas
def renombrar_columnas(headers):
    
    seen = {}
    new_headers = []
    for header in headers:
        if header in seen:
            seen[header] += 1
            new_header = f"{header}_{seen[header]}"
        else:
            seen[header] = 0
            new_header = header
        new_headers.append(new_header)
    return new_headers

def obtener_formula(dms_name, reporte_name, campo, clients_path):
    """
    Esta función busca y retorna la fórmula correspondiente a un campo específico dentro de un reporte
    de un DMS en particular.

    :param dms_name: Nombre del DMS.
    :param reporte_name: Nombre del reporte dentro del DMS.
    :param campo: El nombre de la columna o campo para el cual se quiere obtener la fórmula.
    :return: La fórmula correspondiente al campo si existe, de lo contrario, None.
    """
    # Ruta al archivo JSON del DMS
    dms_path = os.path.join(clients_path, 'dms', f'{dms_name}.json')
    print(f'Dms_path: {dms_path}')
    
    if not os.path.exists(dms_path):
        logging.error(f"No se encontró el archivo {dms_path} para el DMS {dms_name}.")
        return None

    try:
        with open(dms_path, 'r') as file:
            dms_data = json.load(file)
    except json.JSONDecodeError as e:
        logging.error(f"Error al leer el archivo JSON {dms_path}: {e}")
        return None


    print(f'Campo: {campo}')
    # Acceder a las fórmulas en el JSON del DMS para el reporte y campo específicos
    formula = dms_data.get('columnas_esperadas', {}).get(reporte_name, {}).get('formulas', {}).get(campo, None)
    
    return formula


def obtener_filtro(dms_name, reporte_name, clients_path):
    """
    Esta función busca y retorna el filtro correspondiente dentro de un reporte
    de un DMS en particular.

    :param dms_name: Nombre del DMS.
    :param reporte_name: Nombre del reporte dentro del DMS.
    :return: El filtro correspondiente al reporte si existe, de lo contrario, None.
    """
    # Ruta al archivo JSON del DMS
    dms_path = os.path.join(clients_path, 'dms', f'{dms_name}.json')
    print(f'Dms_path: {dms_path}')
    
    if not os.path.exists(dms_path):
        logging.error(f"No se encontró el archivo {dms_path} para el DMS {dms_name}.")
        return None

    try:
        with open(dms_path, 'r') as file:
            dms_data = json.load(file)
    except json.JSONDecodeError as e:
        logging.error(f"Error al leer el archivo JSON {dms_path}: {e}")
        return None


    # Acceder a las fórmulas en el JSON del DMS para el reporte y campo específicos
    filtro = dms_data.get('columnas_esperadas', {}).get(reporte_name, {}).get('filtros', {})
    
    return filtro


def aplicar_formulas(df, dms_name, reporte):
    """
    Aplica fórmulas a las columnas calculadas en el DataFrame.

    :param df: El DataFrame al que se aplicarán las fórmulas.
    :param dms_name: El nombre del DMS utilizado para obtener las fórmulas.
    :param reporte: El nombre del reporte que se está procesando.
    """
    for columna in df.columns:
        # Obtener la fórmula asociada a la columna
        formula = obtener_formula(dms_name, reporte, columna, clients_path)
        if formula:
            try:
                # Verificar si la fórmula contiene 'LimpiaTexto' o 'LimpiaEmail' para aplicar la función correspondiente
                if 'LimpiaTexto' in formula:
                    df[columna] = df[columna].apply(LimpiaTexto)
                elif 'LimpiaEmail' in formula:
                    df[columna] = df[columna].apply(LimpiaEmail)
                elif 'FormulaMargen' in formula:
                    # Aquí modificamos para siempre pasar 'Venta$' y 'Costo$'
                    df[columna] = df.apply(lambda row: FormulaMargen(row['Venta$'], row['Costo$']), axis=1)
                elif 'FormulaUtilidad' in formula:
                    # Aquí modificamos para siempre pasar 'Venta$' y 'Costo$'
                    df[columna] = df.apply(lambda row: FormulaUtilidad(row['Venta$'], row['Costo$']), axis=1)
                elif 'LimpiaCodigos' in formula:
                    df[columna] = df[columna].apply(LimpiaCodigos)
                else:
                    # Convertir las columnas que participan en la fórmula a un tipo numérico
                    columnas_en_formula = re.findall(r"df\['(.*?)'\]", formula)
                    print(f'Columnas_formula .... {columnas_en_formula}')
                    for col in columnas_en_formula:
                        if df[col].dtype == 'object':
                            logging.info(f"Convirtiendo la columna '{col}' a numérico.")
                            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                    # Evaluar cualquier otra fórmula que no sea de limpieza de texto
                    df[columna] = eval(formula)

                logging.info(f"Fórmula '{formula}' aplicada a la columna '{columna}' en el reporte '{reporte}'.")

            except Exception as e:
                logging.error(f"Error al aplicar la fórmula en la columna calculada '{columna}': {e}")
                logging.error(f"Fórmula: {formula}")
        else:
            logging.info(f"No hay fórmula para la columna '{columna}' en el reporte '{reporte}'.")

def obtener_dms_por_reporte(reporte, config_data):
    """
    Función para obtener el DMS basado en un reporte específico.

    :param reporte: El reporte que se está buscando (ejemplo: 'REFSER01').
    :param config_data: El diccionario que contiene la información del JSON de configuración.
    :return: El DMS correspondiente si se encuentra, de lo contrario None.
    """
    # Recorremos los registros dentro de la configuración
    for registro in config_data.get('registros', []):
        dms_data = registro.get('dms', {})
        # Recorremos las claves y listas de reportes dentro de dms
        for dms, reportes_lista in dms_data.items():
            # Verificamos si el reporte está en la lista correspondiente
            if reporte in reportes_lista:
                return dms 
    return None

def generar_servtc(df_servta, sucursal, nuevos_encabezados, nombre_carpeta):
    # Definir el nombre del archivo como SERVTC + Sucursal
    nombre_archivo = f"SERVTC{sucursal}.txt"
    print(f'Nombre Carpeta ................ {nombre_carpeta}')
    
    # Definir la ruta completa del archivo en la carpeta 3-Sandbx
    ruta_archivo = os.path.join(nombre_carpeta, nombre_archivo)

    # Definir todas las posibles columnas por las que deseas agrupar
    columnas_a_agrupar = [
        "FechaFactura", "FechaApertura", "FechaEntrega", "Factura", "Taller", 
        "TipoOrden", "TipoPago", "NumeroOT", "NumeroAsesor", "NombreAsesor", 
        "RFC", "NombreCliente", "Direccion", "Telefono", "CP", "Email", 
        "Odometro", "Vin", "Marca", "Modelo", "Color", "Dias", "Año"
    ]

    # Definir las columnas que deben ser sumadas
    columnas_a_sumar = [
        "Venta$", "Costo$", "Utilidad$", "Margen", "VentaMO$", "DescuentoMO$", 
        "CostoMO$", "VentaMateriales$", "DescuentoMateriales$", "CostoMateriales$", 
        "VentaTOT$", "DescuentoTOT$", "CostoTOT$", "VentaPartes$", "DescuentoPartes$", 
        "CostoPartes$", "VentaTotal$", "CostoTotal$"
    ]

    # Filtrar las columnas que existen en el DataFrame
    columnas_a_agrupar_existentes = [col for col in columnas_a_agrupar if col in df_servta.columns]
    columnas_a_sumar_existentes = [col for col in columnas_a_sumar if col in df_servta.columns]

    # Convertir las columnas numéricas a formato numérico seguro
    df_servta[columnas_a_sumar_existentes] = df_servta[columnas_a_sumar_existentes].apply(pd.to_numeric, errors='coerce')

    # Agrupar por las columnas que existen y sumar las columnas numéricas
    df_servtc = df_servta.groupby(columnas_a_agrupar_existentes)[columnas_a_sumar_existentes].sum().reset_index()

    # Eliminar cualquier fila que contenga solo valores nulos o vacíos
    df_servtc.dropna(how='all', inplace=True)

    # Eliminar cualquier columna extra que pueda contener solo valores vacíos
    df_servtc = df_servtc.loc[:, ~df_servtc.columns.str.contains('^Unnamed')]

    # Ajustar el DataFrame para hacer "match" con los nuevos encabezados
    df_servtc.columns = nuevos_encabezados[:len(df_servtc.columns)]  # Ajustar a los nuevos encabezados

    # Guardar el DataFrame resultante en un archivo .txt separado por |
    df_servtc.to_csv(ruta_archivo, index=False, sep='|', encoding='utf-8')

    logging.info(f"DataFrame SERVTC guardado como {ruta_archivo}")

    return df_servtc

def asignar_tipos_de_datos(df, dms_name, reporte_name):
    for col in df.columns:
        # Inferir el tipo de dato para la columna usando la función existente
        tipo_dato = inferir_tipo_dato(col, dms_name, reporte_name, clients_path)
        logging.info(f"Inferido tipo de dato para '{col}': {tipo_dato}")
        
        # Asignar el tipo de dato correcto según la inferencia
        try:
            if 'VARCHAR' in tipo_dato.upper() or 'varchar' in tipo_dato:
                df[col] = df[col].astype(str)  # Convertir a string
                logging.info(f"Columna '{col}' convertida a string")
                
            elif 'DATE' in tipo_dato.upper() or 'datetime' in tipo_dato.lower():
                # Verificar si es el reporte SERVTC para usar formato YYYY-MM-DD
                if reporte_name == "SERVTC":
                    # Convertir la columna a formato datetime con formato YYYY-MM-DD
                    df[col] = pd.to_datetime(df[col], format='%Y-%m-%d', errors='coerce')
                    logging.info(f"Columna '{col}' convertida a formato datetime con formato '%Y-%m-%d' para SERVTC")
                else:
                    # Convertir la columna a formato datetime con formato dd/mm/yyyy para otros reportes
                    df[col] = pd.to_datetime(df[col], format='%d-%m-%Y', errors='coerce')
                    logging.info(f"Columna '{col}' convertida a formato datetime con formato '%d/%m/%Y'")

            elif 'decimal' in tipo_dato.lower():  # Manejo para decimal
                df[col] = pd.to_numeric(df[col], errors='coerce')  # Convertir a numérico de doble precisión
                logging.info(f"Columna '{col}' convertida a decimal")
                
            elif 'int' in tipo_dato.lower() or 'integer' in tipo_dato.lower():
                df[col] = pd.to_numeric(df[col], errors='coerce', downcast='integer')  # Convertir a entero
                logging.info(f"Columna '{col}' convertida a integer")

            elif isinstance(df[col].iloc[0], pd.Timedelta):
                # Convertir Timedelta a número de días
                df[col] = df[col].dt.days.fillna(0).astype(int).astype(str)  # Convertir a número de días y luego a string
                logging.info(f"Columna '{col}' convertida a número de días desde Timedelta como string")
                
            else:
                logging.warning(f"No se pudo inferir un tipo de dato claro para la columna '{col}', usando 'object'.")
                df[col] = df[col].astype(object)  # Convertir a tipo object como fallback
            
        except Exception as e:
            logging.error(f"Error al convertir la columna '{col}': {e}")
            df[col] = df[col].astype(object)  # Fallback en caso de error

    # Devolver el DataFrame con los tipos de datos actualizados
    return df

def generar_query_alter_table(reporte, columnas_date, sucursal):
    """
    Genera dinámicamente una consulta SQL para modificar las columnas de tipo DATE de un reporte
    y permitir valores NULL en esas columnas.

    :param reporte: El nombre del reporte (tabla) para el cual se generará la consulta.
    :param columnas_date: Lista de nombres de columnas de tipo DATE que se deben modificar.
    :return: Una cadena con la consulta SQL ALTER TABLE generada dinámicamente.
    """
    # Comparamos si es SERVTC
    if reporte == "SERVTC":
        reporte= reporte + sucursal
    # Base de la consulta
    query = f"ALTER TABLE {reporte}\n"

    # Agregar dinámicamente las modificaciones de las columnas
    for columna in columnas_date:
        query += f"    ALTER COLUMN {columna} DROP NOT NULL,\n"

    # Eliminar la última coma y agregar el punto y coma
    query = query.rstrip(",\n") + ";\n"

    return query

def get_odoo_config():
    try:
        # Conectar a la base de datos de Odoo
        connection = psycopg2.connect(
            host="localhost",       
            database="simdata",  
            user="odoo",    
            password="abcd1234"
        )
        cursor = connection.cursor()

        # Consultar los valores de configuración desde ir.config_parameter
        cursor.execute("""
            SELECT key, value FROM ir_config_parameter
            WHERE key IN (
                'my_module.host', 'my_module.user', 'my_module.password',
                'my_module.bd_name', 'my_module.working_folder_path', 
                'my_module.sandbox_folder_path', 'my_module.clients_folder_path'
            );
        """)
        
        # Convertir el resultado en un diccionario de configuración
        config = {key: value for key, value in cursor.fetchall()}
        return config

    except Exception as error:
        logging.error(f"Error al obtener la configuración de Odoo: {error}")
        return None

    finally:
        if connection:
            cursor.close()
            connection.close()

def ejecutar_query_alter_table(db_config, query):
    """
    Ejecuta la consulta SQL generada para modificar las columnas de tipo DATE y permitir NULL.

    :param db_config: Diccionario con la configuración de la base de datos (host, usuario, contrasena, base_de_datos).
    :param query: La consulta SQL a ejecutar.
    """

    try:
        # Establecer la conexión con la base de datos
        conexion = psycopg2.connect(
            host=db_config['host'],
            user=db_config['usuario'],
            password=db_config['contrasena'],
            database=db_config['base_de_datos']
        )
        cursor = conexion.cursor()
        logging.info("Conexión a la base de datos establecida.")

        # Ejecutar la consulta SQL
        cursor.execute(query)
        conexion.commit()
        logging.info(f"Consulta ALTER TABLE ejecutada con éxito:\n{query}")

    except (Exception, Error) as error:
        logging.error(f"Error al ejecutar la consulta ALTER TABLE: {error}")


def aplica_filtros(df, dms_name, reporte_name, clients_path):
    """
    Este paso filtra los registros en el DataFrame según los filtros definidos en el JSON.
    Los registros que cumplan con las condiciones en 'filtros' serán eliminados del DataFrame.

    :param df: DataFrame sobre el cual se aplicarán los filtros.
    :param dms_name: Nombre del DMS para el archivo de configuración.
    :param reporte_name: Nombre del reporte dentro del DMS.
    :param clients_path: Ruta base donde se encuentran los archivos JSON de los DMS.
    :return: DataFrame filtrado según las condiciones.
    """
    # Obtener los filtros definidos en el JSON
    filtros = obtener_filtro(dms_name, reporte_name, clients_path)
    if not filtros:
        logging.info(f"No se encontraron filtros para el reporte '{reporte_name}'. Saltando el paso mata registros.")
        return df

    # Recorrer cada filtro y aplicar la condición si el campo existe en el DataFrame
    for filtro in filtros:
        # Extraer el nombre de la columna de la condición
        columna_match = re.match(r"(\w+)", filtro)
        columna = columna_match.group(1) if columna_match else None

        if columna and columna in df.columns:
            try:
                # Si el filtro es para valores vacíos o None, aplicar la condición directamente
                if filtro == f"{columna} == '' or {columna} == None":
                    # Filtrar registros donde la columna no esté vacía ni sea None
                    df = df[df[columna].str.strip() != ''].reset_index(drop=True)
                    logging.info(f"Filtro '{filtro}' aplicado. Registros con {columna} vacíos o None eliminados.")
                else:
                    logging.warning(f"No se reconoce el formato del filtro '{filtro}'. Saltando este filtro.")
            except Exception as e:
                logging.error(f"Error al aplicar el filtro '{filtro}': {e}")
        else:
            logging.warning(f"La columna '{columna}' no existe en el DataFrame. Saltando este filtro.")
    
    return df

    
procesar_archivo_zip()


