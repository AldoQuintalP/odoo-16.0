import zipfile
import base64
from io import BytesIO
from odoo import models, fields, api

class ProcesamientoDashboard(models.TransientModel):
    _name = 'procesamiento.dashboard'
    _description = 'Dashboard de Procesamiento'

    file_zip = fields.Binary(string="Subir ZIP")
    file_name = fields.Char(string="Nombre del Archivo")

    def process_zip_file(self):
        if self.file_zip:
            zip_file = zipfile.ZipFile(BytesIO(base64.b64decode(self.file_zip)))
            for file in zip_file.namelist():
                # Aquí procesas cada archivo dentro del ZIP sin almacenarlo en la base de datos
                pass
