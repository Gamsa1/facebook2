{
    'name': 'Social Inbox: Messenger & Instagram',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Receive Facebook Messenger & Instagram DM and convert to CRM Leads with 1 click.',
    'description': """
        Features:
        - Webhook for Facebook Messenger & Instagram DM
        - Incoming messages stored in Odoo inbox
        - 1-Click Convert to Lead button
        - Auto-create lead option
        - Settings for Page Access Token & Verify Token
    """,
    'author': 'Saydun Nobi',
    'website': '',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/messenger_message_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
