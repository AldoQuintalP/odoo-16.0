{
    'name': 'Procesamiento',
    'version': '16.0.1.0.0',
    'summary': 'Modulo que agrega al odoo la configuración para Procesamiento de SimData',
    'sequence': 10,
    'description': """
        Modulo que agrega al odoo la configuración para Procesamiento de SimDataGroup
    """,
    'category': 'Tools',
    'author': 'Aldo',
    'depends': ['base', 'website'],
    'data': [

        'security/ir.model.access.csv',
        'security/security_groups.xml',
        
        'views/mi_modelo_views.xml',
        'views/cliente_configuracion_views.xml',
        'views/res_config_settings_views.xml',
        'views/config_inicial_views.xml',
        
        'views/odoo_web_view.xml',
        #'views/success_template_view.xml',
        

    ],
    'assets': {
        'web.assets_backend': [
            'procesamiento/static/src/css/custom_style.css',
        ],
    },

    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'image': 'static/description/icon.png'
}
