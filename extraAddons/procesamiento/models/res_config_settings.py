from odoo import models, fields, api
import json
import os

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    clients_folder_path = fields.Char(
        string="Ruta de la carpeta CLIENTS",
        config_parameter='my_module.clients_folder_path',
        help="Directorio para almacenar los archivos de clientes.")
    
    working_folder_path = fields.Char(
        string="Ruta de la carpeta 2-Working",
        config_parameter='my_module.working_folder_path',
        help="Directorio para colocar el archivo .zip a procesar.")
    
    sandbox_folder_path = fields.Char(
        string="Ruta de la carpeta 3-Sandbox",
        config_parameter='my_module.sandbox_folder_path',
        help="Directorio para almacenar los resultados del procesamiento.")
    
    python_path = fields.Char(
        string="Ruta del Python procesamiento",
        config_parameter='my_module.python_path',
        help="Path del python encargado de realizar el procesamiento.")
    
    host = fields.Char(
        string="Host",
        config_parameter='my_module.host',
        help="IP del servidor")
    
    user = fields.Char(
        string="Usuario BD",
        config_parameter='my_module.user',
        help="Usuario de la base de datos")
    
    bd_name = fields.Char(
        string="Nombre de la Base",
        config_parameter='my_module.bd_name',
        help="Nombre de la Base de datos")
    
    password = fields.Char(
        string="Contraseña",
        config_parameter='my_module.password',
        help="Contraseña")

    def generar_json_configuracion(self):
        # Reunir los valores de los campos en el formato deseado
        configuracion = {
            "clients_dir": self.clients_folder_path,
            "working_dir": self.working_folder_path,
            "sandbox_dir": self.sandbox_folder_path,
            "core_dir": self.python_path,
            "host": self.host,
            "user": self.user,
            "bd_name": self.bd_name,
            "password": self.password
        }
        
        # Verificar la ruta de python_path
        ruta_json = os.path.join(self.python_path, "configuracion.json")
        
        try:
            # Guardar el archivo JSON en la ruta especificada
            with open(ruta_json, 'w') as json_file:
                json.dump(configuracion, json_file, indent=4)
            
            # Notificación de éxito
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'JSON generado',
                    'message': f'El archivo JSON se ha guardado en {ruta_json}.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            # Notificación de error
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error al generar JSON',
                    'message': f'Error: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    # Botón para ejecutar la función de generación del JSON
    def action_generar_json(self):
        return self.generar_json_configuracion()
