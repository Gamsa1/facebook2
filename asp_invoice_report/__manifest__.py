# -*- coding: utf-8 -*-
{
    'name': 'ASP Invoice Report',
    'version': '1.0',
    'summary': 'Custom invoice PDF layout matching ASP Group\'s official invoice form',
    'category': 'Accounting/Accounting',
    'author': 'ASP Group',
    'depends': ['account'],
    'data': [
        'views/asp_invoice_report.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}