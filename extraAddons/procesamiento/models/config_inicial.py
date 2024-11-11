from odoo import models, fields, api
from odoo.exceptions import ValidationError
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
    num_cliente = fields.Integer(string='Número de Cliente') 
    branch = fields.Char(string='Branch') 


    @api.model
    def create(self, vals):
        # Llama al procesamiento del archivo ZIP al crear el registro si viene en el contexto
        record = super(ConfigInicial, self).create(vals)
        if vals.get('archivo_zip'):
            record.procesar_zip_archivo()
        return record

    @api.onchange('archivo_zip')
    def _onchange_archivo_zip(self):
        if self.archivo_zip:
            # Valida que el archivo tenga un nombre correcto
            if not self.nombre_archivo or not self.nombre_archivo.endswith('.zip'):
                self.archivo_zip = False
                self.nombre_archivo = False
                raise ValidationError("El archivo debe ser un archivo ZIP válido.")
            self.procesar_zip_archivo()  # Procesa el archivo ZIP al cambiar

    def procesar_zip_archivo(self):
        """Procesa el archivo ZIP cargado y extrae números únicos de los nombres de archivo."""
        if not self.archivo_zip:
            return

        try:
            zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(self.archivo_zip)))
            zip_file.testzip()  # Verifica que el ZIP no esté corrupto

            # Extrae números únicos de los nombres de archivo
            nombres_unicos = set()
            archivos = []

            for archivo in zip_file.namelist():
                numero = ''.join(filter(str.isdigit, archivo))
                if numero and numero not in nombres_unicos:
                    nombres_unicos.add(numero)
                    archivos.append((0, 0, {
                        'nombre_archivo': numero,
                        'comentario': ''
                    }))

            if archivos:
                # Limpiar registros anteriores
                self.archivos_listados = [(5, 0, 0)]
                self.archivos_listados = archivos

        except zipfile.BadZipFile:
            self.archivo_zip = False
            self.nombre_archivo = False
            raise ValidationError("El archivo ZIP está corrupto o no es válido.")

    # @api.onchange('archivo_zip')
    # def _onchange_archivo_zip(self):
    #     if self.archivo_zip:
    #         if not self.nombre_archivo or not self.nombre_archivo.endswith('.zip'):
    #             self.archivo_zip = False
    #             self.nombre_archivo = False
    #             raise models.ValidationError("El archivo debe ser un archivo ZIP válido.")
            
    #         try:
    #             zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(self.archivo_zip)))
    #             zip_file.testzip()  # Verifica que el ZIP no esté corrupto

    #             # Extraer los números únicos de los nombres de archivo
    #             nombres_unicos = set()
    #             archivos = []
                
    #             for archivo in zip_file.namelist():
    #                 # Extraer solo el número del nombre de archivo (por ejemplo, "001" de "REFCOM001.txt")
    #                 numero = ''.join(filter(str.isdigit, archivo))
    #                 if numero and numero not in nombres_unicos:
    #                     nombres_unicos.add(numero)
    #                     archivos.append((0, 0, {
    #                         'nombre_archivo': numero,
    #                         'comentario': ''
    #                     }))
                
    #             # Limpiar registros anteriores y agregar solo los archivos únicos
    #             self.archivos_listados = archivos

    #         except zipfile.BadZipFile:
    #             self.archivo_zip = False
    #             self.nombre_archivo = False
    #             raise models.ValidationError("El archivo ZIP está corrupto o no es válido.")


    # def write(self, vals):
    #     # Guardar el nombre del archivo si se sube un nuevo ZIP
    #     if 'archivo_zip' in vals:
    #         vals['nombre_archivo'] = self.nombre_archivo or vals.get('nombre_archivo')
            
    #         # Reprocesar archivos ZIP para mantener los registros extraídos
    #         zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(vals['archivo_zip'])))
    #         archivos_nuevos = zip_file.namelist()
            
    #         # Preservar comentarios existentes
    #         archivos_actualizados = []
    #         for archivo in self.archivos_listados:
    #             if archivo.nombre_archivo in archivos_nuevos:
    #                 archivos_actualizados.append((1, archivo.id, {'comentario': archivo.comentario}))
    #                 archivos_nuevos.remove(archivo.nombre_archivo)
            
    #         # Agregar archivos nuevos sin comentario
    #         archivos_actualizados += [
    #             (0, 0, {
    #                 'nombre_archivo': archivo,
    #                 'comentario': ''
    #             }) for archivo in archivos_nuevos
    #         ]
            
    #         vals['archivos_listados'] = archivos_actualizados

    #     return super(ConfigInicial, self).write(vals)

    # @api.model
    # def create(self, vals):
    #     # Guardar el nombre del archivo al crear un nuevo registro si tiene un ZIP
    #     if 'archivo_zip' in vals:
    #         vals['nombre_archivo'] = vals.get('nombre_archivo')
            
    #         # Procesar archivos ZIP para extraer los nombres de archivos al crear el registro
    #         zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(vals['archivo_zip'])))
    #         archivos = [
    #             (0, 0, {
    #                 'nombre_archivo': archivo,
    #                 'comentario': ''
    #             }) for archivo in zip_file.namelist()
    #         ]
    #         vals['archivos_listados'] = archivos

    #     return super(ConfigInicial, self).create(vals)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.nombre_archivo or f'config.inicial,{record.id}'))
        return result

class ConfigInicialArchivo(models.Model):
    _name = 'config.inicial.archivo'
    _description = 'Archivo en Configuración Inicial'

    nombre_archivo = fields.Char(string="Nombre del Archivo", readonly=True)
    comentario = fields.Char(string="Branch")  # Campo de texto editable para el usuario
    config_id = fields.Many2one('config.inicial', string="Configuración", ondelete='cascade')
