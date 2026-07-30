from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    messenger_conversation_id = fields.One2many('messenger.message', 'lead_id',
                                                 string='Messenger Conversation')
    messenger_line_ids = fields.Many2many('messenger.message.line',
                                          compute='_compute_messenger_line_ids',
                                          string='Conversation Messages')

    @api.depends('id')
    def _compute_messenger_line_ids(self):
        for lead in self:
            convo = self.env['messenger.message'].search([('lead_id', '=', lead.id)], limit=1)
            lead.messenger_line_ids = convo.line_ids.ids if convo else False