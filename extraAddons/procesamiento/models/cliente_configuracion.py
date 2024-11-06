from odoo import models, fields, api
from odoo.exceptions import ValidationError,UserError
from datetime import datetime
import json
import os
import zipfile
import io
import base64



class ClienteConfiguracion(models.Model):
    _name = 'cliente.configuracion'
    _description = 'Configuración de Cliente'

    nombre = fields.Char(string='Nombre')
    num_cliente = fields.Integer(string='Número de Cliente')
    branch = fields.Char(string='Branch')
    dms_id = fields.Many2one('modelo.dms', string="DMS", required=True)
    reportes_dms_ids = fields.Many2many('reporte.dms', string='Reportes del DMS')

    archivo_zip = fields.Binary(string="Archivo ZIP")
    nombre_archivo = fields.Char(string="Nombre del Archivo")
    

    @api.onchange('archivo_zip')
    def _onchange_archivo_zip(self):
        if self.archivo_zip and self.nombre_archivo:
            # Validar el nombre del archivo (8 dígitos)
            if len(self.nombre_archivo) == 12 and self.nombre_archivo.endswith('.zip'):
                archivo_sin_extension = self.nombre_archivo[:-4]  # Remueve la extensión .zip

                # Los primeros 4 dígitos son el número de cliente, 2 siguientes son el branch, 2 últimos son la fecha
                num_cliente_archivo = archivo_sin_extension[:4].lstrip('0')  # Remover ceros a la izquierda
                branch_archivo = archivo_sin_extension[4:6]
                

                # Comparar con el valor de la ficha
                if str(self.num_cliente) != num_cliente_archivo:
                    self.archivo_zip = False
                    self.nombre_archivo = False
                    raise UserError(f"El archivo cargado no coincide con el Número de Cliente ({self.num_cliente}).")

                if self.branch != branch_archivo:
                    self.archivo_zip = False
                    self.nombre_archivo = False
                    raise UserError(f"El archivo cargado no coincide con el Branch ({self.branch}).")
                
                # Validar los últimos dos dígitos con el día actual
                archivo_dia = archivo_sin_extension[6:8]
                dia_actual = datetime.today().strftime('%d')  # Día actual formateado con dos dígitos

                print(f'Archivo _dia : {archivo_dia} comparado contra dia _ {dia_actual}')
                # Si el día no coincide, mostrar un sticky note de advertencia
                if archivo_dia != dia_actual:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Advertencia',
                            'message': 'El archivo ZIP no corresponde al día actual. Se ha permitido la carga.',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
            else:
                self.archivo_zip = False
                self.nombre_archivo = False
                raise UserError("El nombre del archivo debe tener 8 dígitos y una extensión .zip.")
    
    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.num_cliente))
        return result

    def action_open_config(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reportes',
            'view_mode': 'tree,form',
            'res_model': 'configuracion.cliente',
            'target': 'current',
            'domain': [('num_cliente', '=', self.num_cliente), ('branch', '=', self.branch)],
            'context': {
                'default_nombre': self.nombre,
                'default_num_cliente': self.num_cliente,
                'default_branch': self.branch
            }
        }
    
        

    def generar_json_dms(self, dms_name, reportes, clients_folder_path):
        columnas_esperadas = {}

        # Obtener los detalles de los reportes asociados al DMS
        for reporte in reportes:
            # Obtener los detalles solo de los reportes que pertenecen al DMS actual (dms_name)
            detalle_reportes = self.env['reporte.dms.detalle'].search([
                ('reporte_id.nombre', '=', reporte),
                ('reporte_id.nombre_dms_origen', '=', dms_name)  # Filtrar por el DMS actual
            ])

            # Obtener el orden exportado de las columnas
            detalle_export_reportes = self.env['reporte.dms.detalle'].search([
                ('reporte_id.nombre', '=', reporte),
                ('reporte_id.nombre_dms_origen', '=', dms_name),
                ('orden_export', '!=', False)  # Asegurarse de que tengan un valor en el orden export
            ], order='orden_export')

            # Listado de columnas, fórmulas y tipos de datos de cada reporte
            columnas = []
            formulas = {}
            data_types = {}
            columnas_export = []
            filtros = []

            # Obtener todos los filtros configurados para el reporte actual
            filtros_records = self.env['filtros.reportes'].search([('reporte_id.nombre', '=', reporte)])
            for filtro in filtros_records:
                if filtro.expresion:
                    filtros.append(filtro.expresion)

            # Obtener todas las fórmulas configuradas para el reporte actual
            formula_records = self.env['formulas.reportes'].search([('reporte_id.nombre', '=', reporte)])
            for formula_record in formula_records:
                columna = formula_record.columna_seleccionada.columna
                expresion_formula = formula_record.expresion

                # Agregar "(computed)" en formulas solo si la columna tiene compute_field en True
                if formula_record.columna_seleccionada.compute_field:
                    columna = f"{columna} (computed)"

                formulas[columna] = expresion_formula or False  # Asignar la fórmula si existe, sino False

            # Recorrer los detalles del reporte
            for detalle in detalle_reportes:
                # Determinar el nombre de la columna, con asteriscos si es invisible
                if detalle.invisible:
                    columna_nombre = f"*{detalle.columna}*"
                else:
                    columna_nombre = detalle.columna
                    # Agregar "(computed)" solo en columnas y columnas_export si compute_field está en True
                    if detalle.compute_field:
                        columna_nombre += " (computed)"
                    
                    # Añadir a formulas si aún no está presente (evitar duplicación de invisibles)
                    if columna_nombre not in formulas:
                        formulas[columna_nombre] = False

                columnas.append(columna_nombre)

                # Definir tipos de datos y longitud
                data_types[detalle.columna] = {
                    "tipo": detalle.tipo_dato,
                    "length": f"{detalle.longitud}, 2" if detalle.tipo_dato == 'decimal' else (
                        detalle.longitud if detalle.tipo_dato == 'varchar' else None
                    )
                }

            # Recorrer los detalles exportados del reporte
            for detalle_export in detalle_export_reportes:
                # Agregar la columna en el orden exportado
                columna_export_nombre = detalle_export.columna
                if detalle_export.compute_field:
                    columna_export_nombre += " (computed)"
                columnas_export.append(columna_export_nombre)

            # Si no se encuentra un orden exportado, usar el orden normal de detalle_reportes
            if not columnas_export:
                columnas_export = columnas

            columnas_esperadas[reporte] = {
                'columnas': columnas,
                'columnas_export': columnas_export,  # Agregar la clave 'columnas_export'
                'formulas': formulas,
                'filtros': filtros,
                'data_types': data_types
            }

        # Estructura del JSON del DMS
        dms_json = {
            'name': dms_name,
            'reportes': reportes,
            'columnas_esperadas': columnas_esperadas
        }

        # Crear la carpeta dms si no existe
        dms_folder_path = os.path.join(clients_folder_path, 'dms')
        if not os.path.exists(dms_folder_path):
            os.makedirs(dms_folder_path)

        # Guardar el JSON en un archivo dentro de la carpeta dms
        dms_filename = os.path.join(dms_folder_path, f"{dms_name}.json")
        with open(dms_filename, 'w') as json_file:
            json.dump(dms_json, json_file, indent=4)

        print(f"Archivo {dms_filename} generado con éxito")


    # Método para generar y guardar JSON
    def generar_json(self):
        registros = []

        # Obtener la ruta de la carpeta CLIENTS desde los ajustes de Odoo
        clients_folder_path = self.env['ir.config_parameter'].sudo().get_param('my_module.clients_folder_path', default=False)

        # Validar si la ruta está configurada
        if not clients_folder_path:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No se ha configurado la ruta de la carpeta CLIENTS. Configúrela en los Ajustes.',
                    'type': 'danger',
                    'sticky': True,
                }
            }

        # Obtener el cliente configurado con el num_cliente y branch actual
        for cliente in self:
            dms_reportes = {}

            # Buscar configuraciones del cliente en la tabla configuracion.cliente
            configuraciones_cliente = self.env['configuracion.cliente'].search([
                ('num_cliente', '=', cliente.num_cliente),
                ('branch', '=', cliente.branch)
            ])

            # Verificar si existen configuraciones del cliente
            if not configuraciones_cliente:
                raise UserError(f"No se encontraron configuraciones para el cliente {cliente.num_cliente} en la sucursal {cliente.branch}.")

            # Verificar si hay reportes configurados en `reportes_dms_ids`
            for configuracion in configuraciones_cliente:
                for reporte in configuracion.reportes_dms_ids:
                    # Agrupa los reportes por `nombre_dms_origen`
                    if reporte.nombre_dms_origen not in dms_reportes:
                        dms_reportes[reporte.nombre_dms_origen] = []
                    dms_reportes[reporte.nombre_dms_origen].append(reporte.nombre)

            # Crear el registro para el JSON del cliente
            registros.append({
                'sucursal': cliente.nombre,
                'branch': cliente.branch,
                'dms': dms_reportes  # Agrega los reportes configurados
            })

            # JSON final del cliente
            json_cliente = {
                'registros': registros
            }

            # Guardar el JSON del cliente en su carpeta
            self.guardar_json_cliente(json_cliente, cliente, clients_folder_path)

            # Para cada DMS, generar y guardar su JSON correspondiente
            for dms_name, reportes in dms_reportes.items():
                self.generar_json_dms(dms_name, reportes, clients_folder_path)

    # Método para guardar el JSON del cliente
    def guardar_json_cliente(self, json_cliente, cliente, clients_folder_path):
        # Crear la carpeta del cliente si no existe
        client_folder = os.path.join(clients_folder_path, str(cliente.num_cliente))
        if not os.path.exists(client_folder):
            os.makedirs(client_folder)

        # Guardar el JSON del cliente en la carpeta del cliente
        json_filename = os.path.join(client_folder, f"{cliente.num_cliente}.json")
        with open(json_filename, 'w') as json_file:
            json.dump(json_cliente, json_file, indent=4)

        print(f"Archivo {json_filename} generado con éxito")

    # Método para ejecutar la acción de generar JSON
    def action_generar_json(self):
        # Llamar al método generar_json cuando se presione el botón
        json_resultado = self.generar_json()

        # Mostrar notificación al usuario sobre la generación del JSON
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'JSON generado',
                'message': 'Los JSON han sido generados y guardados correctamente.',
                'type': 'success',
                'sticky': False,
            }
        }
    

    

    def cargar_json_a_odoo(self):
        # Obtener la ruta de la carpeta CLIENTS desde los ajustes de Odoo
        clients_folder_path = self.env['ir.config_parameter'].sudo().get_param('my_module.clients_folder_path', default=False)
        if not clients_folder_path:
            raise UserError("La ruta de la carpeta CLIENTS no está configurada. Configúrela en los Ajustes.")

        dms_folder_path = os.path.join(clients_folder_path, 'dms')
        
        if not os.path.exists(dms_folder_path):
            raise UserError('La carpeta DMS no existe en la ruta especificada.')

        # Cargar archivos JSON de clientes y DMS
        for root, _, files in os.walk(dms_folder_path):
            print(f'Files: {files}')
            for filename in files:

                if filename.endswith(".json"):
                    dms_name = os.path.splitext(filename)[0]
                    print(f'dms_name: {dms_name}')
                    dms_filepath = os.path.join(root, filename)

                    # Leer el archivo JSON de DMS
                    with open(dms_filepath, 'r') as json_file:
                        dms_data = json.load(json_file)

                    # Obtener el ID del DMS correspondiente en `modelo.dms`
                    dms_model = self.env['modelo.dms'].search([('nombre_dms', '=', dms_name)])
                    print(f'dms_model: {dms_model}')
                    if not dms_model:
                        raise UserError(f"No se encontró un registro en modelo.dms con nombre '{dms_name}'.")

                    # Obtener o crear el registro en `cliente.configuracion`
                    dms_records = self.env['cliente.configuracion'].search([('dms_id', '=', dms_model.id)])
                    print(f'Dms_records: {dms_records}')
                    if not dms_records:
                        # Crear un nuevo registro si no existe
                        dms_record = self.env['cliente.configuracion'].create({
                            'dms_id': dms_model.id,
                            'reportes_dms_ids': []
                        })
                    else:
                        # Si existe, usar el primer registro encontrado
                        dms_record = dms_records[0]
                    
                    # Actualizar o crear reportes DMS
                    for reporte, detalles in dms_data['columnas_esperadas'].items():
                        reporte_record = self.env['reporte.dms.detalle'].search([
                            ('reporte_id.nombre', '=', reporte),
                            ('reporte_id.nombre_dms_origen', '=', dms_name)
                        ], limit=1)

                        if not reporte_record:
                            # Crear el reporte si no existe
                            reporte_record = self.env['reporte.dms.detalle'].create({
                                'reporte_id': dms_record.id,
                                'nombre': reporte,
                                'nombre_dms_origen': dms_name,
                                'columnas': detalles['columnas'],
                                'columnas_export': detalles['columnas_export'],
                                'formulas': detalles['formulas'],
                                'data_types': detalles['data_types']
                            })
                        else:
                            # Actualizar los detalles si ya existe el reporte
                            reporte_record.write({
                                'columnas': detalles['columnas'],
                                'columnas_export': detalles['columnas_export'],
                                'formulas': detalles['formulas'],
                                'data_types': detalles['data_types']
                            })
                    
                    print(f"Archivo {filename} procesado exitosamente.")

        # Leer el archivo JSON de clientes
        cliente_filepath = os.path.join(clients_folder_path, 'clientes.json')
        if os.path.exists(cliente_filepath):
            with open(cliente_filepath, 'r') as json_file:
                cliente_data = json.load(json_file)

            # Procesar cada registro de cliente
            for registro in cliente_data['registros']:
                cliente_name = registro['sucursal']
                cliente_branch = registro['branch']

                # Buscar o crear el cliente en `cliente.configuracion`
                cliente_record = self.env['cliente.configuracion'].search([
                    ('nombre', '=', cliente_name),
                    ('branch', '=', cliente_branch)
                ], limit=1)

                if not cliente_record:
                    # Crear el cliente si no existe
                    cliente_record = self.env['cliente.configuracion'].create({
                        'nombre': cliente_name,
                        'branch': cliente_branch,
                        'reportes_dms_ids': []
                    })

                # Actualizar o crear reportes DMS para el cliente
                for dms_name, reportes in registro['dms'].items():
                    # Obtener el ID del DMS en `modelo.dms`
                    dms_model = self.env['modelo.dms'].search([('nombre', '=', dms_name)], limit=1)
                    if not dms_model:
                        raise UserError(f"No se encontró un registro en modelo.dms con nombre '{dms_name}'.")

                    for reporte in reportes:
                        reporte_record = self.env['reporte.dms.detalle'].search([
                            ('reporte_id.nombre', '=', reporte),
                            ('reporte_id.nombre_dms_origen', '=', dms_name)
                        ], limit=1)

                        if not reporte_record:
                            # Crear el reporte si no existe
                            reporte_record = self.env['reporte.dms.detalle'].create({
                                'reporte_id': cliente_record.id,
                                'nombre': reporte,
                                'nombre_dms_origen': dms_name
                            })
                        else:
                            # Actualizar el reporte si ya existe
                            reporte_record.write({
                                'reporte_id': cliente_record.id,
                                'nombre': reporte,
                                'nombre_dms_origen': dms_name
                            })

                print(f"Cliente {cliente_name} procesado exitosamente.")

