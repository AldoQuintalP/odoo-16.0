from odoo import models, fields, api
from odoo.exceptions import ValidationError
from collections import Counter
import zipfile
import pandas as pd
from io import BytesIO
from io import StringIO
import base64
import re
import chardet
import tempfile
import datetime

class ModeloDMS(models.Model):
    _name = 'modelo.dms'
    _description = 'Modelo DMS'

    nombre_dms = fields.Char(string="Nombre del DMS", required=True)
    activo = fields.Boolean(string="Activo", default=True)
    es_favorito = fields.Boolean("Es Favorito")
    reporte_ids = fields.One2many('reporte.dms', 'dms_id', string="Reportes")
    report_count = fields.Integer(string="Número de Reportes", compute="_compute_report_count")


    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.nombre_dms))
        return result

    def action_open_reports(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear Reporte DMS',
            'view_mode': 'tree,form',
            'res_model': 'reporte.dms',
            'target': 'current',
            'domain': [('nombre_dms_origen', '=', self.nombre_dms)],
            'context': {'default_nombre_dms_origen': self.nombre_dms} 
        }

    @api.depends('reporte_ids')
    def _compute_report_count(self):
        for record in self:
            record.report_count = len(record.reporte_ids)


class FormulasReportes(models.Model):
    _name = 'formulas.reportes'
    _description = 'Formulas Reportes'

    reporte_id = fields.Many2one('reporte.dms', string="Reporte DMS")
    columnas_reporte_ids = fields.Many2many('reporte.dms.detalle', compute="_compute_columnas_reporte")
    expresion = fields.Text(string="Expresión")
    cliente = fields.Integer(string='Número de Cliente')
    branch = fields.Char(string='Branch')


    tabla_html = fields.Html(string='Tabla Procesada')
    columna_seleccionada = fields.Many2one(
        'reporte.dms.detalle',
        string="Columna Seleccionada",
        domain="[('reporte_id', '=', reporte_id)]",  # Filtra columnas según el reporte seleccionado
        readonly=False,  # El campo es seleccionable pero no editable ni creable
        create=False,    # Desactiva la opción de crear nuevas columnas
        edit=False,      # Desactiva la opción de editar la selección directamente
        required=True    # Asegúrate de que se seleccione una columna
    )

    @api.onchange('columna_seleccionada')
    def _onchange_columna_seleccionada(self):
        """
        Este método se ejecuta cada vez que cambia la columna seleccionada.
        Configura la expresión automáticamente según el tipo de dato o nombre de la columna.
        """
        if self.columna_seleccionada:
            columna_nombre = self.columna_seleccionada.columna
            tipo_dato = self.columna_seleccionada.tipo_dato

            # Caso especial para la columna "Date"
            if columna_nombre == "Date":
                self.expresion = 'Ctod("d/m/y")'

            # Caso especial para columnas de tipo Email o Mail
            elif 'email' in columna_nombre.lower() or 'mail' in columna_nombre.lower():
                self.expresion = f'LimpiaEmail({columna_nombre})'

            # Si el tipo de dato es varchar
            elif tipo_dato == 'varchar':
                self.expresion = f'LimpiaTexto({columna_nombre})'

            # Si el tipo de dato es decimal
            elif tipo_dato == 'decimal':
                self.expresion = f'LimpiaCodigos({columna_nombre})'

            # Si no cumple ninguna condición, dejar la expresión en blanco
            else:
                self.expresion = ''
        else:
            self.expresion = ''

    def action_guardar(self):
        try:
            # Guarda el registro
            self.ensure_one()
            self.write({})  # Esto guarda el registro sin realizar ningún cambio adicional
            
            # Mostrar una notificación de éxito
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Éxito',
                    'message': 'Los cambios fueron guardados con éxito.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Hubo un error al guardar: {str(e)}',
                    'type': 'danger',
                    'sticky': False,
                }
            }

    @api.depends('reporte_id')
    def _compute_columnas_reporte(self):
        for record in self:
            if record.reporte_id:
                record.columnas_reporte_ids = [(6, 0, record.reporte_id.detalle_ids.ids)]
            else:
                record.columnas_reporte_ids = [(5,)]

    def action_add_columna_to_expresion(self):
        # Obtener el ID de la columna desde el contexto
        columna_id = self.env.context.get('columna_id')
        if columna_id:
            columna = self.env['reporte.dms.detalle'].browse(columna_id).columna
            # Si existe la columna, añadirla a la expresión
            for record in self:
                if columna:
                    if record.expresion:
                        record.expresion += f" {columna}"
                    else:
                        record.expresion = columna
    

    def action_procesar(self):
        # Obtener el cliente y branch del registro actual
        cliente_num = self.cliente
        branch = self.branch
        reporte_dms = self.reporte_id.nombre  # Nombre del reporte
        print(f'reporte_dms: {reporte_dms}')

        # Buscar en cliente.configuracion si tiene ZIP cargado para el cliente y branch
        cliente_config = self.env['cliente.configuracion'].search([
            ('num_cliente', '=', cliente_num),
            ('branch', '=', branch)
        ], limit=1)

        if not cliente_config or not cliente_config.archivo_zip:
            # Mostrar un mensaje si no hay ZIP cargado
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Advertencia',
                    'message': f'No hay archivo ZIP cargado para el cliente {cliente_num} y branch {branch}.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        try:
            # Decodificar el contenido del archivo ZIP desde Base64
            zip_file_content = base64.b64decode(cliente_config.archivo_zip)  # Decodifica el archivo ZIP cargado

            # Leer el archivo ZIP desde el contenido binario decodificado
            zipfile_obj = zipfile.ZipFile(BytesIO(zip_file_content))

            print(f'Zip_obj: {zipfile_obj}')

        except zipfile.BadZipFile:
            # Manejo del error en caso de que no sea un archivo ZIP válido
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de archivo',
                    'message': 'El archivo cargado no es un ZIP válido. Por favor, cargue un archivo ZIP válido.',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        found_file = None
        pattern = re.sub(r'\d', '', reporte_dms)  # Elimina todos los números del nombre del reporte
        print(f'Pattern: {pattern}')

        for file_name in zipfile_obj.namelist():
            # Elimina números del nombre de archivo y compara solo las letras
            file_name_no_digits = re.sub(r'\d', '', file_name)
            print(f'File_name: {file_name_no_digits}')
            
            if pattern in file_name_no_digits:
                found_file = file_name
                break

        if not found_file:
            # Mostrar una alerta si no se encuentra el reporte dentro del ZIP
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'No se encontró el reporte {reporte_dms} en el ZIP cargado para el cliente {cliente_num} y branch {branch}.',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        
        print("Vamos armar el DF")
        print(f'Found_file: {found_file}')

        # Leer el contenido del archivo encontrado en el ZIP
        with zipfile_obj.open(found_file) as file:
            print(f'File: {file}')
            
            # Leer el contenido del archivo
            rawdata = file.read()
            
            # Detectar la codificación del archivo
            result = chardet.detect(rawdata)
            encoding = result['encoding']
            
            # Decodificar el archivo con la codificación detectada
            file_content = rawdata.decode(encoding, errors='replace')  # Manejar errores de codificación
            
            # Crear un archivo temporal CSV
            with tempfile.NamedTemporaryFile(mode='w+', newline='', delete=False, suffix=".csv") as temp_csv:
                # Escribir el contenido en el archivo temporal
                temp_csv.write(file_content)
                temp_csv.seek(0)  # Asegúrate de volver al inicio del archivo antes de leerlo

                # Leer el archivo CSV temporal con pandas, ignorando errores
                try:
                    df = pd.read_csv(temp_csv.name, delimiter='|', encoding=encoding, on_bad_lines='skip', header=None)
                except Exception as e:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': f'Error al leer el archivo: {str(e)}',
                            'type': 'danger',
                            'sticky': False,
                        }
                    }


        # Obtener las columnas del reporte y las columnas exportadas
        columnas = [col.columna for col in self.columnas_reporte_ids]  # Todas las columnas
        columnas_export = [col.columna for col in self.reporte_id.detalle_ids if col.orden_export >= 0]  # Columnas exportadas en orden
        columnas_export.sort(key=lambda col: next(col_detalle.orden_export for col_detalle in self.reporte_id.detalle_ids if col_detalle.columna == col))
        print(f'Columnas exportadas (en orden): {columnas_export}')

        # Verificar si la última columna está completamente vacía y eliminarla
        if df.columns[-1] == '' or df[df.columns[-1]].isnull().all():
            df = df.iloc[:, :-1]  # Elimina la última columna vacía

        # Verificar el número de columnas en el DataFrame
        print(f'Número de columnas del DataFrame: {len(df.columns)}')
        print(f'Número de columnas esperadas: {len(columnas)}')

        # Ajustar la cantidad de columnas si no coincide
        if len(df.columns) < len(columnas):
            # Agregar columnas vacías hasta que coincidan
            for i in range(len(df.columns), len(columnas)):
                df[f'Columna_{i}'] = ''

        # Asegurarse de que la cantidad de columnas coincida
        if len(df.columns) != len(columnas):
            raise ValueError(f'Error: El número de columnas en el DataFrame ({len(df.columns)}) no coincide con el número esperado de columnas ({len(columnas)}).')

        # Asignar las columnas completas al DataFrame
        df.columns = columnas
        
        # Ordenar el DataFrame de acuerdo a las columnas exportadas
        df = df[columnas_export]
        
        df = df.drop(0).reset_index(drop=True)
        # Mostrar los primeros 3 registros para validar
        df_head = df.head(3)
        print(df_head)

        # Filtrar el DataFrame para solo mostrar las columnas relevantes
        df_filtered = df[columnas_export]

        # Mostrar los primeros 3 registros en la vista del formulario
        table_html = df_filtered.head(3).to_html(classes='table table-bordered', border=0, index=False).replace("\n", "")

        # Reemplazar y agregar estilos directamente al HTML generado
        table_html = table_html.replace(
            '<table border="0" class="dataframe table table-bordered">',
            '<table style="width: 100%; table-layout: fixed; border-collapse: collapse;" class="table">'
        ).replace(
            '<th>', '<th style="width: 200px; padding: 8px; text-align: left; white-space: nowrap;">'
        ).replace(
            '<td>', '<td style="width: 200px; padding: 8px; text-align: left; white-space: nowrap;">'
        )

        # Guardar el contenido HTML de la tabla en el campo 'tabla_html'
        self.write({'tabla_html': table_html})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reporte procesado',
                'message': f'Reporte {reporte_dms} procesado correctamente.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }


    def aplicar_formula(self):
        # Obtener el DataFrame actual desde la tabla procesada
        df = self.obtener_dataframe()
        if df is None:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No se pudo obtener el DataFrame.',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Extraer las columnas del DataFrame y la columna seleccionada
        columnas = [col.columna for col in self.columnas_reporte_ids]
        print(f'Columnas: {columnas}')
        columna_seleccionada = self.columna_seleccionada.columna
        print(f'Columna Seleccionada: {columna_seleccionada}')

        # Validar que la columna seleccionada existe
        if not columna_seleccionada or columna_seleccionada not in columnas:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'La columna seleccionada no es válida.',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Validar que la fórmula tenga contenido
        formula = self.expresion.strip() if self.expresion else ""
        print(f'Formula: {formula}')
        if not formula:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error en la fórmula',
                    'message': 'No hay nada en el campo de expresión.',
                    'type': 'danger',
                    'sticky': True,  # Cambiar a True para que sea una notificación sticky
                }
            }

        # Validación de tipos de datos de las columnas involucradas en la fórmula
        try:
            columnas_en_formula = []
            for col in columnas:
                # Usa expresiones regulares para buscar coincidencias exactas de la columna en la fórmula
                if re.search(r'\b' + re.escape(col) + r'\b', formula):
                    columnas_en_formula.append(col)

            print(f'Columnas en formula: {columnas_en_formula}')
            
            # Validaciones de tipo de datos (por ejemplo, para fechas y números)
            for col in columnas_en_formula:
                detalle_columna = self.env['reporte.dms.detalle'].search([('columna', '=', col)], limit=1)

                print(f'Detalle_columna: {detalle_columna.tipo_dato}')
                if not detalle_columna:
                    continue

                # Si la fórmula contiene una operación de resta (-) y el tipo de dato es "date", convertir las columnas a datetime
                if '-' in formula and detalle_columna.tipo_dato == 'date':
                    df[col] = pd.to_datetime(df[col], errors='coerce')  # Convierte a datetime, manejar errores con 'coerce'

                # Si hay operaciones aritméticas, validar que las columnas sean numéricas
                if any(op in formula for op in ['+', '-', '*', '/']) and detalle_columna.tipo_dato == 'decimal':
                    df[col] = pd.to_numeric(df[col], errors='coerce')  # Convierte a número, manejar errores con 'coerce'

        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error en la validación de tipos de datos: {str(e)}',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Aplicar la fórmula con eval
        try:
            # Reemplazar las columnas con su representación en pandas (df['Columna'])
            for columna in columnas_en_formula:
                formula = formula.replace(columna, f"df['{columna}']")

            print(f'Formula después de reemplazar columnas: {formula}')
            
            # Aplicar el eval directamente a la columna seleccionada
            df[columna_seleccionada] = eval(formula)  # Evalúa la fórmula y la aplica a la columna seleccionada

            # Actualizar el campo 'tabla_html' con el DataFrame procesado, ocultando el índice y respetando el orden de las columnas
            table_html = df.to_html(classes='table table-bordered', border=0, index=False).replace("\n", "")

            # Reemplazar y agregar estilos directamente al HTML generado
            table_html = table_html.replace(
                '<table border="0" class="dataframe table table-bordered">', 
                '<table style="width: 100%; table-layout: fixed; border-collapse: collapse;" class="table">'
            ).replace(
                '<th>', '<th style="width: 200px; padding: 8px; text-align: left; white-space: nowrap;">'
            ).replace(
                '<td>', '<td style="width: 200px; padding: 8px; text-align: left; white-space: nowrap;">'
            )

            # Guardar el contenido HTML de la tabla en el campo 'tabla_html'
            self.write({'tabla_html': table_html})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Éxito',
                    'message': 'Fórmula aplicada correctamente.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'}
                }
            }

        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error al aplicar la fórmula',
                    'message': f'Error: {str(e)}',
                    'type': 'danger',
                    'sticky': False,
                }
            }


    def obtener_dataframe(self):
        """
        Función para obtener el DataFrame actual utilizando las columnas dinámicas
        y validar que coincidan con el reporte procesado.
        """
        try:
            # Obtener las columnas dinámicas definidas en el reporte
            columnas = [col.columna for col in self.columnas_reporte_ids]
            print(f'Columnas dinámicas: {columnas}')
            
            # Obtener las columnas exportadas en orden
            columnas_export = [col.columna for col in self.reporte_id.detalle_ids if col.orden_export >= 0]
            columnas_export.sort(key=lambda col: next(col_detalle.orden_export for col_detalle in self.reporte_id.detalle_ids if col_detalle.columna == col))
            print(f'Columnas exportadas (en orden): {columnas_export}')
            
            # Leer el archivo CSV desde la tabla actual en HTML
            # Esto simula obtener el contenido del DataFrame desde la tabla procesada previamente
            raw_html = self.tabla_html  # Obtener el HTML de la tabla
           
            if not raw_html:
                raise ValueError("No se ha procesado la tabla previamente.")

            # Extraer el contenido del HTML a un DataFrame
            dfs = pd.read_html(raw_html)  # Convertir la tabla HTML de vuelta a un DataFrame
            if len(dfs) == 0:
                raise ValueError("No se pudo extraer un DataFrame válido del HTML.")
            
            df = dfs[0]  # Tomar el primer DataFrame

            print(f'.... {df}')
            # Verificar si la última columna está completamente vacía y eliminarla
            # if df.columns[-1] == '' or df[df.columns[-1]].isnull().all():
            #     df = df.iloc[:, :-1]  # Eliminar la última columna vacía si todas sus celdas son nulas

            # Verificar el número de columnas en el DataFrame
            print(f'Número de columnas en el DataFrame: {len(df.columns)}')
            print(f'Número de columnas esperadas: {len(columnas)}')

            # Asegurarse de que la cantidad de columnas coincida
            if len(df.columns) != len(columnas):
                raise ValueError(f'Error: El número de columnas en el DataFrame ({len(df.columns)}) no coincide con el número esperado de columnas ({len(columnas)}).')

            #Asignar las columnas dinámicas al DataFrame
            df.columns = columnas_export
            print(f'DataFrame procesado:\n{df.head()}')

            return df

        except Exception as e:
            print(f'Error obteniendo el DataFrame dinámico: {str(e)}')
            return None




