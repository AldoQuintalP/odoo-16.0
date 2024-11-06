from odoo import models, fields, api
import zipfile
from io import BytesIO
import base64

class ConfigInicial(models.Model):
    _name = 'config.inicial'
    _description = 'Configuración Inicial'

    archivo_zip = fields.Binary(string="Archivo ZIP", attachment=True)
    nombre_archivo = fields.Char(string="Nombre del Archivo")
    archivos_listados = fields.One2many('config.inicial.archivo', 'config_id', string="Reportes en ZIP")
    cliente = fields.Char(string="Cliente", compute='_compute_cliente', store=True)


    @api.depends('nombre_archivo')
    def _compute_cliente(self):
        for record in self:
            if record.nombre_archivo and record.nombre_archivo[:4].isdigit():
                # Extrae los primeros cuatro dígitos y elimina ceros a la izquierda
                record.cliente = str(int(record.nombre_archivo[:4]))
            else:
                record.cliente = ''

    @api.onchange('archivo_zip')
    def _onchange_archivo_zip(self):
        if self.archivo_zip:
            if not self.nombre_archivo or not self.nombre_archivo.endswith('.zip'):
                self.archivo_zip = False
                self.nombre_archivo = False
                raise models.ValidationError("El archivo debe ser un archivo ZIP válido.")
            try:
                zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(self.archivo_zip)))
                zip_file.testzip()  # Verifica que el ZIP no esté corrupto

                # Limpiar registros anteriores de archivos listados y llenar con los nuevos archivos
                archivos = [
                    (0, 0, {
                        'nombre_archivo': archivo,
                        'comentario': ''  # Deja el comentario vacío inicialmente
                    }) for archivo in zip_file.namelist()
                ]
                self.archivos_listados = archivos

            except zipfile.BadZipFile:
                self.archivo_zip = False
                self.nombre_archivo = False
                raise models.ValidationError("El archivo ZIP está corrupto o no es válido.")

    def write(self, vals):
        # Guardar el nombre del archivo si se sube un nuevo ZIP
        if 'archivo_zip' in vals:
            vals['nombre_archivo'] = self.nombre_archivo or vals.get('nombre_archivo')
            
            # Reprocesar archivos ZIP para mantener los registros extraídos
            zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(vals['archivo_zip'])))
            archivos_nuevos = zip_file.namelist()
            
            # Preservar comentarios existentes
            archivos_actualizados = []
            for archivo in self.archivos_listados:
                if archivo.nombre_archivo in archivos_nuevos:
                    archivos_actualizados.append((1, archivo.id, {'comentario': archivo.comentario}))
                    archivos_nuevos.remove(archivo.nombre_archivo)
            
            # Agregar archivos nuevos sin comentario
            archivos_actualizados += [
                (0, 0, {
                    'nombre_archivo': archivo,
                    'comentario': ''
                }) for archivo in archivos_nuevos
            ]
            
            vals['archivos_listados'] = archivos_actualizados

        return super(ConfigInicial, self).write(vals)

    @api.model
    def create(self, vals):
        # Guardar el nombre del archivo al crear un nuevo registro si tiene un ZIP
        if 'archivo_zip' in vals:
            vals['nombre_archivo'] = vals.get('nombre_archivo')
            
            # Procesar archivos ZIP para extraer los nombres de archivos al crear el registro
            zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(vals['archivo_zip'])))
            archivos = [
                (0, 0, {
                    'nombre_archivo': archivo,
                    'comentario': ''
                }) for archivo in zip_file.namelist()
            ]
            vals['archivos_listados'] = archivos

        return super(ConfigInicial, self).create(vals)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.nombre_archivo or f'config.inicial,{record.id}'))
        return result

class ConfigInicialArchivo(models.Model):
    _name = 'config.inicial.archivo'
    _description = 'Archivo en Configuración Inicial'

    nombre_archivo = fields.Char(string="Nombre del Archivo", readonly=True)
    comentario = fields.Char(string="Comentario")  # Campo de texto editable para el usuario
    config_id = fields.Many2one('config.inicial', string="Configuración", ondelete='cascade')