class ConfigCliente(models.Model):
    _name = 'configuracion.cliente'
    _description = 'Configuración Cliente'

    nombre = fields.Char(string='Nombre', default=lambda self: self.env.context.get('default_nombre', ''))
    num_cliente = fields.Integer(string='Número de Cliente', default=lambda self: self.env.context.get('default_num_cliente', 0))
    branch = fields.Char(string='Branch', default=lambda self: self.env.context.get('default_branch', ''))
    dms_id = fields.Many2one('modelo.dms', string='DMS', domain=[('activo', '=', True)], required=True)
    reportes_dms_ids = fields.Many2many(
        'reporte.dms',
        string='Reportes del DMS',
        domain="[('nombre_dms_origen', '=', dms_id.nombre_dms)]"
    )

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.dms_id.nombre_dms))
        return result

    @api.model
    def create(self, vals):
        print(f"vals: {vals.get('dms_id')}")
        dms_id = vals.get('dms_id')
        # Verificar si los valores están en vals, de lo contrario tomar del contexto
        num_cliente = vals.get('num_cliente', self.env.context.get('default_num_cliente'))
        branch = vals.get('branch', self.env.context.get('default_branch'))

        print(f'Num_cliente: {num_cliente} y el branch : {branch}')

        # Buscar en cliente.configuracion para confirmar la existencia
        cliente_config = self.env['configuracion.cliente'].search([
            ('num_cliente', '=', num_cliente),
            ('branch', '=', branch)
        ])
        
        print(f'Cliente config : {cliente_config.dms_id}, dms_id: {dms_id}, cliente_confit: {cliente_config}')
        for a in cliente_config:
            if a.dms_id.id == dms_id :
                raise ValidationError(f"El DMS {a.dms_id.nombre_dms} ya se encuentra registrado en el Cliente {num_cliente}, branch {branch}")

        return super(ConfigCliente, self).create(vals)

    @api.onchange('dms_id')
    def _onchange_dms_id(self):
        if self.dms_id:
            self.reportes_dms_ids = False  # Limpiar los reportes actuales antes de establecer el nuevo dominio
            return {
                'domain': {'reportes_dms_ids': [('nombre_dms_origen', '=', self.dms_id.nombre_dms)]},
                'value': {'reportes_dms_ids': [(5,)]}  # Comando para eliminar todos los registros existentes en el campo Many2many
            }
        else:
            return {'domain': {'reportes_dms_ids': []}}


    def write(self, vals):
        # Verificar si el DMS está siendo actualizado y si cumple las condiciones
        if 'dms_id' in vals or 'branch' in vals or 'num_cliente' in vals:
            dms_id = vals.get('dms_id', self.dms_id.id)
            branch = vals.get('branch', self.branch)
            num_cliente = vals.get('num_cliente', self.num_cliente)

            existing = self.search([
                ('dms_id', '=', dms_id),
                ('branch', '=', branch),
                ('num_cliente', '=', num_cliente),
                ('id', '!=', self.id)  # Excluir el registro actual de la búsqueda
            ], limit=1)
            if existing:
                raise ValidationError("El DMS seleccionado ya está en uso para el mismo branch y número de cliente.")

        # Actualizar el registro
        return super(ConfigCliente, self).write(vals)
