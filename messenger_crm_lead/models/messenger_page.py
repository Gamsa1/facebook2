from odoo import fields, models


class MessengerPage(models.Model):
    _name = 'messenger.page'
    _description = 'Facebook/Instagram Page for Messenger'
    _rec_name = 'name'

    name = fields.Char(required=True)
    page_id = fields.Char(string='Facebook Page ID', required=True, index=True)
    page_access_token = fields.Char(string='Page Access Token', required=True)
    active = fields.Boolean(default=True)

    _page_id_unique = models.Constraint(
        'unique(page_id)',
        'This Facebook Page ID is already configured.',
    )