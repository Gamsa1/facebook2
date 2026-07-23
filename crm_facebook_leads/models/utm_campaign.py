from odoo import fields, models


class UtmCampaign(models.Model):
    _inherit = 'utm.campaign'

    id_facebook_campaign = fields.Char(string="Facebook Campaign ID")

    _facebook_campaign_unique = models.Constraint(
        'unique(id_facebook_campaign)', 'This Facebook Campaign already exists!')
