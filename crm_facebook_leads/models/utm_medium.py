from odoo import fields, models


class UtmMedium(models.Model):
    _inherit = 'utm.medium'

    id_facebook_ad = fields.Char(string="Facebook Ad ID")

    _facebook_ad_unique = models.Constraint(
        'unique(id_facebook_ad)', 'This Facebook Ad already exists!')
