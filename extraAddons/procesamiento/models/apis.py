import json  # Asegúrate de importar el módulo json
from odoo.http import request, Response
from datetime import datetime
from odoo import http
import os
import subprocess
import re

class ProcesamientoController(http.Controller):

    @http.route('/move_to_working', type='http', auth='public', methods=['POST'], csrf=False)
    def move_to_working(self, file=None, **kwargs):
        if not file:
            return request.make_response('No file provided', status=400)
        
        # Get the working path from configuration
        working_path = request.env['ir.config_parameter'].sudo().get_param('my_module.working_folder_path') or '/default/path/2-working'
        
        # Check if the directory exists; if not, create it
        if not os.path.exists(working_path):
            os.makedirs(working_path)

        # Define the full path to save the file
        file_path = os.path.join(working_path, file.filename)
        
        try:
            # Write the file to the working directory
            with open(file_path, 'wb') as f:
                f.write(file.read())
            
            return request.make_response('File moved successfully', status=200)
        
        except Exception as e:
            # Log the error and return a 500 response
            print(f"Error moving file to working folder: {e}")
            return request.make_response('Error moving file to working folder', status=500)


    @http.route('/validate_zip_file', type='http', auth='public', methods=['POST'], csrf=False)
    def validate_zip_file(self, **post):
        try:
            # Obtenemos el archivo desde la petición
            file = request.httprequest.files.get('file')
            print(f'File: {file}')  # Verificar que el archivo llega correctamente
            if not file:
                return Response(json.dumps({'error': 'No se subió ningún archivo.'}), content_type='application/json')

            # Extraer partes del nombre del archivo
            file_name = file.filename
            cliente = file_name[:4].lstrip('0')  # Eliminar ceros a la izquierda
            branch = file_name[4:6]
            current_day = datetime.now().strftime('%d')
            file_day = file_name[6:8]

            # Verificar en la base de datos si el cliente y branch existen
            cliente_config = request.env['cliente.configuracion'].sudo().search([
                ('num_cliente', '=', int(cliente)),
                ('branch', '=', branch)
            ])

            # Verificar la existencia de cliente y branch
            cliente_exists = bool(cliente_config)
            branch_exists = bool(cliente_config)
            is_today = (current_day == file_day)

            # Devolver la respuesta en formato JSON
            return Response(json.dumps({
                'cliente_exists': cliente_exists,
                'branch_exists': branch_exists,
                'is_today': is_today,
                'error': False
            }), content_type='application/json')

        except Exception as e:
            # En caso de error, lo imprimimos en el log y devolvemos un error JSON
            print(f'Error: {e}')
            return Response(json.dumps({
                'error': 'Error en el servidor: ' + str(e)
            }), content_type='application/json')


    
    from odoo import http
from odoo.http import request, Response
import os
import subprocess
import shutil
import json

