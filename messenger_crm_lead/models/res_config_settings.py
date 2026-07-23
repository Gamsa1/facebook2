from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    messenger_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='messenger_crm_lead.verify_token',
        help='A secret string you choose and enter in Meta Developer Console to verify the webhook.',
    )

    messenger_auto_lead = fields.Boolean(
        string='Auto-create Lead on New Message',
        config_parameter='messenger_crm_lead.auto_lead',
        help='If enabled, a CRM Lead is created immediately when a new message arrives.',
    )