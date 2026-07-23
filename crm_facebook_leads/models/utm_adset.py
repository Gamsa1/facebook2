from odoo import fields, models


class UtmAdset(models.Model):
    _name = 'utm.adset'
    _description = 'Utm Adset'

    name = fields.Char()
    id_facebook_adset = fields.Char(string="Adset ID")

    _facebook_adset_unique = models.Constraint(
        'unique(id_facebook_adset)', 'This Facebook AdSet already exists!')