class FiltrosReportes(models.Model):
    _name = 'filtros.reportes'
    _description = 'Filtros Reportes'

    reporte_id = fields.Many2one('reporte.dms', string="Reporte DMS")
    expresion = fields.Text(string="Filtro")
    columnas_reporte_ids = fields.Many2many('reporte.dms.detalle', compute="_compute_columnas_reporte_filtro")
    
    @api.depends('reporte_id')
    def _compute_columnas_reporte_filtro(self):
        for record in self:
            if record.reporte_id:
                record.columnas_reporte_ids = [(6, 0, record.reporte_id.detalle_ids.ids)]
            else:
                record.columnas_reporte_ids = [(5,)]



class ReporteDMS(models.Model):
    _name = 'reporte.dms'
    _description = 'Reporte DMS'

    nombre = fields.Char(string="Nombre del Reporte", required=True, index=True)
    nombre_dms_origen = fields.Char(string="Nombre DMS Origen", readonly=True)
    detalle_export_ids = fields.One2many('reporte.dms.detalle', 'reporte_id', string="Orden Exportación")
    detalle_ids = fields.One2many('reporte.dms.detalle', 'reporte_id', string="Detalles")
    count_detalle_ids = fields.Integer("Cantidad de Detalles", compute='_compute_count_detalle_ids')
    dms_id = fields.Many2one('modelo.dms', string="DMS")
    file_data = fields.Binary(string="Archivo TXT")
    file_name = fields.Char(string="Nombre del Archivo")
    

    def duplicate_report(self):
        for record in self:
            # Crear una copia del registro principal
            new_record = record.copy({
                'nombre': f"{record.nombre}_copy"  # Cambiar el nombre del duplicado
            })

            # Duplicar los detalles del reporte (detalle_ids)
            for detalle in record.detalle_ids:
                detalle.copy({
                    'reporte_id': new_record.id
                })

            # Duplicar las fórmulas asociadas
            formulas = self.env['formulas.reportes'].search([('reporte_id', '=', record.id)])
            for formula in formulas:
                formula.copy({
                    'reporte_id': new_record.id
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',  # Recargar la vista
        }



    # Modificada para validar el nombre del reporte dentro del mismo nombre_dms_origen
    @api.model
    def create(self, vals):
        print(f'vals: {vals}')
        # Asegurarse de que se tenga 'nombre_dms_origen' correctamente
        nombre_dms_origen = vals.get('nombre')
        print(f'Nombredmsorigen: {nombre_dms_origen}')
        if not nombre_dms_origen:
            dms = self.env['modelo.dms'].browse(vals['dms_id'])
            nombre_dms_origen = dms.nombre_dms if dms else None
            vals['nombre_dms_origen'] = nombre_dms_origen

        if vals.get('nombre') and nombre_dms_origen:
            # Buscar existentes con el mismo nombre y nombre_dms_origen
            existing = self.search([
                ('nombre', '=', vals['nombre']),
                ('nombre_dms_origen', '=', nombre_dms_origen)
            ])
            if existing:
                raise ValidationError("El nombre del reporte debe ser único dentro del mismo origen DMS.")

        return super(ReporteDMS, self).create(vals)
    

    # @api.model
    # def create(self, vals):
    #     # Obtener el nombre_dms_origen del contexto si no está en vals
    #     nombre_dms_origen = vals.get('nombre_dms_origen', self.env.context.get('default_nombre_dms_origen'))
    #     print(f'Nombre_dms_origen: {nombre_dms_origen}')
    #     if nombre_dms_origen:
    #         dms = self.env['modelo.dms'].search([('nombre_dms', '=', nombre_dms_origen)], limit=1)
    #         if dms:
    #             vals['dms_id'] = dms.id
    #             vals['nombre_dms_origen'] = nombre_dms_origen  # Asegúrate de que este campo se establezca si es necesario

    #     return super(ReporteDMS, self).create(vals)

    def write(self, vals):
        # Verificar si el campo nombre está vacío
        if not self.nombre and 'file_data' in vals:
            raise ValidationError("No puedes cargar un archivo si no has asignado un nombre al reporte.")

        # Validación del nombre del reporte
        if 'nombre' in vals or 'nombre_dms_origen' in vals:
            nombre = vals.get('nombre', self.nombre)
            nombre_dms_origen = vals.get('nombre_dms_origen', self.nombre_dms_origen)
            existing = self.search([
                ('nombre', '=', nombre),
                ('nombre_dms_origen', '=', nombre_dms_origen),
                ('id', '!=', self.id)
            ])
            if existing:
                raise ValidationError("El nombre del reporte debe ser único dentro del mismo origen DMS.")

        # Validación del nombre del archivo
        if 'file_data' in vals and 'file_name' in vals:
            # Asegurarse de que el reporte tiene un nombre asignado antes de cargar el archivo
            if not self.nombre:
                raise ValidationError("Debes asignar un nombre al reporte antes de cargar el archivo.")

            nombre_reporte = re.sub(r'\d', '', self.nombre)  # Elimina los números del nombre del reporte
            nombre_archivo = re.sub(r'\d', '', vals['file_name'].split('.')[0])  # Elimina números del archivo y la extensión

            # Comparar los nombres
            if nombre_reporte != nombre_archivo:
                raise ValidationError("El nombre del archivo no coincide con el nombre del reporte.")

        return super(ReporteDMS, self).write(vals)

    @api.depends('detalle_ids')
    def _compute_count_detalle_ids(self):
        for record in self:
            record.count_detalle_ids = len(record.detalle_ids)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.nombre))
        return result
    

    def order_export(self):
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ordenar Columnas de Exportación',
            'view_mode': 'tree',
            'res_model': 'reporte.dms.detalle',
            'domain': [('reporte_id', '=', self.id)],
            'context': {'create': False, 'edit': True},
            'views': [(self.env.ref('procesamiento.view_reporte_dms_detalle_order_export_tree').id, 'tree')],
            'target': 'new',  # Abre la vista en una ventana modal
        }


    def action_open_formulas(self):
        # Iterar a través de las columnas del reporte
        detalle_ids = self.env['reporte.dms.detalle'].search([('reporte_id', '=', self.id)])

        for columna in detalle_ids:
            # Buscar o crear un registro en formulas.reportes para cada columna
            formula_record = self.env['formulas.reportes'].search([
                ('reporte_id', '=', self.id),
                ('columna_seleccionada', '=', columna.id)
            ], limit=1)
            
            # Crear el registro si no existe
            if not formula_record:
                formula_record = self.env['formulas.reportes'].create({
                    'reporte_id': self.id,
                    'columna_seleccionada': columna.id
                })

            # Asignar la expresión de acuerdo con las condiciones, sólo si está vacío o necesita ser actualizado
            if not formula_record.expresion:
                if columna.columna == "Date":
                    formula_record.expresion = 'Ctod("d/m/y")'
                elif 'email' in columna.columna.lower() or 'mail' in columna.columna.lower():
                    formula_record.expresion = f'LimpiaEmail({columna.columna})'
                elif columna.tipo_dato == 'varchar':
                    formula_record.expresion = f'LimpiaTexto({columna.columna})'
                elif columna.tipo_dato == 'decimal':
                    formula_record.expresion = f'LimpiaCodigos({columna.columna})'

        # Abrir la vista de fórmulas de reportes después de la actualización
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fórmulas de Reportes',
            'res_model': 'formulas.reportes',
            'view_mode': 'tree,form',
            'domain': [('reporte_id', '=', self.id)],
            'context': {'default_reporte_id': self.id},
            'target': 'current',
        }




    def action_open_filter(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Filtros',
            'view_mode': 'tree,form',
            'res_model': 'filtros.reportes',
            'target': 'current',
            'domain': [('reporte_id', '=', self.id)],
            'context': {'default_reporte_id': self.id},
        }


    def action_upload_file(self):
        """
        Acción para procesar el archivo subido.
        """
        if not self.file_data or not self.file_name:
            raise ValidationError("Por favor, cargue un archivo TXT.")
        
        # Procesamiento del archivo aquí...
        # Ejemplo: Decodificar el archivo si es binario y procesarlo como texto
        file_content = base64.b64decode(self.file_data).decode('utf-8')
        # Puedes implementar la lógica para procesar el contenido aquí
        print(f"Archivo cargado con éxito: {self.file_name}")


    def procesar_archivo(self):
        """Procesa el archivo y extrae las columnas para llenar detalle_ids"""
        if not self.file_data:
            raise ValidationError("No has subido ningún archivo para procesar.")

        # Decodificar el archivo desde el campo 'file_data'
        file_data = base64.b64decode(self.file_data)
        
        # Detectar la codificación usando chardet
        detection = chardet.detect(file_data)
        encoding = detection.get('encoding', 'utf-8')  # Si no detecta, usar utf-8 como predeterminado

        try:
            file_content = file_data.decode(encoding)
        except UnicodeDecodeError:
            raise ValidationError(f"El archivo contiene caracteres inválidos y no puede ser decodificado con la codificación detectada: {encoding}")

        # Reemplazar 'A¤o' por 'Ano' en el contenido
        file_content = file_content.replace('A¤o', 'Ano')

        # Obtener la primera línea para las columnas y eliminar columnas vacías
        columnas = [col for col in file_content.splitlines()[0].split('|') if col]

        # Renombrar columnas duplicadas agregando un número secuencial
        columnas_contador = Counter(columnas)
        columnas_renombradas = []
        columnas_usadas = {}

        for columna in columnas:
            if columnas_contador[columna] > 1:
                # Si ya existe la columna, se agrega el número adecuado (Celular, Celular2, Celular3, etc.)
                if columna in columnas_usadas:
                    columnas_usadas[columna] += 1
                else:
                    columnas_usadas[columna] = 1
                columna_renombrada = f"{columna}{columnas_usadas[columna]}"
            else:
                columna_renombrada = columna
            
            columnas_renombradas.append(columna_renombrada)

        # Limpiar los detalles previos
        self.detalle_ids.unlink()

        # Llenar detalle_ids con las columnas detectadas, estableciendo tipo_dato en 'varchar' y longitud en 255
        detalles_vals = []
        for idx, columna in enumerate(columnas_renombradas):
            detalles_vals.append({
                'sequence': idx + 1,  # Orden secuencial
                'columna': columna,   # Nombre de la columna
                'tipo_dato': 'varchar',  # Tipo de dato predefinido
                'longitud': 255,  # Longitud predefinida
            })

        # Crear los registros en detalle_ids
        self.write({'detalle_ids': [(0, 0, val) for val in detalles_vals]})

        # Llamar a la acción que abrirá la ventana modal con las columnas
        return {
            'type': 'ir.actions.act_window',
            'name': 'Columnas Detectadas',
            'view_mode': 'tree',
            'res_model': 'reporte.dms.detalle',
            'domain': [('reporte_id', '=', self.id)],
            'context': {'create': False},
            'target': 'new',  # 'new' para abrir en una ventana modal
        }

    
    def importar_columnas(self):
        """ Importa todas las columnas desde el modal y las guarda en detalle_ids """
        detalle_ids = self.env['reporte.dms.detalle'].search([('reporte_id', '=', self.id)])
        
        # Procesar y guardar las columnas seleccionadas en detalle_ids del registro actual
        detalles_vals = []
        for detalle in detalle_ids:
            detalles_vals.append({
                'sequence': detalle.sequence,
                'columna': detalle.columna,
                'tipo_dato': detalle.tipo_dato,
                'longitud': detalle.longitud,
            })
        
        # Actualizar el campo detalle_ids en reporte.dms con los valores procesados
        self.write({'detalle_ids': [(0, 0, val) for val in detalles_vals]})
    


