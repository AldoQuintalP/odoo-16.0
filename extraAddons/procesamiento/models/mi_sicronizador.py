from odoo import models, fields, api
import json
from odoo.exceptions import ValidationError

class SincronizadorReportes(models.Model):
    _name = 'sincronizador.reportes'
    _description = 'Sincronizador de Reportes de Clientes'

    def generar_json(self):
        # Inicializamos la estructura final del JSON
        registros = []

        # Obtenemos todas las configuraciones de clientes
        clientes_config = self.env['cliente.configuracion'].search([])

        # Iteramos sobre cada cliente configurado
        for cliente in clientes_config:
            sucursal_data = {
                "sucursal": cliente.nombre,  # Nombre de la sucursal/cliente
                "branch": cliente.branch,  # Branch del cliente
                "dms": {}  # Inicializamos la estructura de DMS
            }

            # Obtenemos los DMS configurados para este cliente
            dms_config = cliente.dms_id

            # Iteramos sobre los DMS y agrupamos los reportes por DMS
            if dms_config:
                for dms in dms_config:
                    # Inicializamos la lista de reportes por DMS
                    reportes_dms = []

                    # Obtenemos los reportes asociados al DMS actual
                    reportes = self.env['reporte.dms'].search([('dms_id', '=', dms.id)])

                    # Agregamos los nombres de los reportes al array de reportes del DMS
                    for reporte in reportes:
                        reportes_dms.append(reporte.nombre)

                        # Obtenemos las columnas de 'detalle_ids' (esperadas) y 'detalle_export_ids' (orden exportado)
                        columnas_esperadas = [detalle.columna for detalle in reporte.detalle_ids]
                        print(f'Columnas_esperadas: {columnas_esperadas}')
                        columnas_export = [detalle_export.columna for detalle_export in reporte.detalle_export_ids]
                        print(f'Columnas_export: {columnas_export}')

                        # Armamos la estructura de las columnas del reporte
                        sucursal_data["dms"][dms.nombre_dms] = {
                            "columnas": columnas_esperadas,
                            "columnas_export": columnas_export,  # Agregar la clave 'columnas_export'
                            "formulas": {
                                detalle.columna: False for detalle in reporte.detalle_ids
                            },
                            "data_types": {
                                detalle.columna: {
                                    "tipo": detalle.tipo_dato,
                                    "length": detalle.longitud
                                } for detalle in reporte.detalle_ids
                            }
                        }

            # Añadimos la sucursal con sus DMS y reportes al array de registros
            registros.append(sucursal_data)

        # Estructura final
        json_final = {
            "registros": registros
        }

        # Convertimos el diccionario a JSON
        json_string = json.dumps(json_final, indent=4)

        # Puedes retornar el JSON para que lo puedas guardar o visualizar
        return json_string

    # Acción del botón para generar el JSON
    def action_generar_json(self):
        json_resultado = self.generar_json()
        # Aquí puedes hacer algo con el JSON generado, por ejemplo, guardarlo en un archivo o mostrarlo
        raise ValidationError(f'JSON Generado: {json_resultado}')