class FileController(http.Controller):

    @http.route('/execute_python', type='http', auth='user', methods=['POST'], csrf=False)
    def execute_python(self, **post):
        try:
            # Retrieve paths from configuration parameters
            python_path = request.env['ir.config_parameter'].sudo().get_param('my_module.python_path')
            clients_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.clients_folder_path')
            working_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.working_folder_path') or '/default/path/2-working'

            print(f'Python_path: {python_path}')
            print(f'Clients_folder_path: {clients_folder_path}')
            print(f'Working_folder_path: {working_folder_path}')

            # Initialize file_path to avoid "referenced before assignment" error
            file_path = None

            # Check if python_path is set
            if not python_path:
                return Response(json.dumps({'error': 'La ruta a la carpeta de Python no está configurada correctamente.'}), content_type='application/json')

            # Verify that python_path contains the correct path to the .bat file
            bat_file = os.path.join(python_path, 'procesamiento.bat')  # Path to procesamiento.bat

            if not os.path.exists(bat_file):
                return Response(json.dumps({'error': 'No se encontró el archivo procesamiento.bat en la ruta especificada.'}), content_type='application/json')

            # Move the file to the working folder
            if 'file' in post:
                file = post['file']
                file_path = os.path.join(working_folder_path, file.filename)

                # Save the file in the working folder
                with open(file_path, 'wb') as f:
                    shutil.copyfileobj(file.stream, f)
                print(f'File {file.filename} moved to {working_folder_path}')

            # Execute the .bat file
            try:
                subprocess.run([bat_file], check=True)
                success_message = 'El script se ejecutó correctamente.'

                # Delete the file from the working folder after successful execution
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    print(f'File {file.filename} deleted from {working_folder_path} after execution.')
                
                return Response(json.dumps({'success': success_message}), content_type='application/json')
            
            except subprocess.CalledProcessError as e:
                error_message = f'Error al ejecutar el script: {e}'
                
                # Delete the file from the working folder in case of an error
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    print(f'File {file.filename} deleted from {working_folder_path} after error.')

                return Response(json.dumps({'error': error_message}), content_type='application/json')

        except Exception as e:
            # Handle server error
            return Response(json.dumps({'error': f'Error en el servidor: {e}'}), content_type='application/json')      

    
    @http.route('/delete_zip', type='json', auth='user', methods=['POST'], csrf=False)
    def delete_zip(self, **kwargs):
        try:
            # Decode and load JSON request body to access file_name
            json_data = json.loads(request.httprequest.data.decode('utf-8'))
            file_name = json_data.get('file_name')  # Retrieve file_name from JSON data
            print(f"File name received for deletion: {file_name}")

            if not file_name:
                return {'error': 'No file name provided for deletion.'}

            working_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.working_folder_path')
            file_path = os.path.join(working_folder_path, file_name)

            # Attempt to delete the file
            if os.path.exists(file_path):
                os.remove(file_path)
                return {'success': f'File {file_name} deleted successfully.'}
            else:
                return {'error': f'File {file_name} does not exist in the specified path.'}

        except Exception as e:
            return {'error': f'Server error during file deletion: {str(e)}'}
        
                
    @http.route('/get_logs', type='http', auth='user', methods=['GET'], csrf=False)
    def get_logs(self, **kwargs):
        try:
            print("Obteniendo los logs...")

            # Obtener el nombre del archivo ZIP para extraer el cliente
            zip_filename = kwargs.get('zip_filename')
            if not zip_filename:
                return Response(json.dumps({'error': 'El nombre del archivo ZIP no fue proporcionado.'}), content_type='application/json')

            # Extraer los primeros 4 dígitos del nombre del archivo y eliminar ceros a la izquierda
            cliente = zip_filename[:4].lstrip('0')
            print(f'Cliente extraído del archivo: {cliente}')

            # Obtener la ruta base desde los parámetros de configuración
            clients_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.clients_folder_path')
            print(f'Clients_folder_path: {clients_folder_path}')

            if not clients_folder_path:
                return Response(json.dumps({'error': 'La ruta de la carpeta de clientes no está configurada.'}), content_type='application/json')

            # Suponiendo que el archivo de logs se encuentra en esta ruta
            log_filename = f"log_{datetime.now().strftime('%Y-%m-%d')}.txt"
            log_path = os.path.join(clients_folder_path, cliente, 'Logs', log_filename)
            print(f'Log_path: {log_path}')
            
            # Verificar si el archivo de log existe
            if not os.path.exists(log_path):
                print(f"Archivo de logs no encontrado: {log_path}")
                return Response(json.dumps({'error': 'No se encontró el archivo de logs.'}), content_type='application/json')

            # Leer el contenido del archivo de logs
            logs = None
            codificaciones = ['utf-8', 'ISO-8859-1', 'latin1', 'Windows-1252']
            for codificacion in codificaciones:
                try:
                    with open(log_path, 'r', encoding=codificacion) as log_file:
                        logs = log_file.readlines()  # Leer como lista de líneas
                        print(f'Archivo leído con la codificación {codificacion}')
                        break  # Si la lectura es exitosa, salimos del bucle
                except UnicodeDecodeError:
                    print(f'Error al leer con la codificación {codificacion}, probando otra...')
                    continue

            if logs is None:
                return Response(json.dumps({'error': 'Error al leer el archivo de logs con las codificaciones probadas.'}), content_type='application/json')

            # Buscar el último proceso completo
            start_message = "<--------------- Inicia el proceso --------------->"
            end_message = "<--------------- Conexion a la base de datos cerrada. --------------->"

            start_index = None
            end_index = None

            # Buscar el último inicio y fin del proceso en los logs
            for i in range(len(logs) - 1, -1, -1):  # Recorrer los logs al revés
                if end_message in logs[i] and end_index is None:
                    end_index = i
                if start_message in logs[i] and end_index is not None:
                    start_index = i
                    break

            # Extraer solo los logs entre el inicio y el fin del proceso
            if start_index is not None and end_index is not None and start_index < end_index:
                process_logs = logs[start_index:end_index + 1]
                logs_output = ''.join(process_logs)
            else:
                logs_output = 'No se encontró un proceso completo en los logs.'

            return Response(json.dumps({'logs': logs_output}), content_type='application/json')

        except Exception as e:
            print(f"Error al obtener los logs: {e}")
            return Response(json.dumps({'error': f'Error al obtener los logs: {e}'}), content_type='application/json')
        


    @http.route('/get_reports', type='http', auth='user', methods=['GET'], csrf=False)
    def get_reports(self):
        try:
            print("obteniendo reportes:")
            # Obtener la ruta a la carpeta '3-Sandbox' desde la configuración
            sandbox_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.sandbox_folder_path')
            print(f'Sandbox en get_report: {sandbox_folder_path}')
            if not sandbox_folder_path:
                return Response(json.dumps({'error': 'La ruta de la carpeta sandbox no está configurada.'}), content_type='application/json')

            # Buscar archivos con la extensión .sql.dump en la carpeta '3-Sandbox'
            report_files = []
            for file in os.listdir(sandbox_folder_path):
                if file.endswith('.sql.dump'):
                    report_files.append(file)

            # Devolver la lista de reportes
            return Response(json.dumps({'reports': report_files}), content_type='application/json')

        except Exception as e:
            return Response(json.dumps({'error': f'Error al obtener los reportes: {e}'}), content_type='application/json')





    @http.route('/get_report_data', type='http', auth='user', methods=['GET'], csrf=False)
    def get_report_data(self, **kwargs):
        try:
            report_name = kwargs.get('report_name')
            if not report_name:
                return json.dumps({'error': 'No se especificó el nombre del reporte.'})

            # Ruta del archivo .sql.dump
            clients_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.clients_folder_path')
            report_path = os.path.join(clients_folder_path, '3-Sandbox', f'{report_name}.sql.dump')

            if not os.path.exists(report_path):
                return json.dumps({'error': 'No se encontró el archivo del reporte.'})

            # Leer el archivo .sql.dump y extraer la estructura de la tabla y los datos
            columns = []
            rows = []
            inside_insert = False
            with open(report_path, 'r', encoding='utf-8') as file:
                for line in file:
                    if line.startswith('CREATE TABLE'):
                        # Procesar la estructura de la tabla
                        continue
                    elif line.startswith('INSERT INTO'):
                        inside_insert = True
                        continue
                    if inside_insert:
                        # Extraer los valores insertados
                        line = line.strip().strip(';')
                        values = line.split('VALUES')[1].strip()[1:-1]  # Eliminar paréntesis
                        rows.append([value.strip().strip("'") for value in values.split(',')])

            # Obtener los nombres de las columnas de la estructura de la tabla
            with open(report_path, 'r', encoding='utf-8') as file:
                for line in file:
                    if line.startswith('CREATE TABLE'):
                        inside_table = True
                        continue
                    if inside_table and '(' in line:
                        column_name = line.split(' ')[0]
                        columns.append(column_name)
                    elif inside_table and ')' in line:
                        break

            # Devolver columnas y filas como JSON
            return json.dumps({'columns': columns, 'rows': rows})
        except Exception as e:
            return json.dumps({'error': f'Error al procesar el reporte: {str(e)}'})




    @http.route('/get_report_content', type='json', auth='user', methods=['POST'])
    def get_report_content(self, **kwargs):
        try:
            # Obtener el cuerpo crudo de la solicitud
            json_data = json.loads(request.httprequest.data.decode('utf-8'))
            print(f"Datos recibidos del cuerpo de la solicitud: {json_data}")
            
            # Extraer el nombre del reporte
            report = json_data.get('report')
            
            if not report:
                return {'error': 'No se proporcionó un reporte válido.'}

            try:
                # Obtener el path base de la carpeta de reportes desde la configuración
                sandbox_folder_path = request.env['ir.config_parameter'].sudo().get_param('my_module.sandbox_folder_path')

                if not sandbox_folder_path:
                    return {'error': 'La ruta de la carpeta de Sandbox no está configurada.'}

                # Construir la ruta completa del archivo del reporte
                report_path = os.path.join(sandbox_folder_path, f'{report}.sql.dump')
                print(f'Report_path : {report_path}')

                # Verificar si la ruta es válida y si el archivo existe
                if not os.path.exists(report_path):
                    return {'error': 'No se encontró el archivo de reporte.'}

                # Leer el archivo del reporte
                with open(report_path, 'r', encoding='utf-8') as report_file:
                    lines = report_file.readlines()

                # Unir las líneas en un solo string para buscar el CREATE TABLE correctamente
                sql_content = " ".join(lines)

                # Buscar la definición de la tabla en el dump (CREATE TABLE)
                create_table_pattern = re.compile(r'CREATE TABLE.*?\((.*?)\);', re.S)
                create_table_match = create_table_pattern.search(sql_content)

                if not create_table_match:
                    return {'error': 'No se encontró la definición de la tabla en el dump.'}

                # Extraer las columnas de la definición de la tabla (Encabezados)
                columns_definition = create_table_match.group(1)
                print(f'columns_definition: {columns_definition}')

                # Limpiar los nombres de las columnas
                column_lines = [line.strip() for line in columns_definition.split(",") if line.strip()]
                headers = []
                for column_line in column_lines:
                    column_name = column_line.split()[0]  # Obtener el nombre de la columna
                    headers.append(column_name.strip('"'))  # Eliminar comillas si las tiene

                print(f'Headers: {headers}')

                # Buscar las filas de datos con los INSERT INTO
                insert_pattern = re.compile(r'INSERT INTO.*?VALUES\s*\((.*?)\);', re.S)
                rows = []
                for match in insert_pattern.finditer(sql_content):
                    values = match.group(1).split(",")
                    values = [value.strip().strip("'") for value in values]  # Limpiar comillas y espacios
                    rows.append(values)

                if not rows:
                    return {'error': 'No se encontraron datos en el dump.'}

                print(f'Rows: {rows}')

                return {'headers': headers, 'rows': rows}

            except Exception as e:
                return {'error': f'Error inesperado: {str(e)}'}

        except Exception as e:
            print(f"Error inesperado en el servidor: {str(e)}")
            return {'error': f'Error inesperado: {str(e)}'}