class ReportesDMS(models.Model):
    _name = 'reportes.dms'
    _description = 'Reportes DMS'

    nombre_reporte = fields.Char(string="Nombre del Reporte", required=True)
    descripcion = fields.Text(string="Descripción")
    nombre_dms_origen = fields.Char(string="Nombre DMS Origen", readonly=True) 


class ReporteDMSDetalle(models.Model):
    _name = 'reporte.dms.detalle'
    _description = 'Detalle de Reporte DMS'
    _order = 'sequence'

    reporte_id = fields.Many2one('reporte.dms', string="Reporte", required=True, ondelete='cascade')
    ordenamiento = fields.Char(string="Ordenamiento", compute='_compute_ordenamiento', store=True)
    columna = fields.Char(string="Columna")
    tipo_dato = fields.Selection([
        ('decimal', 'Decimal'),
        ('date', 'Date'),
        ('varchar', 'Varchar')
    ], string="Tipo de Dato")
    longitud = fields.Integer(string="Longitud", default=0)
    invisible = fields.Boolean(string="Invisible", default=False)
    compute_field = fields.Boolean(string="Campo Computado", default=False)
    sequence = fields.Integer(string="Secuencia")
    expresion = fields.Html(string="Expresión", sanitize=False, strip_style=False)

    # Nuevo campo para el orden de exportación
    orden_export = fields.Integer(string="Orden de Exportación", default=0)

    _rec_name = 'columna'



    @api.model
    def create(self, vals):
        # Verificar si la columna ya existe para el mismo ID de reporte
        if 'columna' in vals and 'reporte_id' in vals:
            existing = self.env['reporte.dms.detalle'].search([
                ('columna', '=', vals['columna']),
                ('reporte_id', '=', vals['reporte_id'])
            ], limit=1)
            if existing:
                raise ValidationError("La columna '{}' ya está en uso para el mismo reporte.".format(vals['columna']))

        # Asignar la secuencia pero solo dentro del mismo reporte
        if 'reporte_id' in vals:
            last_detail = self.env['reporte.dms.detalle'].search([
                ('reporte_id', '=', vals['reporte_id'])
            ], order='sequence desc', limit=1)
            next_sequence = (last_detail.sequence + 1) if last_detail else 1
            vals['sequence'] = next_sequence

        # Crear el registro
        record = super(ReporteDMSDetalle, self).create(vals)

        # Asegurarse de que el campo ordenamiento se calcula correctamente
        record._compute_ordenamiento()

        return record


    
    @api.constrains('columna', 'reporte_id')
    def _check_columna(self):
        for record in self:
            # Asegurarte de que 'reporte_id' contiene un ID y no un recordset.
            reporte_id = record.reporte_id.id if record.reporte_id else False
            domain = [('columna', '=', record.columna), ('reporte_id', '=', reporte_id), ('id', '!=', record.id)]
            existing = self.search(domain, limit=1)
            if existing:
                raise ValidationError("La columna '{}' ya está en uso para el reporte actual.".format(record.columna))


    def action_add_columna_to_expresion(self):
        # Obtener el ID de la columna desde el contexto
        columna_id = self.env.context.get('columna_id')
        if columna_id:
            columna = self.env['reporte.dms.detalle'].browse(columna_id).columna
            # Si existe la columna, añadirla a la expresión
            for record in self:
                if columna:
                    if record.expresion:
                        record.expresion += f" {columna}"
                    else:
                        record.expresion = columna


    @api.depends('sequence')
    def _compute_ordenamiento(self):
        for record in self:
            record.ordenamiento = f'F{record.sequence}'

    @api.onchange('tipo_dato')
    def _onchange_tipo_dato(self):
        if self.tipo_dato == 'varchar':
            self.longitud = 50  
        elif self.tipo_dato == 'decimal':
            self.longitud = 18  
        else:
            self.longitud = 0

    
